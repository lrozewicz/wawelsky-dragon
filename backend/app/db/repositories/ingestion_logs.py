"""Repozytorium logów ingestii (zadanie DS2) — Core ``text()`` z parametrami wiązanymi.

Upstream v0.27.2 trzyma logi w tabeli ``pipeline_operation_log`` (jeden wiersz na zakończoną
operację pipeline'u). WD nie ma tej tabeli (K2/C9): odpowiednikiem operacji parsowania jest
zadanie ``parse_document`` z tabeli ``tasks``, a pola pliku pochodzą z wiersza ``documents``
(upstream ``PipelineOperationLogService.create``: ``avatar = document.thumbnail``,
``operation_status = document.run``, ``process_begin_at``/``process_duration`` z dokumentu,
``parser_id``/``pipeline_title = document.parser_id``, ``source_from`` = pierwszy człon
``document.source_type``). Tożsamością logu jest ``tasks.public_id``.

Log powstaje tylko dla operacji w stanie końcowym (upstream ``_is_final_state``): dokument
w ``run`` 2 (CANCEL), 3 (DONE) albo 4 (FAIL). Trwający parse nie ma jeszcze wiersza logu.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import TextClause, bindparam, text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

# Task parsowania w tabeli ``tasks`` (worker/queue.py).
PARSE_TASK_TYPE = "parse_document"
# Stany ``documents.run``, dla których upstream ma już wiersz logu (2/3/4 = CANCEL/DONE/FAIL).
FINAL_RUNS = ("2", "3", "4")
# Kolumny sortowania listy logów — odpowiedniki getter_by(orderby) z upstream.
ORDER_BY_COLUMNS = {"create_time": "t.create_time", "update_time": "t.update_time"}

_COLUMNS = (
    "t.public_id AS id, t.task_type, t.document_id, t.dataset_id, t.create_time,"
    " t.update_time, d.name AS document_name, d.suffix AS document_suffix,"
    " d.type AS document_type, d.source_type, d.chunk_method, d.progress, d.progress_msg,"
    " d.thumbnail, d.process_begin_at, d.process_duration, d.run"
)
_FROM = " FROM tasks t JOIN documents d ON d.id = t.document_id"
_FINAL_RUNS_CONSTRAINT = "d.run IN :final_runs"


@dataclass(frozen=True)
class LogRow:
    """Wiersz logu ingestii pliku (zadanie parse + dokument) — pola złota --08/--09."""

    id: str
    task_type: str
    document_id: str
    dataset_id: str
    create_time: int
    update_time: int
    document_name: str
    document_suffix: str
    document_type: str
    source_type: str
    chunk_method: str
    progress: float
    progress_msg: str
    thumbnail: str | None
    process_begin_at: int | None
    process_duration: float
    run: str


def _row(row: RowMapping) -> LogRow:
    """RowMapping → LogRow (jawne rzutowania — wartości z bazy są ``Any``)."""
    return LogRow(
        id=cast("str", row["id"]),
        task_type=cast("str", row["task_type"]),
        document_id=cast("str", row["document_id"]),
        dataset_id=cast("str", row["dataset_id"]),
        create_time=cast("int", row["create_time"]),
        update_time=cast("int", row["update_time"]),
        document_name=cast("str", row["document_name"]),
        document_suffix=cast("str", row["document_suffix"]),
        document_type=cast("str", row["document_type"]),
        source_type=cast("str", row["source_type"]),
        chunk_method=cast("str", row["chunk_method"]),
        progress=float(row["progress"]),
        progress_msg=cast("str", row["progress_msg"]),
        thumbnail=cast("str | None", row["thumbnail"]),
        process_begin_at=cast("int | None", row["process_begin_at"]),
        process_duration=float(row["process_duration"]),
        run=cast("str", row["run"]),
    )


def _clauses(
    *,
    dataset_id: str,
    operation_status: Sequence[str],
    keywords: str | None,
    create_date_from: str | None,
    create_date_to: str | None,
) -> tuple[list[str], dict[str, Any]]:
    """Warunki i parametry; filtr dokładany tylko, gdy podany (upstream robi tak samo)."""
    clauses = ["t.dataset_id = :dataset_id", "t.task_type = :task_type", _FINAL_RUNS_CONSTRAINT]
    params: dict[str, Any] = {
        "dataset_id": dataset_id,
        "task_type": PARSE_TASK_TYPE,
        "final_runs": list(FINAL_RUNS),
    }
    if operation_status:
        clauses.append("d.run IN :statuses")
        params["statuses"] = list(operation_status)
    if keywords:
        clauses.append("LOWER(d.name) LIKE :keywords")
        params["keywords"] = f"%{keywords.lower()}%"
    if create_date_from:
        clauses.append("t.create_date >= :create_date_from")
        params["create_date_from"] = create_date_from
    if create_date_to:
        clauses.append("t.create_date <= :create_date_to")
        params["create_date_to"] = create_date_to
    return clauses, params


def _statement(
    columns: str, clauses: Sequence[str], params: dict[str, Any], tail: str = ""
) -> TextClause:
    """Buduje ``text()`` z warunkami; listy ``IN :…`` wiąże jako expanding."""
    sql = f"SELECT {columns}{_FROM} WHERE " + " AND ".join(clauses) + tail
    statement = text(sql)
    expanding = [name for name in ("final_runs", "statuses") if name in params]
    return statement.bindparams(*(bindparam(name, expanding=True) for name in expanding))


async def list_logs(  # noqa: PLR0913 — kształt parametrów listy z upstream (service)
    session: AsyncSession,
    *,
    dataset_id: str,
    offset: int,
    limit: int,
    orderby: str,
    desc: bool,
    operation_status: Sequence[str] = (),
    keywords: str | None = None,
    create_date_from: str | None = None,
    create_date_to: str | None = None,
) -> tuple[list[LogRow], int]:
    """Strona logów plików datasetu + liczba wszystkich pasujących (jak upstream)."""
    clauses, params = _clauses(
        dataset_id=dataset_id,
        operation_status=operation_status,
        keywords=keywords,
        create_date_from=create_date_from,
        create_date_to=create_date_to,
    )
    total = (await session.execute(_statement("COUNT(*)", clauses, params), params)).scalar_one()
    direction = "DESC" if desc else "ASC"
    tail = f" ORDER BY {ORDER_BY_COLUMNS[orderby]} {direction} LIMIT :limit OFFSET :offset"
    rows = (
        await session.execute(
            _statement(_COLUMNS, clauses, params, tail),
            {**params, "limit": limit, "offset": offset},
        )
    ).mappings()
    return [_row(row) for row in rows], int(total)


async def get_log(session: AsyncSession, *, dataset_id: str, log_id: str) -> LogRow | None:
    """Log pliku po ``public_id`` w obrębie datasetu; brak/obcy dataset → None."""
    clauses, params = _clauses(
        dataset_id=dataset_id,
        operation_status=(),
        keywords=None,
        create_date_from=None,
        create_date_to=None,
    )
    rows = (
        await session.execute(
            _statement(_COLUMNS, [*clauses, "t.public_id = :log_id"], params),
            {**params, "log_id": log_id},
        )
    ).mappings()
    row = rows.first()
    return None if row is None else _row(row)
