"""Faza ``files`` etapu ``documents``: ``file`` → ``files`` (kontrakt §5, WP E4-6b1).

Wiersze źródłowe ``file`` dostaje faza gotowe (jedno czytanie źródła w ``documents.py``).
Faza wstawia wiersze od korzeni w dół (FK ``fk_files_parent``) i kopiuje bloby **tylko**
plików bez dokumentu — wpisy z właścicielem ``document:`` kopiuje faza ``documents``.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.tools.ragflow_migrate.blobs import BlobEntry, BlobPlan, CopyOutcome, SourceFiles, copy_blob
from app.tools.ragflow_migrate.stages.base import Issue, PhaseResult, RunContext
from app.tools.ragflow_migrate.stages.common import ms_naive, pick_times

#: Kolumny celu pisane przez fazę (kolejność = lista INSERT), wg DDL ``files``.
COLUMNS: tuple[str, ...] = (
    "id",
    "tenant_id",
    "created_by",
    "parent_id",
    "name",
    "type",
    "size",
    "location",
    "source_type",
    "create_time",
    "create_date",
    "update_time",
    "update_date",
)

#: Kody uwag fazy (kontrakt §5).
ORPHAN = "file_orphan"
BLOB_MISSING = "file_blob_missing"
BLOB_SIZE_MISMATCH = "file_blob_size_mismatch"

_COLUMN_LIST = ", ".join(COLUMNS)
# Nazwy kolumn pochodzą ze stałej ``COLUMNS`` (nie z danych), więc interpolacja jest bezpieczna.
_INSERT = f"INSERT INTO files ({_COLUMN_LIST}) VALUES ({', '.join(':' + c for c in COLUMNS)})"  # noqa: S608
_UPDATE = f"UPDATE files SET {', '.join(f'{c} = :{c}' for c in COLUMNS)} WHERE id = :id"  # noqa: S608
_SELECT_EXISTING = f"SELECT {_COLUMN_LIST} FROM files WHERE id IN :ids"  # noqa: S608
_SELECT_IDS = "SELECT id FROM files WHERE id IN :ids"


def _text(value: Any) -> str:
    """Wartość kolumny jako tekst; ``None`` → ``''``."""
    return "" if value is None else str(value)


def _is_folder(row: Mapping[str, Any]) -> bool:
    return _text(row.get("type")) == "folder"


def _is_root(row: Mapping[str, Any]) -> bool:
    """Root RAGFlow wskazuje na siebie (``parent_id == id``) — w celu dostaje ``parent_id NULL``."""
    return _text(row.get("parent_id")) == _text(row.get("id"))


def _ordered(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[list[Mapping[str, Any]], list[str]]:
    """Wiersze w kolejności od korzeni w dół (BFS po głębokości) i id sierot.

    Sierotą jest wiersz, do którego nie prowadzi żadna ścieżka od korzenia (brak rodzica
    w źródle albo cykl). Potomkowie sieroty też nie są osiągalni, więc przepadają razem z nią.
    """
    children: dict[str, list[Mapping[str, Any]]] = {}
    roots: list[Mapping[str, Any]] = []
    for row in rows:
        if _is_root(row):
            roots.append(row)
        else:
            children.setdefault(_text(row["parent_id"]), []).append(row)

    queue: list[tuple[Mapping[str, Any], int]] = [(row, 0) for row in roots]
    visited = {_text(row["id"]) for row in roots}
    ordered: list[tuple[Mapping[str, Any], int]] = []
    while queue:
        row, depth = queue.pop(0)
        ordered.append((row, depth))
        for child in children.get(_text(row["id"]), []):
            if _text(child["id"]) not in visited:
                visited.add(_text(child["id"]))
                queue.append((child, depth + 1))
    ordered.sort(key=lambda item: item[1])
    orphans = sorted(_text(row["id"]) for row in rows if _text(row["id"]) not in visited)
    return [row for row, _ in ordered], orphans


def _target_row(
    row: Mapping[str, Any],
    plan: BlobPlan,
    existing: Mapping[str, Any] | None,
    now_ms: int,
) -> dict[str, Any]:
    """Wiersz źródła ``file`` → wartości kolumn celu (kontrakt §5)."""
    create_time, update_time = pick_times(row["create_time"], row["update_time"], existing, now_ms)
    file_id = _text(row["id"])
    return {
        "id": file_id,
        "tenant_id": row["tenant_id"],
        "created_by": row["created_by"],
        "parent_id": None if _is_root(row) else row["parent_id"],
        "name": row["name"],
        "type": row["type"],
        "size": 0 if row["size"] is None else int(row["size"]),
        "location": None if _is_folder(row) else str(plan.file_dest[file_id]),
        "source_type": _text(row["source_type"]) or "local",
        "create_time": create_time,
        "create_date": ms_naive(create_time),
        "update_time": update_time,
        "update_date": ms_naive(update_time),
    }


def _unchanged(existing: Mapping[str, Any], computed: Mapping[str, Any]) -> bool:
    """True, gdy każda kolumna celu w wierszu istniejącym równa się wyliczonej (idempotencja)."""
    return all(str(existing[column]) == str(computed[column]) for column in COLUMNS)


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


async def _target_ids(session: AsyncSession, ids: list[str]) -> set[str]:
    """Id ze zbioru ``ids`` obecne w ``files`` po fazie."""
    if not ids:
        return set()
    statement = text(_SELECT_IDS).bindparams(bindparam("ids", expanding=True))
    result = await session.execute(statement, {"ids": ids})
    return {str(value) for value in result.scalars().all()}


def _file_only(entry: BlobEntry) -> bool:
    """Wpis należy do pliku i nie ma właściciela-dokumentu (kopiuje go ta faza)."""
    return any(owner.startswith("file:") for owner in entry.owners) and not any(
        owner.startswith("document:") for owner in entry.owners
    )


def _file_ids(entry: BlobEntry) -> list[str]:
    """Id plików-właścicieli wpisu (bez prefiksu)."""
    return sorted(owner.split(":", 1)[1] for owner in entry.owners if owner.startswith("file:"))


def _blob_issue(entry: BlobEntry, outcome: CopyOutcome) -> Issue:
    """Uwaga ``warning`` o blobie pliku; komunikaty bez ścieżek i treści (kontrakt §6)."""
    ids = _file_ids(entry)
    if outcome.status == "missing":
        return Issue(
            severity="warning",
            code=BLOB_MISSING,
            message="brak bloba pliku w źródle — wiersz przenoszony bez kopii",
            ids=ids,
        )
    return Issue(
        severity="warning",
        code=BLOB_SIZE_MISMATCH,
        message=(
            "rozmiar bloba pliku niezgodny z rozmiarem deklarowanym w źródle"
            f" (rozmiar w źródle: {outcome.actual_size})"
        ),
        ids=ids,
    )


async def _copy_file_blobs(ctx: RunContext, plan: BlobPlan) -> list[Issue]:
    """Kopiuje bloby plików bez dokumentu, liczy je w ``ctx.shared['documents_blobs']``."""
    entries = [entry for entry in plan.entries.values() if _file_only(entry)]
    if not entries:
        return []
    if ctx.storage is None:
        raise RuntimeError("storage not configured")
    source = SourceFiles(ctx.src_files_dir)  # type: ignore[arg-type]
    counters: dict[str, int] = ctx.shared["documents_blobs"]
    new_keys: list[str] = ctx.shared.setdefault("new_blob_keys", [])
    issues: list[Issue] = []
    for entry in entries:
        outcome = await copy_blob(
            ctx.storage, source, entry, dry_run=ctx.dry_run, new_keys=new_keys
        )
        counters[outcome.status] += 1
        if outcome.status in ("missing", "size_mismatch"):
            issues.append(_blob_issue(entry, outcome))
    return issues


async def run_files(  # noqa: PLR0913, PLR0917 — pełny kontekst fazy w jednym miejscu
    src_rows: Sequence[Mapping[str, Any]],
    tree_rows: Sequence[Mapping[str, Any]],
    session: AsyncSession,
    ctx: RunContext,
    plan: BlobPlan,
    now_ms: int,
) -> PhaseResult:
    """Faza ``files``: upsert ``file`` → ``files`` i bloby plików bez dokumentu.

    ``src_rows`` to wiersze do upsertu (przy ``--since`` tylko zmienione), a ``tree_rows`` —
    pełna tabela ``file``: kolejność (FK ``parent_id``) i sieroty liczymy z całego drzewa,
    inaczej przyrost zgłosiłby fałszywe ``file_orphan`` dla zmienionego dziecka (kontrakt §2).
    """
    ordered, orphans = _ordered(tree_rows)
    wanted = {_text(row["id"]) for row in src_rows}
    rows = [row for row in ordered if _text(row["id"]) in wanted]
    issues: list[Issue] = []
    if orphans:
        issues.append(
            Issue(
                severity="warning",
                code=ORPHAN,
                message=f"pliki bez rodzica w źródle — pominięte razem z potomkami: {len(orphans)}",
                ids=orphans,
            )
        )
    source_ids = [_text(row["id"]) for row in rows]
    existing = await _fetch_existing(session, source_ids)
    created = updated = skipped = len(orphans)
    for row in rows:
        target = _target_row(row, plan, existing.get(_text(row["id"])), now_ms)
        if target["id"] not in existing:
            await session.execute(text(_INSERT), target)
            created += 1
        elif _unchanged(existing[target["id"]], target):
            skipped += 1
        else:
            await session.execute(text(_UPDATE), target)
            updated += 1
    present = await _target_ids(session, source_ids)
    issues += await _copy_file_blobs(ctx, plan)
    return PhaseResult(
        source_count=len(src_rows),
        created=created,
        updated=updated,
        skipped=skipped,
        target_count=len(present),
        issues=issues,
    )
