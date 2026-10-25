"""Modele OpenAPI ingestii i sprawdzenia embeddingu (zadanie DS2) — kształty złota --07..--10."""

from typing import Any

from app.api.ragflow.normalize.dataset_ingestions import EmbeddingCheckCommand
from app.api.ragflow.schemas.common import RequestModel, ResponseModel


class IngestionStatus(ResponseModel):
    """``data.status`` podsumowania ingestii (--07): liczby dokumentów po stanie ``run``."""

    cancel_count: int
    done_count: int
    fail_count: int
    running_count: int
    unstart_count: int


class IngestionSummary(ResponseModel):
    """Kształt GET …/ingestions/summary (--07)."""

    chunk_num: int
    doc_num: int
    status: IngestionStatus
    token_num: int


class IngestionLog(ResponseModel):
    """Kształt logu pliku (--08/--09) — pola wg upstream ``PipelineOperationLog``."""

    avatar: str
    create_date: str
    create_time: int
    document_id: str
    document_name: str
    document_suffix: str
    document_type: str
    dsl: dict[str, Any]
    id: str
    kb_id: str
    operation_status: str
    parser_id: str
    pipeline_id: str
    pipeline_title: str
    process_begin_at: str
    process_duration: float
    progress: float
    progress_msg: str
    source_from: str
    status: str
    task_type: str
    tenant_id: str
    update_date: str
    update_time: int


class IngestionsList(ResponseModel):
    """Kształt GET …/ingestions (--08): strona logów + ``total``."""

    logs: list[IngestionLog]
    total: int


class EmbeddingCheckChunk(ResponseModel):
    """Wynik per chunk (--10); przy pominięciu wypełnione tylko ``chunk_id`` i ``reason``."""

    chunk_id: str
    cos_sim: float | None = None
    doc_id: str | None = None
    doc_name: str | None = None
    vector_dim: int | None = None
    vector_field: str | None = None
    reason: str | None = None


class EmbeddingCheckSummary(ResponseModel):
    """``data.summary`` (--10): ocena zgodności modelu z zapisanymi wektorami."""

    avg_cos_sim: float
    kb_id: str
    match_mode: str
    max_cos_sim: float
    min_cos_sim: float
    model: str
    sampled: int
    valid: int


class EmbeddingCheckData(ResponseModel):
    """Kształt POST …/embedding/check (--10)."""

    results: list[EmbeddingCheckChunk]
    summary: EmbeddingCheckSummary


class EmbeddingCheckRequest(RequestModel, EmbeddingCheckCommand):
    """Ciało POST …/embedding/check (normalize.dataset_ingestions.EmbeddingCheckCommand)."""


REQUEST_MODELS: tuple[type[RequestModel], ...] = (EmbeddingCheckRequest,)
