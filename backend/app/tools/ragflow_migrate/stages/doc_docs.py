"""Faza ``documents`` etapu ``documents``: ``document`` → ``documents`` (kontrakt §5, WP E4-6b1).

Wiersze źródłowe ``document`` dostaje faza gotowe (jedno czytanie źródła w ``documents.py``).
Wiersz docelowy piszemy **zawsze**, gdy dataset dokumentu istnieje w celu — także przy braku
bloba (znacznik ``content_hash=''`` i ``error`` z prefiksem ``migration:``, DEC-133).
Bloby wpisów współdzielonych z plikiem kopiujemy raz: ``copy_blob`` z cache po ``dest``
i licznikiem ``ctx.shared['_blob_counted']`` (jeden wpis planu liczy się raz).
"""

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.tools.ragflow_migrate.blobs import BlobEntry, BlobPlan, CopyOutcome, SourceFiles, copy_blob
from app.tools.ragflow_migrate.stages.base import Issue, PhaseResult, RunContext
from app.tools.ragflow_migrate.stages.common import dumps_json, ms_naive, pick_times, same_json
from app.tools.ragflow_migrate.stages.datasets import (
    map_chunk_method,
    raw_parser_config,
    split_parser_config,
)

#: Kolumny celu pisane przez fazę (kolejność = lista INSERT), wg DDL ``documents``.
COLUMNS: tuple[str, ...] = (
    "id",
    "dataset_id",
    "created_by",
    "name",
    "suffix",
    "type",
    "size",
    "location",
    "content_hash",
    "source_type",
    "source_ref",
    "chunk_method",
    "parser_config",
    "run",
    "progress",
    "progress_msg",
    "error",
    "process_begin_at",
    "process_duration",
    "chunk_count",
    "token_count",
    "enabled",
    "meta_fields",
    "thumbnail",
    "create_time",
    "create_date",
    "update_time",
    "update_date",
)

#: Kolumny JSON porównywane przez ``same_json`` w idempotencji (kontrakt §5, brief pkt 2).
JSON_COLUMNS: tuple[str, ...] = ("parser_config", "meta_fields")

#: Kody uwag fazy (kontrakt §5).
DOC_DATASET_MISSING = "document_dataset_missing"
CHUNK_METHOD_FALLBACK = "chunk_method_fallback"
BLOB_MISSING = "blob_missing"
BLOB_SIZE_MISMATCH = "blob_size_mismatch"

#: ``source_type`` dokumentu wskazanego w mapowaniu SharePoint (CONTRACT §7, WP E4-6c).
SOURCE_TYPE_SHAREPOINT = "sharepoint"

_COLUMN_LIST = ", ".join(COLUMNS)
_VALUES = ", ".join(":" + column for column in COLUMNS)
# Nazwy kolumn pochodzą ze stałej ``COLUMNS`` (nie z danych), więc interpolacja jest bezpieczna.
_INSERT = f"INSERT INTO documents ({_COLUMN_LIST}) VALUES ({_VALUES})"  # noqa: S608
_UPDATE = f"UPDATE documents SET {', '.join(f'{c} = :{c}' for c in COLUMNS)} WHERE id = :id"  # noqa: S608
_SELECT_EXISTING = f"SELECT {_COLUMN_LIST} FROM documents WHERE id IN :ids"  # noqa: S608
_SELECT_IDS = "SELECT id FROM documents WHERE id IN :ids"


def _text(value: Any) -> str:
    """Wartość kolumny jako tekst; ``None`` → ``''``."""
    return "" if value is None else str(value)


def _enabled(status: Any) -> int:
    """``enabled`` celu z ``document.status`` źródła: ``'1'`` albo NULL → 1, inaczej 0."""
    return 1 if status is None or str(status) == "1" else 0


def _blob_marker(entry: BlobEntry, outcome: CopyOutcome) -> tuple[str, str | None]:
    """``(content_hash, error)`` wg DEC-133: brak/zły rozmiar → ``''`` i ``migration: …``."""
    if outcome.status == "missing":
        return "", "migration: blob missing"
    if outcome.status == "size_mismatch":
        return (
            "",
            f"migration: blob size mismatch (declared {entry.expected_size},"
            f" actual {outcome.actual_size})",
        )
    return outcome.content_hash, None


def _target_row(  # noqa: PLR0913, PLR0917 — pełny wiersz celu w jednym miejscu
    row: Mapping[str, Any],
    source_ref: str | None,
    plan: BlobPlan,
    chunk_method: str,
    entry: BlobEntry,
    outcome: CopyOutcome,
    existing: Mapping[str, Any] | None,
    now_ms: int,
) -> dict[str, Any]:
    """Wiersz źródła ``document`` → wartości kolumn ``documents`` (kontrakt §5).

    ``source_ref`` (CONTRACT §7) niepuste znaczy „dokument z mapowania SharePoint”: wtedy
    ``source_type`` to ``sharepoint``, a ``source_ref`` — klucz elementu integracji. Reszta
    dokumentów zachowuje ``source_type`` źródła, a ``source_ref`` zostaje ``NULL``.
    """
    document_id = _text(row["id"])
    create_time, update_time = pick_times(row["create_time"], row["update_time"], existing, now_ms)
    content_hash, error = _blob_marker(entry, outcome)
    return {
        "id": document_id,
        "dataset_id": _text(row["kb_id"]),
        "created_by": row["created_by"],
        "name": _text(row["name"]),
        "suffix": _text(row["suffix"]),
        "type": _text(row["type"]),
        "size": 0 if row["size"] is None else int(row["size"]),
        "location": str(plan.doc_dest[document_id]),
        "content_hash": content_hash,
        "source_type": (
            SOURCE_TYPE_SHAREPOINT if source_ref is not None else _text(row["source_type"])
        ),
        "source_ref": source_ref,
        "chunk_method": chunk_method,
        "parser_config": dumps_json(split_parser_config(raw_parser_config(row["parser_config"]))),
        "run": "0",
        "progress": 0.0,
        "progress_msg": "",
        "error": error,
        "process_begin_at": None,
        "process_duration": 0.0,
        "chunk_count": 0,
        "token_count": 0,
        "enabled": _enabled(row["status"]),
        "meta_fields": "{}",
        "thumbnail": None,
        "create_time": create_time,
        "create_date": ms_naive(create_time),
        "update_time": update_time,
        "update_date": ms_naive(update_time),
    }


def _unchanged(existing: Mapping[str, Any], computed: Mapping[str, Any]) -> bool:
    """True, gdy każda kolumna celu równa się wyliczonej; JSON-y przez ``same_json`` (§5)."""
    for column in COLUMNS:
        if column in JSON_COLUMNS:
            if not same_json(existing[column], computed[column]):
                return False
        elif str(existing[column]) != str(computed[column]):
            return False
    return True


async def _fetch_existing(session: AsyncSession, ids: list[str]) -> dict[str, Mapping[str, Any]]:
    """Wiersze celu dla podanych id (klucz = id); puste ``ids`` → pusta mapa."""
    if not ids:
        return {}
    statement = text(_SELECT_EXISTING).bindparams(bindparam("ids", expanding=True))
    result = await session.execute(statement, {"ids": ids})
    return {
        str(row["id"]): {column: row[column] for column in COLUMNS}
        for row in result.mappings().all()
    }


async def _dataset_ids(session: AsyncSession, ids: list[str]) -> set[str]:
    """Id datasetów obecnych w ``datasets`` celu (kontrakt §5: filtr ``kb_id``)."""
    if not ids:
        return set()
    statement = text("SELECT id FROM datasets WHERE id IN :ids").bindparams(
        bindparam("ids", expanding=True)
    )
    result = await session.execute(statement, {"ids": ids})
    return {str(value) for value in result.scalars().all()}


async def _dataset_chunk_methods(session: AsyncSession, ids: list[str]) -> dict[str, str]:
    """``chunk_method`` datasetów celu (fallback, gdy ``parser_id`` nie ma mapowania)."""
    if not ids:
        return {}
    statement = text("SELECT id, chunk_method FROM datasets WHERE id IN :ids").bindparams(
        bindparam("ids", expanding=True)
    )
    result = await session.execute(statement, {"ids": ids})
    return {str(row["id"]): _text(row["chunk_method"]) for row in result.mappings().all()}


async def _target_ids(session: AsyncSession, ids: list[str]) -> set[str]:
    """Id ze zbioru ``ids`` obecne w ``documents`` po fazie."""
    if not ids:
        return set()
    statement = text(_SELECT_IDS).bindparams(bindparam("ids", expanding=True))
    result = await session.execute(statement, {"ids": ids})
    return {str(value) for value in result.scalars().all()}


def _blob_issue(document_id: str, entry: BlobEntry, outcome: CopyOutcome) -> Issue:
    """Uwaga ``warning`` o blobie dokumentu; komunikat bez ścieżek i treści (kontrakt §6)."""
    if outcome.status == "missing":
        return Issue(
            severity="warning",
            code=BLOB_MISSING,
            message="brak bloba dokumentu w źródle — wiersz przenoszony bez kopii",
            ids=[document_id],
        )
    return Issue(
        severity="warning",
        code=BLOB_SIZE_MISMATCH,
        message=(
            "rozmiar bloba dokumentu niezgodny z rozmiarem deklarowanym w źródle"
            f" (rozmiar w źródle: {outcome.actual_size})"
        ),
        ids=[document_id],
    )


async def _copy_document_blobs(
    rows: Sequence[Mapping[str, Any]], ctx: RunContext, plan: BlobPlan
) -> tuple[dict[str, CopyOutcome], list[Issue]]:
    """Kopiuje bloby dokumentów (wpis współdzielony raz po ``dest``), liczy je i zwraca uwagi."""
    if not rows:
        return {}, []
    if ctx.storage is None:
        raise RuntimeError("storage not configured")
    source = SourceFiles(ctx.src_files_dir)  # type: ignore[arg-type]
    counters: dict[str, int] = ctx.shared["documents_blobs"]
    new_keys: list[str] = ctx.shared.setdefault("new_blob_keys", [])
    counted: set[str] = ctx.shared.setdefault("_blob_counted", set())
    cache: dict[str, CopyOutcome] = {}
    outcomes: dict[str, CopyOutcome] = {}
    issues: list[Issue] = []
    for row in rows:
        document_id = _text(row["id"])
        entry = plan.entries[plan.doc_dest[document_id]]
        key = str(entry.dest)
        outcome = cache.get(key)
        if outcome is None:
            outcome = await copy_blob(
                ctx.storage, source, entry, dry_run=ctx.dry_run, new_keys=new_keys
            )
            cache[key] = outcome
            if key not in counted:
                counted.add(key)
                counters[outcome.status] += 1
        outcomes[document_id] = outcome
        if outcome.status in ("missing", "size_mismatch"):
            issues.append(_blob_issue(document_id, entry, outcome))
    return outcomes, issues


def _chunk_methods(
    rows: Sequence[Mapping[str, Any]], methods: Mapping[str, str]
) -> tuple[dict[str, str], list[str]]:
    """``chunk_method`` per dokument i id tych, dla których użyto metody datasetu (fallback)."""
    resolved: dict[str, str] = {}
    fallback: list[str] = []
    for row in rows:
        document_id = _text(row["id"])
        method = map_chunk_method(_text(row["parser_id"]))
        if method is None:
            method = methods.get(_text(row["kb_id"]), "")
            fallback.append(document_id)
        resolved[document_id] = method
    return resolved, fallback


async def run_documents(  # noqa: PLR0913, PLR0917 — faza dostaje wiersze, sesję i kontekst biegu
    src_rows: Sequence[Mapping[str, Any]],
    session: AsyncSession,
    ctx: RunContext,
    plan: BlobPlan,
    now_ms: int,
    source_refs: Mapping[str, str],
) -> PhaseResult:
    """Faza ``documents``: upsert ``document`` → ``documents`` i kopiowanie blobów dokumentów.

    ``source_refs`` (CONTRACT §7) to mapa id dokumentu źródła → klucz elementu SharePoint
    z tabeli mapowań; pusta mapa = brak mapowań w źródle (zachowanie z E4-6b).
    """
    datasets = await _dataset_ids(session, sorted({_text(row["kb_id"]) for row in src_rows}))
    present = [row for row in src_rows if _text(row["kb_id"]) in datasets]
    skipped_rows = [row for row in src_rows if _text(row["kb_id"]) not in datasets]
    issues: list[Issue] = []
    if skipped_rows:
        issues.append(
            Issue(
                severity="warning",
                code=DOC_DATASET_MISSING,
                message="dataset dokumentu nie istnieje w celu — dokument pominięty",
                ids=[_text(row["id"]) for row in skipped_rows],
            )
        )

    methods = await _dataset_chunk_methods(
        session, sorted({_text(row["kb_id"]) for row in present})
    )
    chunk_methods, fallback = _chunk_methods(present, methods)
    if fallback:
        issues.append(
            Issue(
                severity="info",
                code=CHUNK_METHOD_FALLBACK,
                message=(
                    "`parser_id` nie ma odpowiednika `chunk_method` w WD"
                    " — użyto `chunk_method` datasetu"
                ),
                ids=fallback,
            )
        )

    outcomes, blob_issues = await _copy_document_blobs(present, ctx, plan)
    issues += blob_issues

    source_ids = [_text(row["id"]) for row in present]
    existing = await _fetch_existing(session, source_ids)
    created = updated = skipped = len(skipped_rows)
    for row in present:
        document_id = _text(row["id"])
        entry = plan.entries[plan.doc_dest[document_id]]
        target = _target_row(
            row,
            source_refs.get(document_id),
            plan,
            chunk_methods[document_id],
            entry,
            outcomes[document_id],
            existing.get(document_id),
            now_ms,
        )
        if document_id not in existing:
            await session.execute(text(_INSERT), target)
            created += 1
        elif _unchanged(existing[document_id], target):
            skipped += 1
        else:
            await session.execute(text(_UPDATE), target)
            updated += 1
    present_ids = await _target_ids(session, source_ids)
    return PhaseResult(
        source_count=len(src_rows),
        created=created,
        updated=updated,
        skipped=skipped,
        target_count=len(present_ids),
        issues=issues,
    )
