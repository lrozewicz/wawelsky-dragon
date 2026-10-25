"""Usługa tras dokumentów poza ``/datasets/{id}/documents`` (scenariusz documents_extras).

Osobny moduł od ``app/services/documents.py`` — limit 400 linii ``check_file_size.py``.
Uprawnienia wyłącznie przez ``DatasetService.load`` (C1.2); ``Container`` pod
``TYPE_CHECKING`` (wzór: ``app/services/documents.py``).

Zakres fragmentu (E2-1 DOC): ``PATCH …/documents/metadatas`` (kroki 13-14) oraz
``POST …/documents/batch-update-status`` (kroki 15-16); dodatkowo E2-2a T4 —
``POST /v1/document/change_status`` (kroki 17-18, te same wpisy statusu, inna trasa).
Trasy ``/documents/ingest``,
``/documents/upload``, ``/thumbnails``, ``GET /documents/{id}`` (+``/preview``),
``GET /documents/images/{id}`` — poza tym fragmentem.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import Conflict, NotFound
from app.db.repositories import documents as documents_repo
from app.db.repositories import documents_query
from app.db.uow import transaction
from app.domain.policy import Action, Principal
from app.domain.retrieval.metadata import MetadataCondition, match_documents
from app.services.datasets import DatasetService
from app.services.documents import MSG_DOCS_NOT_FOUND

if TYPE_CHECKING:
    from app.core.container import Container

__all__ = [
    "MSG_METADATA_FOREIGN",
    "MSG_STATUS_PARTIAL",
    "DocumentExtraService",
    "StatusesResult",
]

MSG_METADATA_FOREIGN = "These documents do not belong to dataset {dataset_id}: {ids}"  # DOC:1432
MSG_STATUS_PARTIAL = "Partial failure"  # DOC:2064


@dataclass(frozen=True)
class StatusesResult:
    """Wynik ``batch-update-status``: mapa doc_id → wpis i flaga błędu częściowego."""

    entries: dict[str, dict[str, str]]
    has_error: bool


def _apply_updates(meta: dict[str, Any], updates: Sequence[Mapping[str, Any]]) -> bool:
    """Zapis wartości do metadanych; True, gdy cokolwiek się zmieniło (DOC:1271-1315)."""
    changed = False
    for update in updates:
        key = str(update["key"])
        if key in meta and meta[key] == update["value"]:
            continue
        meta[key] = update["value"]
        changed = True
    return changed


def _apply_deletes(meta: dict[str, Any], deletes: Sequence[Mapping[str, Any]]) -> bool:
    """Usuwa klucze metadanych; brak klucza nic nie zmienia (DOC:1317-1345)."""
    changed = False
    for deletion in deletes:
        if str(deletion["key"]) in meta:
            del meta[str(deletion["key"])]
            changed = True
    return changed


class DocumentExtraService:
    """Metadane zbiorcze dokumentów i zbiorcza zmiana statusu (fragment E2-1 DOC)."""

    def __init__(self, container: Container) -> None:
        self._container = container

    def _sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        """Fabryka sesji z kontenera (C0 p. 2)."""
        return cast(async_sessionmaker[AsyncSession], self._container.sessionmaker)

    async def metadatas(  # noqa: PLR0913 — kształt żądania upstream (selector + updates + deletes)
        self,
        principal: Principal,
        dataset_id: str,
        *,
        document_ids: Sequence[str],
        updates: Sequence[Mapping[str, Any]],
        deletes: Sequence[Mapping[str, Any]],
        condition: MetadataCondition | None = None,
    ) -> tuple[int, int]:
        """Aktualizuje meta_fields wybranych dokumentów; zwraca (updated, matched_docs).

        Kolejność wg upstream ``update_document_metadata`` (DOC:1426-1444): dokumenty spoza
        datasetu → 102, potem ``metadata_condition`` zawęża zbiór; warunek z niepustymi
        ``conditions`` i pustym wynikiem kończy żądanie ``0/0`` bez zapisu.
        """
        await DatasetService(self._container).load(principal, dataset_id, Action.UPDATE)
        unique_ids = list(dict.fromkeys(document_ids))
        async with transaction(self._sessionmaker()) as session:
            present = await documents_query.ids_in_dataset(session, dataset_id, unique_ids)
        foreign = [doc_id for doc_id in unique_ids if doc_id not in present]
        if foreign:
            raise Conflict(
                MSG_METADATA_FOREIGN.format(dataset_id=dataset_id, ids=", ".join(foreign))
            )
        if not unique_ids:
            return 0, 0
        target = unique_ids
        if condition is not None:
            async with transaction(self._sessionmaker()) as session:
                metas = await documents_query.meta_fields_by_document(session, dataset_id)
            matched = match_documents(metas, condition)
            target = [doc_id for doc_id in unique_ids if doc_id in matched]
            if condition.conditions and not target:
                return 0, 0
        updated = 0
        async with transaction(self._sessionmaker()) as session:
            docs = await documents_repo.get_many(session, target)
            now = self._container.clock.now_ms()
            for doc in docs:
                meta = copy.deepcopy(doc.meta_fields)
                changed = _apply_updates(meta, updates)
                changed = _apply_deletes(meta, deletes) or changed
                if changed:
                    await documents_query.update_meta(
                        session, doc.id, {"meta_fields": meta}, now_ms=now
                    )
                    updated += 1
        return updated, len(docs)

    async def set_status(
        self,
        principal: Principal,
        dataset_id: str,
        doc_ids: Sequence[str],
        status: str,
    ) -> StatusesResult:
        """Ustawia ``enabled`` dokumentów datasetu; zwraca wpisy per dokument (DOC:2020-2065)."""
        await DatasetService(self._container).load(principal, dataset_id, Action.UPDATE)
        entries: dict[str, dict[str, str]] = {}
        has_error = False
        async with transaction(self._sessionmaker()) as session:
            docs = {doc.id: doc for doc in await documents_repo.get_many(session, doc_ids)}
            now = self._container.clock.now_ms()
            for doc_id in dict.fromkeys(doc_ids):
                doc = docs.get(doc_id)
                if doc is None:
                    entries[doc_id] = {"error": "Document not found"}
                    has_error = True
                    continue
                if doc.dataset_id != dataset_id:
                    entries[doc_id] = {"error": "Document not found in this dataset."}
                    has_error = True
                    continue
                if ("1" if doc.enabled else "0") != status:
                    await documents_query.update_meta(
                        session, doc_id, {"enabled": status == "1"}, now_ms=now
                    )
                entries[doc_id] = {"status": status}
        return StatusesResult(entries=entries, has_error=has_error)

    async def statuses_by_document(
        self, principal: Principal, doc_ids: Sequence[str], status: str
    ) -> dict[str, dict[str, str]]:
        """Zmiana ``enabled`` dokumentów po samych id (legacy ``POST /v1/document/change_status``).

        Trasa nie ma datasetu w ścieżce, więc dataset bierze się z wiersza dokumentu.
        Wszystkie sprawdzenia (istnienie wiersza, własność datasetu przez ``DatasetService.load``)
        idą **przed** pierwszą zmianą: cudzy albo nieistniejący dokument przerywa całe żądanie
        bez mutacji (CONTRACT C0 p. 9). Wyjątek zamienia na odmowę trasa (``refuse``).
        """
        unique_ids = list(dict.fromkeys(doc_ids))
        async with transaction(self._sessionmaker()) as session:
            docs = await documents_repo.get_many(session, unique_ids)
        present = {doc.id for doc in docs}
        missing = [doc_id for doc_id in unique_ids if doc_id not in present]
        if missing:
            raise NotFound(MSG_DOCS_NOT_FOUND.format(ids=repr(missing)))
        grouped: dict[str, list[str]] = {}
        for doc in docs:
            grouped.setdefault(doc.dataset_id, []).append(doc.id)
        for dataset_id in grouped:
            await DatasetService(self._container).load(principal, dataset_id, Action.UPDATE)
        entries: dict[str, dict[str, str]] = {}
        for dataset_id, ids in grouped.items():
            entries.update((await self.set_status(principal, dataset_id, ids, status)).entries)
        return entries
