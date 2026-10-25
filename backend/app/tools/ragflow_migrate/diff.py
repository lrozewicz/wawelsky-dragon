"""Komenda ``diff``: wiersze tabel celu zmienione po ``since`` (kontrakt E4-6c §3.3).

Mapa tabela→kolumna czasu jest **stała** (bez odczytu ``information_schema`` w czasie
działania); źródło: DDL ``backend/alembic/versions/0001..0003``. Wszystkie kolumny czasu celu
są typu BIGINT (milisekundy epoki), więc warunek to ``> since_ms``. Trzy tabele integracji
nie mają kolumn z reguły §3.3 — patrz DEC-145 (``integration_containers`` → ``discovered_at``,
``integration_sync_runs`` → ``started_at``, ``integration_sharepoint`` → czas rodzica 1:1
``integrations.updated_at``). Wyłącznie ``SELECT``; nic nie zapisuje.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.timeutil import iso, now_ms
from app.db.engine import make_engine, make_sessionmaker

VERSION = 1
COMMAND = "diff"

#: Maksymalna liczba id na tabelę w raporcie; więcej → ``truncated`` (kontrakt §3.3).
MAX_IDS = 1000

#: Liczba id pokazywanych w Markdownie na tabelę (brief T5, wymaganie 3).
MARKDOWN_IDS = 50


@dataclass(frozen=True)
class _Spec:
    """Stała specyfikacja jednej tabeli: ``FROM``, wyrażenie czasu i wyrażenie id."""

    table: str
    column: str  # etykieta kolumny czasu w raporcie
    source: str  # klauzula FROM (z JOIN dla integration_sharepoint)
    time_expr: str  # wyrażenie czasu w WHERE
    id_expr: str  # wyrażenie id w SELECT
    order_expr: str  # klucz sortowania (kolumny id)


#: Tabele WD w stałej kolejności (kontrakt §3.3); wszystkie kolumny czasu to BIGINT ms.
_SPECS: tuple[_Spec, ...] = (
    _Spec("users", "update_time", "users", "update_time", "CAST(id AS CHAR)", "id"),
    _Spec("datasets", "update_time", "datasets", "update_time", "CAST(id AS CHAR)", "id"),
    _Spec("documents", "update_time", "documents", "update_time", "CAST(id AS CHAR)", "id"),
    _Spec("chats", "update_time", "chats", "update_time", "CAST(id AS CHAR)", "id"),
    _Spec("chat_sessions", "update_time", "chat_sessions", "update_time", "CAST(id AS CHAR)", "id"),
    _Spec("chat_messages", "update_time", "chat_messages", "update_time", "CAST(id AS CHAR)", "id"),
    # assistant_access: PK złożony (email, chat_id) — id jako "email:chat_id" (brief T5, pkt 2).
    _Spec(
        "assistant_access",
        "created_at",
        "assistant_access",
        "created_at",
        "CONCAT(email, ':', chat_id)",
        "email, chat_id",
    ),
    _Spec("api_keys", "update_time", "api_keys", "update_time", "CAST(id AS CHAR)", "id"),
    _Spec("integrations", "updated_at", "integrations", "updated_at", "CAST(id AS CHAR)", "id"),
    # integration_sharepoint bez kolumny czasu → czas rodzica 1:1 (DEC-145).
    _Spec(
        "integration_sharepoint",
        "integrations.updated_at",
        "integration_sharepoint AS s JOIN integrations AS i ON i.id = s.integration_id",
        "i.updated_at",
        "CAST(s.integration_id AS CHAR)",
        "s.integration_id",
    ),
    # integration_containers bez kolumn z §3.3 → discovered_at (DEC-145); PK złożony.
    _Spec(
        "integration_containers",
        "discovered_at",
        "integration_containers",
        "discovered_at",
        "CONCAT(integration_id, ':', container_id)",
        "integration_id, container_id",
    ),
    # integration_item_mappings: PK złożony (integration_id, container_id, item_id).
    _Spec(
        "integration_item_mappings",
        "updated_at",
        "integration_item_mappings",
        "updated_at",
        "CONCAT(integration_id, ':', container_id, ':', item_id)",
        "integration_id, container_id, item_id",
    ),
    # integration_sync_runs bez kolumn z §3.3 → started_at (DEC-145).
    _Spec(
        "integration_sync_runs",
        "started_at",
        "integration_sync_runs",
        "started_at",
        "CAST(id AS CHAR)",
        "id",
    ),
    _Spec(
        "integration_sync_events",
        "created_at",
        "integration_sync_events",
        "created_at",
        "CAST(id AS CHAR)",
        "id",
    ),
)


@dataclass
class DiffTable:
    """Zmiany w jednej tabeli celu."""

    table: str
    column: str
    changed: int
    ids: list[str]
    truncated: bool


@dataclass
class DiffReport:
    """Raport ``diff`` (kontrakt §3.3)."""

    since: str
    since_ms: int
    started_at: str
    finished_at: str
    tables: list[DiffTable]

    def to_json(self) -> dict[str, Any]:
        """JSON raportu dokładnie wg §3.3 (``ids`` obcięte, ``changed`` pełny)."""
        return {
            "version": VERSION,
            "command": COMMAND,
            "since": self.since,
            "since_ms": self.since_ms,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "tables": [
                {
                    "table": entry.table,
                    "column": entry.column,
                    "changed": entry.changed,
                    "ids": list(entry.ids),
                    "truncated": entry.truncated,
                }
                for entry in self.tables
            ],
        }

    def to_markdown(self) -> str:
        """Markdown raportu: tabela (tabela, kolumna, zmienione) i listy id (pierwsze 50)."""
        lines = [
            "# Diff RAGFlow → WD",
            "",
            f"- od: {self.since}",
            f"- start: {self.started_at}",
            f"- koniec: {self.finished_at}",
            "",
            "| tabela | kolumna | zmienione |",
            "|---|---|---|",
        ]
        for entry in self.tables:
            lines.append(f"| {entry.table} | {entry.column} | {entry.changed} |")
        for entry in self.tables:
            lines += ["", f"## {entry.table}", ""]
            shown = entry.ids[:MARKDOWN_IDS]
            lines += [f"- {ident}" for ident in shown] or ["—"]
        return "\n".join(lines) + "\n"


async def run_diff(settings: Settings, since_ms: int) -> DiffReport:
    """Zwraca zmiany w tabelach celu od ``since_ms`` (kontrakt §3.3).

    Otwiera własny silnik do bazy celu (tylko ``SELECT``) i zamyka go po biegu. Brak tabeli
    w celu → wyjątek sterownika (schemat WD ma wszystkie 14 tabel).
    """
    started_at = iso(now_ms())
    engine = make_engine(settings)
    try:
        sessionmaker = make_sessionmaker(engine)
        async with sessionmaker() as session:
            tables = [await _diff_table(session, spec, since_ms) for spec in _SPECS]
    finally:
        await engine.dispose()
    return DiffReport(
        since=iso(since_ms),
        since_ms=since_ms,
        started_at=started_at,
        finished_at=iso(now_ms()),
        tables=tables,
    )


async def _diff_table(session: AsyncSession, spec: _Spec, since_ms: int) -> DiffTable:
    """Licznik (pełny) i posortowane id jednej tabeli; ``ids`` obcięte do ``MAX_IDS``."""
    changed = int((await session.execute(text(_count_sql(spec)), {"since": since_ms})).scalar_one())
    result = await session.execute(text(_ids_sql(spec)), {"since": since_ms})
    ids = [str(value) for value in result.scalars().all()]
    return DiffTable(
        table=spec.table,
        column=spec.column,
        changed=changed,
        ids=ids[:MAX_IDS],
        truncated=len(ids) > MAX_IDS,
    )


def _count_sql(spec: _Spec) -> str:
    """SQL licznika zmienionych wierszy (identyfikatory wyłącznie ze stałych modułu)."""
    return f"SELECT COUNT(*) FROM {spec.source} WHERE {spec.time_expr} > :since"  # noqa: S608


def _ids_sql(spec: _Spec) -> str:
    """SQL posortowanych id, o jeden ponad limit raportu (do wykrycia ``truncated``)."""
    return (
        f"SELECT {spec.id_expr} AS ident FROM {spec.source}"  # noqa: S608
        f" WHERE {spec.time_expr} > :since ORDER BY {spec.order_expr} LIMIT {MAX_IDS + 1}"
    )
