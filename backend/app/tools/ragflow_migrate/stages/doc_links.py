"""Faza ``file2document`` etapu ``documents``: ``file2document`` → ``file2document`` (§5, T4c).

Wiersze źródłowe dostaje faza gotowe (jedno czytanie źródła w ``documents.py``). Faza nie
dotyka blobów. Link pomijamy, gdy wskazany plik albo dokument nie trafił do celu
(``warning`` ``link_skipped``), oraz gdy para ``(file_id, document_id)`` należy już do innego
wiersza celu albo została zajęta przez wcześniejszy wiersz źródła (``warning``
``link_duplicate``).
"""

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.tools.ragflow_migrate.stages.base import Issue, PhaseResult, RunContext
from app.tools.ragflow_migrate.stages.common import ms_naive, pick_times

#: Kolumny celu pisane przez fazę (kolejność = lista INSERT), wg DDL ``file2document``.
COLUMNS: tuple[str, ...] = (
    "id",
    "file_id",
    "document_id",
    "create_time",
    "create_date",
    "update_time",
    "update_date",
)

#: Kody uwag fazy (kontrakt §5).
LINK_SKIPPED = "link_skipped"
LINK_DUPLICATE = "link_duplicate"

_COLUMN_LIST = ", ".join(COLUMNS)
_VALUES = ", ".join(":" + column for column in COLUMNS)
# Nazwy kolumn pochodzą ze stałej ``COLUMNS`` (nie z danych), więc interpolacja jest bezpieczna.
_INSERT = f"INSERT INTO file2document ({_COLUMN_LIST}) VALUES ({_VALUES})"  # noqa: S608
_UPDATE = f"UPDATE file2document SET {', '.join(f'{c} = :{c}' for c in COLUMNS)} WHERE id = :id"  # noqa: S608
_SELECT_EXISTING = f"SELECT {_COLUMN_LIST} FROM file2document WHERE id IN :ids"  # noqa: S608
_SELECT_IDS = "SELECT id FROM file2document WHERE id IN :ids"
_SELECT_FILES = "SELECT id FROM files WHERE id IN :ids"
_SELECT_DOCUMENTS = "SELECT id FROM documents WHERE id IN :ids"
_SELECT_PAIRS = "SELECT id, file_id, document_id FROM file2document WHERE file_id IN :ids"


def _text(value: Any) -> str:
    """Wartość kolumny jako tekst; ``None`` → ``''``."""
    return "" if value is None else str(value)


def _target_row(
    row: Mapping[str, Any], existing: Mapping[str, Any] | None, now_ms: int
) -> dict[str, Any]:
    """Wiersz źródła ``file2document`` → wartości kolumn celu (kontrakt §5)."""
    create_time, update_time = pick_times(row["create_time"], row["update_time"], existing, now_ms)
    return {
        "id": _text(row["id"]),
        "file_id": _text(row["file_id"]),
        "document_id": _text(row["document_id"]),
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


async def _present_ids(session: AsyncSession, statement_sql: str, ids: list[str]) -> set[str]:
    """Id ze zbioru ``ids`` obecne w tabeli wskazanej zapytaniem ``statement_sql``."""
    if not ids:
        return set()
    statement = text(statement_sql).bindparams(bindparam("ids", expanding=True))
    result = await session.execute(statement, {"ids": ids})
    return {str(value) for value in result.scalars().all()}


async def _existing_pairs(session: AsyncSession, file_ids: list[str]) -> dict[tuple[str, str], str]:
    """Pary ``(file_id, document_id)`` już obecne w celu → id wiersza, który je zajmuje."""
    if not file_ids:
        return {}
    statement = text(_SELECT_PAIRS).bindparams(bindparam("ids", expanding=True))
    result = await session.execute(statement, {"ids": file_ids})
    return {
        (_text(row["file_id"]), _text(row["document_id"])): str(row["id"])
        for row in result.mappings().all()
    }


async def _target_ids(session: AsyncSession, ids: list[str]) -> set[str]:
    """Id ze zbioru ``ids`` obecne w ``file2document`` po fazie."""
    if not ids:
        return set()
    statement = text(_SELECT_IDS).bindparams(bindparam("ids", expanding=True))
    result = await session.execute(statement, {"ids": ids})
    return {str(value) for value in result.scalars().all()}


def _skipped_issue(ids: list[str]) -> Issue:
    """Uwaga ``warning`` o linkach bez pliku albo dokumentu w celu (kontrakt §5)."""
    return Issue(
        severity="warning",
        code=LINK_SKIPPED,
        message="plik albo dokument linku nie istnieje w celu — link pominięty",
        ids=ids,
    )


def _duplicate_issue(ids: list[str]) -> Issue:
    """Uwaga ``warning`` o parach ``(file_id, document_id)`` zajętych przez inny wiersz (§5)."""
    return Issue(
        severity="warning",
        code=LINK_DUPLICATE,
        message="para (file_id, document_id) należy do innego linku celu — link pominięty",
        ids=ids,
    )


async def run_links(
    src_rows: Sequence[Mapping[str, Any]],
    session: AsyncSession,
    ctx: RunContext,
    now_ms: int,
) -> PhaseResult:
    """Faza ``file2document``: upsert ``file2document`` → ``file2document`` (kontrakt §5)."""
    file_ids = sorted({_text(row.get("file_id")) for row in src_rows})
    document_ids = sorted({_text(row.get("document_id")) for row in src_rows})
    present_files = await _present_ids(session, _SELECT_FILES, file_ids)
    present_documents = await _present_ids(session, _SELECT_DOCUMENTS, document_ids)

    source_ids = [_text(row["id"]) for row in src_rows]
    existing = await _fetch_existing(session, source_ids)
    pairs = await _existing_pairs(session, file_ids)

    skipped_links: list[str] = []
    duplicate_links: list[str] = []
    created = updated = skipped = 0
    for row in src_rows:
        link_id = _text(row["id"])
        file_id = _text(row.get("file_id"))
        document_id = _text(row.get("document_id"))
        if file_id not in present_files or document_id not in present_documents:
            skipped_links.append(link_id)
            skipped += 1
            continue
        key = (file_id, document_id)
        owner = pairs.get(key)
        if owner is not None and owner != link_id:
            duplicate_links.append(link_id)
            skipped += 1
            continue
        target = _target_row(row, existing.get(link_id), now_ms)
        if link_id not in existing:
            await session.execute(text(_INSERT), target)
            created += 1
        elif _unchanged(existing[link_id], target):
            skipped += 1
        else:
            await session.execute(text(_UPDATE), target)
            updated += 1
        pairs[key] = link_id

    issues: list[Issue] = []
    if skipped_links:
        issues.append(_skipped_issue(skipped_links))
    if duplicate_links:
        issues.append(_duplicate_issue(duplicate_links))
    present = await _target_ids(session, source_ids)
    return PhaseResult(
        source_count=len(src_rows),
        created=created,
        updated=updated,
        skipped=skipped,
        target_count=len(present),
        issues=issues,
    )
