"""Usługa metadanych dokumentów datasetu (zadanie DS3, E2-1) — trasy ``metadata/*``.

Pięć operacji v0.27.2: konfiguracja metadanych datasetu (``metadata/config``, trzymana
w ``datasets.parser_config`` pod kluczami ``metadata`` i ``built_in_metadata`` — tak jak
upstream ``dataset_api_service.get/update_auto_metadata``), podsumowanie wartości pól
(``metadata/summary``), masowa zmiana metadanych dokumentów (``metadata/update``) i słownik
spłaszczony po datasetach (``metadata/flattened``). Semantyka agregacji i operacji na
metadanych to port ``api/db/services/doc_metadata_service.py`` (v0.27.2) na tabelę
``documents`` (kolumna ``meta_fields`` JSON); WD nie ma indeksu ``ragflow_doc_meta_*``.

Uprawnienia wyłącznie przez ``app.domain.policy`` (przez ``DatasetService.load``).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import Conflict
from app.db.repositories import datasets as datasets_repo
from app.db.repositories import documents as documents_repo
from app.db.repositories import documents_query
from app.db.repositories.datasets import DatasetRecord
from app.db.repositories.documents import DocumentRow
from app.db.uow import transaction
from app.domain.policy import Action, Principal
from app.domain.retrieval.metadata import MetadataCondition, match_documents
from app.services.datasets import MSG_DATASET_LACKS, DatasetService

if TYPE_CHECKING:
    from app.core.container import Container

__all__ = [
    "BUILT_IN_KEY",
    "METADATA_KEY",
    "MSG_CONDITION_OBJECT",
    "MSG_DELETE_ENTRY",
    "MSG_DOCUMENT_NOT_IN_DATASET",
    "MSG_DOC_IDS_LIST",
    "MSG_FOREIGN_DOCS",
    "MSG_LISTS",
    "MSG_SELECTOR_OBJECT",
    "MSG_UPDATE_ENTRY",
    "DatasetMetadataService",
    "MetadataSummaryField",
    "MetadataUpdateResult",
]

# Klucze konfiguracji metadanych w ``datasets.parser_config`` (upstream dataset_api_service).
METADATA_KEY = "metadata"
BUILT_IN_KEY = "built_in_metadata"

# Komunikaty 1:1 z upstream ``document_api.py:359`` (metryka/update) — kod DATA_ERROR (102).
MSG_SELECTOR_OBJECT = "selector must be an object."
MSG_LISTS = "updates and deletes must be lists."
MSG_CONDITION_OBJECT = "metadata_condition must be an object."
MSG_DOC_IDS_LIST = "document_ids must be a list."
MSG_UPDATE_ENTRY = "Each update requires key and value."
MSG_DELETE_ENTRY = "Each delete requires key."
MSG_FOREIGN_DOCS = "These documents do not belong to dataset {dataset_id}: {ids}"
# Komunikat trasy S-320 dla dokumentu spoza datasetu (upstream document_api.py:1269, kod 102).
MSG_DOCUMENT_NOT_IN_DATASET = "document {document_id} not found in dataset {dataset_id}"

# Rozpoznanie wartości czasu w podsumowaniu (upstream _is_time_string, :1152).
_TIME_VALUE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


@dataclass(frozen=True)
class MetadataSummaryField:
    """Pole podsumowania: typ wartości i pary (wartość, liczba) malejąco po liczbie."""

    type: str
    values: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class MetadataUpdateResult:
    """Wynik ``metadata/update``: liczba dopasowanych i faktycznie zmienionych dokumentów."""

    matched_docs: int
    updated: int


def _dedupe(values: Sequence[Any]) -> list[Any]:
    """Usuwa powtórzone wartości po ``str()``, zachowując kolejność (upstream dedupe_list)."""
    seen: set[str] = set()
    deduped: list[Any] = []
    for item in values:
        key = str(item)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _normalize_meta(meta: Any) -> dict[str, Any]:
    """Metadane dokumentu jako dict: str → JSON, inne typy → {} (upstream _normalize_meta)."""
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except ValueError:
            return {}
    if not isinstance(meta, dict):
        return {}
    return deepcopy(meta)


def _updated_list(current: list[Any], new_value: Any, match_value: Any) -> list[Any] | None:
    """Nowa wartość listy metadanych; None gdy ``match`` nie pasuje do żadnej pozycji.

    Bez ``match`` (None albo pusty łańcuch) nowa wartość jest dopisywana z deduplikacją;
    z ``match`` pozycje równe wartości są zamieniane (upstream ``_apply_updates``).
    """
    if match_value is None or match_value == "":
        added = new_value if isinstance(new_value, list) else [new_value]
        return _dedupe(current + added)
    if not any(str(item) == str(match_value) for item in current):
        return None
    return _dedupe([new_value if str(item) == str(match_value) else item for item in current])


def _apply_update(meta: dict[str, Any], update: Mapping[str, Any]) -> bool:
    """Nakłada jedną aktualizację na metadane; zwraca czy zmieniła cokolwiek (upstream :1271).

    ``match`` (niepusty) zawęża zmianę do pozycji równych wartości, a gdy pole jeszcze nie
    istnieje — pomija aktualizację.
    """
    key = update.get("key")
    new_value = update.get("value")
    match_value = update.get("match")
    match_provided = match_value is not None and match_value != ""
    if not key or (match_provided and key not in meta):
        return False
    if key in meta:
        current = meta[key]
        if isinstance(current, list):
            updated = _updated_list(current, new_value, match_value)
            if updated is None:
                return False
            current = updated
        elif match_provided and str(current) != str(match_value):
            return False
        else:
            current = new_value
    else:
        current = _dedupe(new_value) if isinstance(new_value, list) else new_value
    meta[key] = current
    return True


def _apply_updates(meta: dict[str, Any], updates: Sequence[Mapping[str, Any]]) -> bool:
    """Nakłada wszystkie aktualizacje; zwraca czy cokolwiek zmieniono (upstream :1271-1320)."""
    changed = False
    for update in updates:
        changed = _apply_update(meta, update) or changed
    return changed


def _apply_deletes(meta: dict[str, Any], deletes: Sequence[Mapping[str, Any]]) -> bool:
    """Usuwa pola/pozycje wg ``deletes``; zwraca czy cokolwiek zmieniono (upstream :1321-1350)."""
    changed = False
    for delete in deletes:
        key = delete.get("key")
        if not key or key not in meta:
            continue
        value = delete.get("value")
        if isinstance(meta[key], list):
            if value is None:
                del meta[key]
                changed = True
                continue
            kept = [item for item in meta[key] if str(item) != str(value)]
            if len(kept) != len(meta[key]):
                if kept:
                    meta[key] = kept
                else:
                    del meta[key]
                changed = True
        elif value is None or str(meta[key]) == str(value):
            del meta[key]
            changed = True
    return changed


def _value_type(value: Any) -> str | None:
    """Typ wartości metadanej wg upstream ``_meta_value_type`` (None → brak typu)."""
    if value is None:
        return None
    if isinstance(value, list):
        return "list"
    if isinstance(value, bool):
        return "string"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str) and _TIME_VALUE_RE.match(value):
        return "time"
    return "string"


def _summarize(metas: Mapping[str, Mapping[str, Any]]) -> dict[str, MetadataSummaryField]:
    """Agreguje wartości pól po dokumentach (upstream ``get_metadata_summary``, :1134-1224).

    Liczniki wartości po ``str()``; typ pola to najczęstszy typ wartości (remis → pierwszy
    napotkany); pary sortowane malejąco po liczbie (remis → kolejność napotkania).
    """
    counts: dict[str, dict[str, int]] = {}
    type_counts: dict[str, dict[str, int]] = {}
    for meta in metas.values():
        for key, value in meta.items():
            value_type = _value_type(value)
            if value_type is not None:
                per_type = type_counts.setdefault(key, {})
                per_type[value_type] = per_type.get(value_type, 0) + 1
            for item in value if isinstance(value, list) else [value]:
                if item is None:
                    continue
                text = str(item)
                per_value = counts.setdefault(key, {})
                per_value[text] = per_value.get(text, 0) + 1
    summary: dict[str, MetadataSummaryField] = {}
    for key, per_value in counts.items():
        values = tuple(sorted(per_value.items(), key=lambda pair: pair[1], reverse=True))
        per_type = type_counts.get(key, {})
        value_type = max(per_type.items(), key=lambda pair: pair[1])[0] if per_type else "string"
        summary[key] = MetadataSummaryField(type=value_type, values=values)
    return summary


def _merge_flattened(
    target: dict[str, dict[str, list[str]]], metas: Mapping[str, Mapping[str, Any]]
) -> None:
    """Dokłada dokumenty do słownika {pole: {wartość: [document_id]}} (upstream :763-857)."""
    for doc_id, meta in metas.items():
        for key, value in meta.items():
            per_value = target.setdefault(key, {})
            for item in value if isinstance(value, list) else [value]:
                if item is None:
                    continue
                per_value.setdefault(str(item), []).append(doc_id)


def _config(parser_config: Mapping[str, Any]) -> dict[str, list[Any]]:
    """Konfiguracja metadanych z ``parser_config``; brak/nie-lista → pusta lista (:752-765)."""
    metadata = parser_config.get(METADATA_KEY)
    built_in = parser_config.get(BUILT_IN_KEY)
    return {
        METADATA_KEY: list(metadata) if isinstance(metadata, list) else [],
        BUILT_IN_KEY: list(built_in) if isinstance(built_in, list) else [],
    }


class DatasetMetadataService:
    """Konfiguracja, podsumowanie, masowa zmiana i spłaszczenie metadanych datasetu."""

    def __init__(self, container: Container) -> None:
        self._container = container

    def _sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        """Fabryka sesji z kontenera (C0 p. 2)."""
        return cast(async_sessionmaker[AsyncSession], self._container.sessionmaker)

    async def _dataset(
        self, principal: Principal, dataset_id: str, action: Action = Action.READ
    ) -> DatasetRecord:
        """Dataset po id z kontrolą dostępu (komunikat braku jak w trasach datasetów)."""
        return await DatasetService(self._container).load(
            principal, dataset_id, action, missing=MSG_DATASET_LACKS
        )

    async def get_config(self, principal: Principal, dataset_id: str) -> dict[str, list[Any]]:
        """GET ``metadata/config``: konfiguracja z ``datasets.parser_config`` (--11)."""
        record = await self._dataset(principal, dataset_id)
        return _config(record.parser_config)

    async def put_config(
        self,
        principal: Principal,
        dataset_id: str,
        metadata: list[dict[str, Any]],
        built_in_metadata: list[dict[str, Any]],
    ) -> dict[str, list[Any]]:
        """PUT ``metadata/config``: zapis obu list do ``parser_config``; zwraca zapisane (--12)."""
        record = await self._dataset(principal, dataset_id, Action.UPDATE)
        merged = deepcopy(record.parser_config)
        merged[METADATA_KEY] = metadata
        merged[BUILT_IN_KEY] = built_in_metadata
        async with transaction(self._sessionmaker()) as session:
            await datasets_repo.update_fields(
                session,
                dataset_id,
                {"parser_config": merged},
                now_ms=self._container.clock.now_ms(),
            )
        return {METADATA_KEY: list(metadata), BUILT_IN_KEY: list(built_in_metadata)}

    async def put_document_metadata_config(
        self, principal: Principal, dataset_id: str, document_id: str, metadata: Any
    ) -> DocumentRow | None:
        """PUT ``…/documents/{id}/metadata/config``: zapis ``parser_config.metadata`` (S-320).

        Kolejność upstream ``document_api.py:1262-1288``: dostęp do datasetu (102 „you don't
        own the dataset" — profil odmowy trasy), dokument w datasecie (brak → ``None``; trasa
        oddaje 102 „document <id> not found in dataset <id>"), dopiero potem ciało (101 —
        ``normalize``). Zwraca świeży wiersz do prezentacji (złoto ``metadata_e6--35``/``--36``).
        """
        await self._dataset(principal, dataset_id, Action.UPDATE)
        async with transaction(self._sessionmaker()) as session:
            row = await documents_repo.get(session, document_id)
            if row is None or row.dataset_id != dataset_id:
                return None
            merged = deepcopy(row.parser_config)
            merged[METADATA_KEY] = metadata
            now_ms = self._container.clock.now_ms()
            await documents_query.update_meta(
                session, document_id, {"parser_config": merged}, now_ms=now_ms
            )
            return await documents_repo.get(session, document_id)

    async def summary(
        self, principal: Principal, dataset_id: str, doc_ids: Sequence[str] | None
    ) -> dict[str, MetadataSummaryField]:
        """GET ``metadata/summary``: agregacja wartości ``meta_fields`` dokumentów (--15/--17)."""
        await self._dataset(principal, dataset_id)
        async with transaction(self._sessionmaker()) as session:
            metas = await documents_query.meta_fields_by_document(session, dataset_id, doc_ids)
        return _summarize(metas)

    async def flattened(
        self, principal: Principal, dataset_ids: Sequence[str]
    ) -> dict[str, dict[str, list[str]]]:
        """GET ``metadata/flattened``: {pole: {wartość: [document_id]}} po datasetach (--18)."""
        for dataset_id in dataset_ids:
            await self._dataset(principal, dataset_id)
        flattened: dict[str, dict[str, list[str]]] = {}
        async with transaction(self._sessionmaker()) as session:
            for dataset_id in dataset_ids:
                metas = await documents_query.meta_fields_by_document(session, dataset_id)
                _merge_flattened(flattened, metas)
        return flattened

    async def update(  # noqa: PLR0913 — kształt żądania upstream (selector + updates + deletes)
        self,
        principal: Principal,
        dataset_id: str,
        *,
        document_ids: Sequence[str],
        condition: MetadataCondition | None,
        updates: Sequence[Mapping[str, Any]],
        deletes: Sequence[Mapping[str, Any]],
    ) -> MetadataUpdateResult:
        """POST ``metadata/update``: masowa zmiana metadanych wskazanych dokumentów (--16).

        Kolejność wg upstream ``metadata_batch_update`` (document_api.py:359-460):
        dokumenty spoza datasetu → 102; ``metadata_condition`` zawęża zbiór do dokumentów
        spełniających warunek; zapisywane są tylko dokumenty, których metadane faktycznie
        się zmieniły (``updated``), a ``matched_docs`` to liczność zbioru docelowego.
        """
        await self._dataset(principal, dataset_id, Action.UPDATE)
        async with transaction(self._sessionmaker()) as session:
            if document_ids:
                present = await documents_query.ids_in_dataset(session, dataset_id, document_ids)
                outside = sorted(set(document_ids) - present)
                if outside:
                    raise Conflict(
                        MSG_FOREIGN_DOCS.format(dataset_id=dataset_id, ids=", ".join(outside))
                    )
            target = set(document_ids)
            if condition is not None:
                metas = await documents_query.meta_fields_by_document(session, dataset_id)
                target &= set(match_documents(metas, condition))
            target_ids = sorted(target)
            meta_map = await documents_query.meta_fields_by_document(
                session, dataset_id, target_ids
            )
            now_ms = self._container.clock.now_ms()
            updated = 0
            for document_id in target_ids:
                meta = _normalize_meta(meta_map.get(document_id, {}))
                original = deepcopy(meta)
                changed = _apply_updates(meta, updates)
                changed = _apply_deletes(meta, deletes) or changed
                if changed and meta != original:
                    await documents_query.update_meta(
                        session, document_id, {"meta_fields": meta}, now_ms=now_ms
                    )
                    updated += 1
        return MetadataUpdateResult(matched_docs=len(target_ids), updated=updated)
