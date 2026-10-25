"""Usługa datasetów dla /api/v1/datasets (kontrakt E1-9a C1.2).

Uprawnienia wyłącznie przez ``app.domain.policy``; DTO dla prezentertów re-eksportowane
z repozytorium (``DatasetRecord``), bo ``app.api`` nie może importować ``app.db``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.db.repositories import datasets as datasets_repo
from app.db.repositories.datasets import DatasetRecord
from app.db.uow import transaction
from app.domain.policy import (
    Action,
    Principal,
    ResourceRef,
    can,
    require,
    visibility_filter,
)
from app.llm.gateway import LLMGateway
from app.llm.registry import ModelRegistry
from app.llm.types import ModelRef
from app.services.datasets_layout import validate_layout_recognize
from app.services.default_models import DefaultModelsService
from app.storage.keys import dataset_prefix, validate_key

if TYPE_CHECKING:
    from app.core.container import Container

__all__ = [
    "DEFAULT_PARSER_CONFIG",
    "MSG_CHUNK_METHOD_UNSUPPORTED",
    "MSG_DATASETS_LACK",
    "MSG_DATASET_LACKS",
    "MSG_DATASET_NOT_OWNED",
    "MSG_EMBEDDING_LOCKED",
    "MSG_NAME_EXISTS",
    "MSG_NO_PROPERTIES",
    "UNSUPPORTED_CHUNK_METHODS",
    "DatasetListQuery",
    "DatasetRecord",
    "DatasetService",
    "deep_merge",
    "unique_name",
]

# = złoto G/datasets/datasets_crud--01.json (poza llm_id, który wpisuje create).
DEFAULT_PARSER_CONFIG: dict[str, Any] = {
    "auto_keywords": 0,
    "auto_questions": 0,
    "children_delimiter": "",
    "chunk_token_num": 512,
    "delimiter": "\n",
    "html4excel": False,
    "image_context_size": 0,
    "layout_recognize": "DeepDOC",
    "llm_id": "",
    "parent_child": {"children_delimiter": "\n", "use_parent_child": False},
    "table_context_size": 0,
    "topn_tags": 3,
}

UNSUPPORTED_CHUNK_METHODS = frozenset({"tag", "knowledge_graph", "resume", "audio"})

MSG_DATASET_NOT_OWNED = "You don't own the dataset {dataset_id}."  # DOC:831, CHK:552
MSG_DATASET_LACKS = "User '{user_id}' lacks permission for dataset '{dataset_id}'"  # DAS:266…
MSG_DATASETS_LACK = "User '{user_id}' lacks permission for datasets: '{ids}'"  # DAS:172
MSG_NO_PROPERTIES = "no properties were modified"  # DAS:315
MSG_NAME_EXISTS = "Dataset name '{name}' already exists"  # DAS:376
MSG_EMBEDDING_LOCKED = (  # v0.24.0:api/apps/sdk/dataset.py:364 (brief rozstrzygnięcie 3)
    "When chunk_num ({chunk_count}) > 0, embedding_model must remain {embedding_model}"
)
MSG_CHUNK_METHOD_UNSUPPORTED = "`chunk_method` {chunk_method} is not supported by Wawelsky Dragon"

# Tekst sondy wymiaru embeddingu (kontrakt T2) — krótki, deterministyczny, bez danych użytkownika.
EMBEDDING_PROBE_TEXT = "dimension probe"


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Nowy dict: dict-w-dict scalane rekurencyjnie, pozostałe wartości nadpisywane."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def unique_name(name: str, taken: set[str]) -> str:
    """Wolna nazwa bez zmian; zajęta → stem(1).ext, stem(2).ext… (``taken`` małymi literami)."""
    if name.lower() not in taken:
        return name
    stem, ext = os.path.splitext(name)
    counter = 1
    while True:
        candidate = f"{stem}({counter}){ext}"
        if candidate.lower() not in taken:
            return candidate
        counter += 1


@dataclass(frozen=True)
class DatasetListQuery:
    """Parametry GET /datasets po przepisaniu przez normalize (kontrakt C1.2)."""

    page: int
    page_size: int
    orderby: str
    desc: bool
    dataset_id: str | None = None
    name: str | None = None
    keywords: str | None = None


def _ref(record: DatasetRecord) -> ResourceRef:
    """ResourceRef datasetu dla polityki (kontrakt C0 p. 3)."""
    return ResourceRef(
        kind="dataset", owner_id=record.tenant_id, permission=record.permission, id=record.id
    )


class DatasetService:
    """CRUD datasetów + ``load`` — jedyne miejsce sprawdzania dostępu do datasetu."""

    def __init__(self, container: Container) -> None:
        self._container = container

    async def _ensure_dimension(self, ref: ModelRef) -> ModelRef:
        """Zwraca referencję z wymiarem: zapisanym albo zmierzonym sondą (kontrakt T2, usterka #2).

        Model bez zapisanego wymiaru (``dimension is None``, np. dodany ręcznie) dostaje jedno
        wywołanie ``LLMGateway.embed`` na tekście ``EMBEDDING_PROBE_TEXT``; zmierzona długość
        wektora trafia do ``models.dimension`` i do zwróconej referencji. Dzięki temu ``create``
        i ``update`` nie kończą się błędem "has no dimension" dla modelu dodanego bez wymiaru.

        Błąd bramki (LLM*/httpx/timeout/4xx) → ``ValidationFailed`` z powodem równym nazwie klasy
        wyjątku — bez URL z kluczem, bez sekretów i bez treści odpowiedzi.
        """
        if ref.dimension is not None:
            return ref
        llm = cast(LLMGateway, self._container.llm)
        try:
            vector = (await llm.embed(ref, [EMBEDDING_PROBE_TEXT]))[0]
        except Exception as exc:  # kontrakt T2: dowolny błąd bramki → unavailable
            raise ValidationFailed(
                f"embedding model {ref.name} unavailable: {type(exc).__name__}"
            ) from exc
        dimension = len(vector)
        if ref.id is not None:  # model spoza rejestru (id None) nie ma wiersza do zapisania
            await cast(ModelRegistry, self._container.models).set_dimension(ref.id, dimension)
        return replace(ref, dimension=dimension)

    async def create(  # noqa: PLR0913 — kształt kontraktu C1.2
        self,
        principal: Principal,
        *,
        name: str,
        description: str | None = None,
        avatar: str | None = None,
        language: str = "English",
        embedding_model: str | None = None,
        permission: str = "me",
        chunk_method: str = "naive",
        parser_config: Mapping[str, Any] | None = None,
    ) -> DatasetRecord:
        """Tworzy dataset: dedup nazwy, domyślne modele, pełny parser_config (kontrakt C1.2)."""
        if chunk_method in UNSUPPORTED_CHUNK_METHODS:
            raise ValidationFailed(MSG_CHUNK_METHOD_UNSUPPORTED.format(chunk_method=chunk_method))
        ref = await self._ensure_dimension(
            await cast(ModelRegistry, self._container.models).resolve(embedding_model, "embedding")
        )
        llm_id = (await DefaultModelsService(self._container).get())["llm_id"]
        config = deep_merge({**DEFAULT_PARSER_CONFIG, "llm_id": llm_id}, parser_config or {})
        await validate_layout_recognize(self._container.models, parser_config)
        clean = name.strip()
        dataset_id = self._container.id_gen.new_id()
        async with transaction(self._sessionmaker()) as session:
            final_name = unique_name(
                clean, await datasets_repo.names_taken(session, principal.user_id)
            )
            await datasets_repo.insert(
                session,
                id=dataset_id,
                tenant_id=principal.user_id,
                created_by=principal.user_id,
                name=final_name,
                description=description,
                avatar=avatar,
                language=language,
                embedding_model=ref.name,
                # `_ensure_dimension` gwarantuje wymiar — nie może tu być None.
                embedding_dim=cast(int, ref.dimension),
                permission=permission,
                chunk_method=chunk_method,
                parser_config=config,
                now_ms=self._container.clock.now_ms(),
            )
            record = await datasets_repo.get_record(session, dataset_id)
        if record is None:  # wiersz wstawiony wyżej w tej samej transakcji
            raise AssertionError("dataset row missing after insert")
        return record

    async def get(self, principal: Principal, dataset_id: str) -> DatasetRecord:
        """Dataset po id z kontrolą READ (kontrakt C1.2)."""
        return await self.load(principal, dataset_id, Action.READ, missing=MSG_DATASET_LACKS)

    async def get_detail(self, principal: Principal, dataset_id: str) -> tuple[DatasetRecord, int]:
        """Dataset po id z kontrolą READ + ``size`` = suma rozmiarów dokumentów (DAS:276).

        Upstream ``get_dataset`` dokłada do wiersza KB ``size`` z
        ``DocumentService.get_total_size_by_kb_id`` — semantyka: suma ``documents.size``.
        """
        record = await self.load(principal, dataset_id, Action.READ, missing=MSG_DATASET_LACKS)
        async with transaction(self._sessionmaker()) as session:
            size = await datasets_repo.document_total_size(session, dataset_id)
        return record, size

    async def update(
        self, principal: Principal, dataset_id: str, fields: Mapping[str, Any]
    ) -> DatasetRecord:
        """Aktualizacja: pusty payload → Conflict; reguły nazwy, embeddingu, configu (C1.2)."""
        if not fields:
            raise Conflict(MSG_NO_PROPERTIES)
        record = await self.load(principal, dataset_id, Action.UPDATE, missing=MSG_DATASET_LACKS)
        to_save: dict[str, Any] = {
            key: value
            for key, value in fields.items()
            if key not in ("name", "embedding_model", "parser_config", "chunk_method")
        }
        if "chunk_method" in fields:
            chunk_method = fields["chunk_method"]
            if chunk_method in UNSUPPORTED_CHUNK_METHODS:
                raise ValidationFailed(
                    MSG_CHUNK_METHOD_UNSUPPORTED.format(chunk_method=chunk_method)
                )
            to_save["chunk_method"] = chunk_method
        async with transaction(self._sessionmaker()) as session:
            if "name" in fields:
                clean = fields["name"].strip()
                taken = await datasets_repo.names_taken(session, record.tenant_id)
                taken.discard(record.name.lower())
                if clean.lower() in taken:
                    raise Conflict(MSG_NAME_EXISTS.format(name=clean))
                to_save["name"] = clean
            if "embedding_model" in fields:
                ref = await cast(ModelRegistry, self._container.models).resolve(
                    fields["embedding_model"], "embedding"
                )
                if ref.name != record.embedding_model and record.chunk_count > 0:
                    raise ValidationFailed(
                        MSG_EMBEDDING_LOCKED.format(
                            chunk_count=record.chunk_count, embedding_model=record.embedding_model
                        )
                    )
                ref = await self._ensure_dimension(ref)
                to_save["embedding_model"] = ref.name
                to_save["embedding_dim"] = ref.dimension
            if "parser_config" in fields:
                incoming = fields["parser_config"]
                # Jawne ``null``/``{}`` zeruje konfigurację do domyślnej (upstream
                # ``get_parser_config(chunk_method, None)``); częściowy dict scala się z zapisanym.
                to_save["parser_config"] = (
                    deep_merge(record.parser_config, incoming)
                    if incoming is not None
                    else deep_merge(
                        DEFAULT_PARSER_CONFIG, {"llm_id": record.parser_config.get("llm_id", "")}
                    )
                )
                await validate_layout_recognize(self._container.models, incoming)
            await datasets_repo.update_fields(
                session, dataset_id, to_save, now_ms=self._container.clock.now_ms()
            )
            fresh = await datasets_repo.get_record(session, dataset_id)
        if fresh is None:  # rekord istniał chwilę wcześniej w tej samej transakcji
            raise AssertionError("dataset row missing after update")
        return fresh

    async def delete(
        self, principal: Principal, ids: Sequence[str] | None, delete_all: bool
    ) -> int:
        """Usuwa datasety (najpierw wszystkie sprawdzenia); zwraca liczbę usuniętych (C1.2)."""
        if not ids and not delete_all:
            return 0
        targets = await self._resolve_targets(principal, ids, delete_all)
        for record in targets:
            await self.purge(record)
        return len(targets)

    async def load(
        self,
        principal: Principal,
        dataset_id: str,
        action: Action,
        *,
        missing: str = MSG_DATASET_NOT_OWNED,
    ) -> DatasetRecord:
        """Rekord datasetu + require(action); brak → NotFound(missing). Dla dokumentów/chunków."""
        async with transaction(self._sessionmaker()) as session:
            record = await datasets_repo.get_record(session, dataset_id)
        if record is None:
            raise NotFound(missing.format(dataset_id=dataset_id, user_id=principal.user_id))
        require(principal, action, _ref(record))
        return record

    def _sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        """Fabryka sesji z kontenera (C0 p. 2)."""
        return cast(async_sessionmaker[AsyncSession], self._container.sessionmaker)

    async def _resolve_targets(
        self, principal: Principal, ids: Sequence[str] | None, delete_all: bool
    ) -> list[DatasetRecord]:
        """Zbiór datasetów do usunięcia; wszystkie sprawdzenia PRZED jakimkolwiek usunięciem."""
        sessionmaker = self._sessionmaker()
        if ids:
            unique_ids = list(dict.fromkeys(ids))
            found: list[DatasetRecord] = []
            missing: list[str] = []
            async with transaction(sessionmaker) as session:
                for dataset_id in unique_ids:
                    record = await datasets_repo.get_record(session, dataset_id)
                    if record is None:
                        missing.append(dataset_id)
                    else:
                        found.append(record)
            if missing:
                raise PermissionDenied(
                    MSG_DATASETS_LACK.format(user_id=principal.user_id, ids=", ".join(missing))
                )
            for record in found:
                require(principal, Action.DELETE, _ref(record))
            return found
        async with transaction(sessionmaker) as session:
            records, _total = await datasets_repo.list_records(
                session,
                visibility=visibility_filter(principal, "dataset"),
                offset=0,
                limit=10**9,
                orderby="create_time",
                desc=True,
            )
        return [record for record in records if can(principal, Action.DELETE, _ref(record))]

    async def purge(self, record: DatasetRecord) -> None:
        """Usuwa dokumenty (ingestia), dataset i katalogi storage (C1.2); woła też import (T2)."""
        async with transaction(self._sessionmaker()) as session:
            doc_ids = await datasets_repo.list_document_ids(session, record.id)
        if doc_ids:
            await self._container.ingest.delete_documents(doc_ids)
        async with transaction(self._sessionmaker()) as session:
            await datasets_repo.delete(session, record.id)
        await self._container.storage.delete_prefix(dataset_prefix(record.id))
        await self._container.storage.delete_prefix(validate_key(f"images/{record.id}"))

    # Metoda ``list`` na końcu klasy: dalsza definicja przesłoniłaby wbudowany ``list``
    # w adnotacjach metod zdefiniowanych poniżej (mypy strict).
    async def list(
        self, principal: Principal, q: DatasetListQuery
    ) -> tuple[list[DatasetRecord], int]:
        """Strona listy datasetów widocznych dla principal + total (kontrakt C1.2).

        Istnienie każdego filtra sprawdzamy OSOBNO, przed listowaniem (upstream DAS:449-457:
        ``get_kb_by_id``, potem ``get_kb_by_name``, każdy brak → 102). Puste przecięcie filtrów
        (np. ``id`` istniejącego datasetu i ``name`` innego) to ``code 0`` z pustą listą —
        wcześniej WD zwracał tu 102, bo brał ``total == 0`` za brak dostępu.
        """
        async with transaction(self._sessionmaker()) as session:
            visibility = visibility_filter(principal, "dataset")
            if q.dataset_id is not None and not await datasets_repo.exists(
                session, visibility=visibility, dataset_id=q.dataset_id
            ):
                raise NotFound(
                    MSG_DATASET_LACKS.format(user_id=principal.user_id, dataset_id=q.dataset_id)
                )
            if q.name is not None and not await datasets_repo.exists(
                session, visibility=visibility, name=q.name
            ):
                raise NotFound(
                    MSG_DATASET_LACKS.format(user_id=principal.user_id, dataset_id=q.name)
                )
            records, total = await datasets_repo.list_records(
                session,
                visibility=visibility,
                offset=(q.page - 1) * q.page_size,
                limit=q.page_size,
                orderby=q.orderby,
                desc=q.desc,
                dataset_id=q.dataset_id,
                name=q.name,
                keywords=q.keywords,
            )
        return records, total
