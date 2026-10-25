"""Usługa logów ingestii i sprawdzenia embeddingu (zadanie DS2).

Trzy trasy odczytu stanu ingestii (``ingestions/summary``, ``ingestions``, ``ingestions/{id}``)
i ``embedding/check``. Uprawnienia wyłącznie przez ``app.domain.policy`` (przez
``DatasetService.load``). Źródłem logów jest istniejący stan ingestu WD: zadanie
``parse_document`` (``tasks``) + wiersz ``documents`` — WD nie ma tabeli
``pipeline_operation_log`` (patrz ``repositories/ingestion_logs.py``).

``embedding/check`` powtarza przepis embeddingu ingestu (DEC-033 p. 4): tytuł = ``stem`` nazwy
dokumentu, tekst = pytania albo treść (``embed.recipe_text``), mieszanie wagą
``parser_config.filename_embd_weight`` (``embed.filename_weight``), porównanie cosinusem
z wektorem zapisanym w ``chunk_vec_d<dim>``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import Conflict, NotFound
from app.db.repositories import documents_query, embedding_check, ingestion_logs
from app.db.repositories.datasets import DatasetRecord
from app.db.repositories.embedding_check import ChunkSample
from app.db.repositories.ingestion_logs import LogRow
from app.db.uow import transaction
from app.domain.policy import Action, Principal
from app.llm.gateway import LLMGateway
from app.llm.registry import ModelRegistry
from app.services.datasets import MSG_DATASET_LACKS, DatasetService
from app.services.embed import (
    combine,
    cosine_similarity,
    embed_texts,
    filename_weight,
    recipe_text,
)

if TYPE_CHECKING:
    from app.core.container import Container

__all__ = [
    "LOG_TYPES",
    "MSG_EMBD_REQUIRED",
    "MSG_INVALID_LOG_TYPE",
    "MSG_LOG_NOT_FOUND",
    "MSG_NOT_EFFECTIVE",
    "MSG_NO_CHUNKS",
    "DatasetIngestionsService",
    "EmbeddingCheck",
    "EmbeddingCheckChunk",
    "IngestionLog",
    "IngestionSummary",
    "IngestionsQuery",
]

# Upstream dataset_api_service.list_ingestion_logs: dozwolone rodzaje logów i komunikat błędu.
LOG_TYPES = ("dataset", "file")
DEFAULT_LOG_TYPE = "dataset"
MSG_INVALID_LOG_TYPE = 'Invalid "log_type", expected "dataset" or "file"'
MSG_LOG_NOT_FOUND = "Log not found"  # upstream get_ingestion_log
MSG_EMBD_REQUIRED = "`embd_id` is required."  # upstream check_embedding (:1375)
MSG_NO_CHUNKS = "No embedded chunks are available to compare."  # upstream check_embedding
MSG_NOT_EFFECTIVE = (  # upstream check_embedding
    "Embedding model switch failed: the average similarity between old and new vectors "
    "is below 0.9, indicating incompatible vector spaces."
)
MSG_EMBEDDING_FAILURE = (
    "Embedding failure. The dimension ({actual}) of given embedding model "
    "is different from the original ({stored})"
)

# Próg uznania modelu za zgodny (upstream: avg_cos_sim >= 0.9).
EFFECTIVE_MIN_COS_SIM = 0.9
# Kolumna ``status`` wiersza logu upstream ma wartość domyślną '1' (złoto --08/--09).
LOG_STATUS = "1"
# Etykieta zadania parsowania (upstream PipelineTaskType.PARSE) — złoto ``task_type``.
PARSE_TASK_LABEL = "Parse"
# Zlecenia pipeline'ów (graf/raptor) WD nie ma → ``pipeline_id`` zawsze puste, a tytuł to
# ``parser_id`` dokumentu (upstream: gałąź ``pipeline_id`` fałszywa).
PIPELINE_ID = ""

# Kubełki statusu w podsumowaniu (upstream get_parsing_status_by_kb_ids); kod '5' (SCHEDULE)
# nie ma kubełka i nie jest liczony.
RUN_STATUS_KEYS = (
    "unstart_count",
    "running_count",
    "cancel_count",
    "done_count",
    "fail_count",
)
RUN_TO_STATUS = {
    "0": "unstart_count",
    "1": "running_count",
    "2": "cancel_count",
    "3": "done_count",
    "4": "fail_count",
}

# Powody pominięcia chunka w wyniku (upstream: brak tekstu / brak zapisanego wektora).
REASON_NO_TEXT = "no_text"
REASON_NO_VECTOR = "no_stored_vector"


@dataclass(frozen=True)
class IngestionsQuery:
    """Parametry GET …/ingestions po przepisaniu przez normalize (upstream list_ingestion_logs)."""

    page: int
    page_size: int
    orderby: str
    desc: bool
    log_type: str
    operation_status: tuple[str, ...] = ()
    keywords: str | None = None
    create_date_from: str | None = None
    create_date_to: str | None = None


@dataclass(frozen=True)
class IngestionSummary:
    """Podsumowanie ingestii datasetu (złoto --07): liczby z wiersza KB + statusy dokumentów."""

    doc_num: int
    chunk_num: int
    token_num: int
    status: dict[str, int]


@dataclass(frozen=True)
class IngestionLog:
    """Log ingestii pliku (złoto --08/--09) — pola wg upstream PipelineOperationLog.create."""

    id: str
    tenant_id: str
    kb_id: str
    document_id: str
    document_name: str
    document_suffix: str
    document_type: str
    source_from: str
    parser_id: str
    pipeline_id: str
    pipeline_title: str
    task_type: str
    operation_status: str
    progress: float
    progress_msg: str
    avatar: str | None
    status: str
    process_begin_at: int | None
    process_duration: float
    create_time: int
    update_time: int


@dataclass(frozen=True)
class EmbeddingCheckChunk:
    """Wynik dla jednego chunka: cosinus i wektor albo ``reason`` (upstream check_embedding)."""

    chunk_id: str
    doc_id: str | None = None
    doc_name: str | None = None
    vector_field: str | None = None
    vector_dim: int | None = None
    cos_sim: float | None = None
    reason: str | None = None


@dataclass(frozen=True)
class EmbeddingCheck:
    """Podsumowanie sprawdzenia embeddingu + wynik oceny zgodności (próg 0.9)."""

    kb_id: str
    model: str
    sampled: int
    valid: int
    avg_cos_sim: float
    min_cos_sim: float
    max_cos_sim: float
    match_mode: str
    effective: bool
    results: list[EmbeddingCheckChunk] = field(default_factory=list)


class DatasetIngestionsService:
    """Logi ingestii i sprawdzenie embeddingu datasetu — jedyne miejsce ich kontroli dostępu."""

    def __init__(self, container: Container) -> None:
        self._container = container

    def _sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        """Fabryka sesji z kontenera (C0 p. 2)."""
        return cast(async_sessionmaker[AsyncSession], self._container.sessionmaker)

    async def _dataset(self, principal: Principal, dataset_id: str) -> DatasetRecord:
        """Dataset po id z kontrolą READ (komunikat braku jak w trasach datasetów)."""
        return await DatasetService(self._container).load(
            principal, dataset_id, Action.READ, missing=MSG_DATASET_LACKS
        )

    def _log(self, row: LogRow, record: DatasetRecord) -> IngestionLog:
        """Wiersz repo → log API; mapowanie pól wg upstream ``PipelineOperationLog.create``."""
        return IngestionLog(
            id=row.id,
            tenant_id=record.tenant_id,
            kb_id=row.dataset_id,
            document_id=row.document_id,
            document_name=row.document_name,
            document_suffix=row.document_suffix,
            document_type=row.document_type,
            source_from=row.source_type.split("/")[0],
            parser_id=row.chunk_method,
            pipeline_id=PIPELINE_ID,
            pipeline_title=row.chunk_method,
            task_type=PARSE_TASK_LABEL,
            operation_status=row.run,
            progress=row.progress,
            progress_msg=row.progress_msg,
            avatar=row.thumbnail,
            status=LOG_STATUS,
            process_begin_at=row.process_begin_at,
            process_duration=row.process_duration,
            create_time=row.create_time,
            update_time=row.update_time,
        )

    async def summary(self, principal: Principal, dataset_id: str) -> IngestionSummary:
        """Podsumowanie ingestii: liczby dokumentów/chunków/tokenów + statusy po ``run`` (--07)."""
        record = await self._dataset(principal, dataset_id)
        async with transaction(self._sessionmaker()) as session:
            counts = await documents_query.run_counts(session, dataset_id)
        status = {key: 0 for key in RUN_STATUS_KEYS}
        for run, bucket in RUN_TO_STATUS.items():
            status[bucket] = counts.get(run, 0)
        return IngestionSummary(
            doc_num=record.document_count,
            chunk_num=record.chunk_count,
            token_num=record.token_num,
            status=status,
        )

    async def list_logs(
        self, principal: Principal, dataset_id: str, query: IngestionsQuery
    ) -> tuple[list[IngestionLog], int]:
        """Strona logów plików datasetu; ``log_type=dataset`` → pusta lista (upstream: fake doc)."""
        record = await self._dataset(principal, dataset_id)
        if query.log_type != "file":
            return [], 0
        async with transaction(self._sessionmaker()) as session:
            rows, total = await ingestion_logs.list_logs(
                session,
                dataset_id=dataset_id,
                offset=(query.page - 1) * query.page_size,
                limit=query.page_size,
                orderby=query.orderby,
                desc=query.desc,
                operation_status=query.operation_status,
                keywords=query.keywords,
                create_date_from=query.create_date_from,
                create_date_to=query.create_date_to,
            )
        return [self._log(row, record) for row in rows], total

    async def get_log(self, principal: Principal, dataset_id: str, log_id: str) -> IngestionLog:
        """Log pliku po id; brak (albo parse jeszcze trwa) → NotFound(MSG_LOG_NOT_FOUND)."""
        record = await self._dataset(principal, dataset_id)
        async with transaction(self._sessionmaker()) as session:
            row = await ingestion_logs.get_log(session, dataset_id=dataset_id, log_id=log_id)
        if row is None:
            raise NotFound(MSG_LOG_NOT_FOUND)
        return self._log(row, record)

    async def check_embedding(
        self, principal: Principal, dataset_id: str, *, embd_id: str, check_num: int
    ) -> EmbeddingCheck:
        """Re-embeddowanie próbki chunków żądanym modelem i cosinus z wektorem zapisanym (--10)."""
        record = await self._dataset(principal, dataset_id)
        if not embd_id:
            raise Conflict(MSG_EMBD_REQUIRED)
        ref = await cast(ModelRegistry, self._container.models).resolve(embd_id, "embedding")
        samples, vectors = await self._samples(dataset_id, check_num, record.embedding_dim)
        llm = cast(LLMGateway, self._container.llm)
        results: list[EmbeddingCheckChunk] = []
        sims: list[float] = []
        mode = "content_only"
        for sample in samples:
            text = recipe_text(sample.content, sample.questions)
            if not text:
                results.append(EmbeddingCheckChunk(chunk_id=sample.id, reason=REASON_NO_TEXT))
                continue
            stored = vectors[sample.id]
            if not stored:
                results.append(EmbeddingCheckChunk(chunk_id=sample.id, reason=REASON_NO_VECTOR))
                continue
            if ref.dimension is not None and ref.dimension != len(stored):
                raise Conflict(
                    MSG_EMBEDDING_FAILURE.format(actual=ref.dimension, stored=len(stored))
                )
            title_vec, content_vec = await embed_texts(
                llm,
                ref,
                [Path(sample.document_name).stem, text],
                batch_size=2,
                expected_dim=len(stored),
            )
            mixed = combine(title_vec, content_vec, filename_weight(sample.parser_config))
            sim = cosine_similarity(content_vec, stored)
            mode = "content_only"
            sim_mixed = cosine_similarity(mixed, stored)
            if sim_mixed > sim:
                sim = sim_mixed
                mode = "title+content"
            sims.append(sim)
            results.append(
                EmbeddingCheckChunk(
                    chunk_id=sample.id,
                    doc_id=sample.document_id,
                    doc_name=sample.document_name,
                    # Nazwa pola wektora w API v0.27.2 (doc-store upstream); WD trzyma wektor
                    # w kolumnie ``embedding`` tabeli chunk_vec_d<dim>, kształt zostaje zgodny.
                    vector_field=f"q_{len(stored)}_vec",
                    vector_dim=len(stored),
                    cos_sim=round(sim, 6),
                )
            )
        if not sims:
            raise Conflict(MSG_NO_CHUNKS)
        average = _round_mean(sims)
        return EmbeddingCheck(
            kb_id=dataset_id,
            model=embd_id,
            sampled=len(samples),
            valid=len(sims),
            avg_cos_sim=average,
            min_cos_sim=round(min(sims), 6),
            max_cos_sim=round(max(sims), 6),
            match_mode=mode,
            effective=average >= EFFECTIVE_MIN_COS_SIM,
            results=results,
        )

    async def _samples(
        self, dataset_id: str, check_num: int, dim: int
    ) -> tuple[list[ChunkSample], dict[str, list[float] | None]]:
        """Próbka chunków i ich wektory zapisane (jedna transakcja odczytu)."""
        async with transaction(self._sessionmaker()) as session:
            samples = await embedding_check.sample_chunks(session, dataset_id, check_num)
            vectors = {
                sample.id: await embedding_check.fetch_vector(session, dim, sample.id)
                for sample in samples
            }
        return list(samples), vectors


def _round_mean(values: Sequence[float]) -> float:
    """Średnia cosinusów zaokrąglona do 6 miejsc (upstream ``round(np.mean(...), 6)``)."""
    return round(sum(values) / len(values), 6)
