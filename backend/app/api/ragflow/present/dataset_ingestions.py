"""Prezentery ingestii i sprawdzenia embeddingu (zadanie DS2): kształty v0.27.2 (--07..--10)."""

from typing import Any

from app.api.ragflow.compat import CompatProfile
from app.api.ragflow.present.common import date, ts
from app.services.dataset_ingestions import (
    EmbeddingCheck,
    EmbeddingCheckChunk,
    IngestionLog,
    IngestionSummary,
)


def ingestion_summary(summary: IngestionSummary, profile: CompatProfile) -> dict[str, Any]:
    """--07: ``doc_num``/``chunk_num``/``token_num`` z wiersza KB + statusy po ``run``.

    Klucze statusu posortowane (upstream serializuje JSON alfabetycznie); kompletu kubełków
    pilnuje normalize/service (upstream ``get_parsing_status_by_kb_ids``).
    """
    return {
        "chunk_num": summary.chunk_num,
        "doc_num": summary.doc_num,
        "status": {key: summary.status[key] for key in sorted(summary.status)},
        "token_num": summary.token_num,
    }


def ingestion_log(log: IngestionLog, profile: CompatProfile) -> dict[str, Any]:
    """--08/--09: log pliku (pola wg upstream ``PipelineOperationLogService.create``).

    ``dsl``: WD nie ma DSL-a pipeline'u — upstream dla parsowania metodą ``naive`` zapisuje
    ``{}`` (``create(..., dsl="{}")``), więc kształt jest zgodny.
    """
    return {
        "avatar": log.avatar or "",
        "create_date": date(log.create_time),
        "create_time": ts(log.create_time),
        "document_id": log.document_id,
        "document_name": log.document_name,
        "document_suffix": log.document_suffix,
        "document_type": log.document_type,
        "dsl": {},
        "id": log.id,
        "kb_id": log.kb_id,
        "operation_status": log.operation_status,
        "parser_id": log.parser_id,
        "pipeline_id": log.pipeline_id,
        "pipeline_title": log.pipeline_title,
        "process_begin_at": _optional_date(log.process_begin_at),
        "process_duration": log.process_duration,
        "progress": log.progress,
        "progress_msg": log.progress_msg,
        "source_from": log.source_from,
        "status": log.status,
        "task_type": log.task_type,
        "tenant_id": log.tenant_id,
        "update_date": date(log.update_time),
        "update_time": ts(log.update_time),
    }


def ingestion_logs_list(
    logs: list[IngestionLog], total: int, profile: CompatProfile
) -> dict[str, Any]:
    """--08: ``{"logs": [...], "total": n}`` (upstream ``{"total": ..., "logs": ...}``)."""
    return {"logs": [ingestion_log(log, profile) for log in logs], "total": total}


def embedding_check(check: EmbeddingCheck, profile: CompatProfile) -> dict[str, Any]:
    """--10: ``results`` (per chunk) + ``summary`` (upstream ``check_embedding``)."""
    return {
        "results": [_check_chunk(result) for result in check.results],
        "summary": {
            "avg_cos_sim": check.avg_cos_sim,
            "kb_id": check.kb_id,
            "match_mode": check.match_mode,
            "max_cos_sim": check.max_cos_sim,
            "min_cos_sim": check.min_cos_sim,
            "model": check.model,
            "sampled": check.sampled,
            "valid": check.valid,
        },
    }


def _check_chunk(result: EmbeddingCheckChunk) -> dict[str, Any]:
    """Wynik per chunk: ``reason`` zamiast cosinusa, gdy chunka nie dało się porównać."""
    if result.reason is not None:
        return {"chunk_id": result.chunk_id, "reason": result.reason}
    return {
        "chunk_id": result.chunk_id,
        "cos_sim": result.cos_sim,
        "doc_id": result.doc_id,
        "doc_name": result.doc_name,
        "vector_dim": result.vector_dim,
        "vector_field": result.vector_field,
    }


def _optional_date(ms: int | None) -> str:
    """Data z milisekund albo "" (``process_begin_at`` przed pierwszym parsowaniem jest NULL)."""
    return "" if ms is None else date(ms)
