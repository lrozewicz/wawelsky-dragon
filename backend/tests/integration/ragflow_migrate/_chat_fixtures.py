"""Pomocnik testów etapów ``chats``, ``sessions`` i ``access`` (CONTRACT WP E4-6b2 §5).

Bez fixture'ów pytest — zwykłe funkcje i kontekst-menedżery. T2 i T3 importują te nazwy,
więc nie zmieniaj ich.
"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any
from urllib.parse import unquote, urlsplit

import pymysql
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.container import Container
from app.main import create_app
from app.tools.ragflow_migrate import stages
from app.tools.ragflow_migrate.runner import run_all
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import RunContext, StageResult
from tests.integration.ragflow_migrate.conftest import WdDb

U1_ID = "b0a1c2d3e4f5061728394a5b6c7d8e91"
U2_ID = "b0a1c2d3e4f5061728394a5b6c7d8e92"
D1_ID = "e1f2a3b4c5d60718293a4b5c6d7e8f01"
D2_ID = "e1f2a3b4c5d60718293a4b5c6d7e8f02"
S1_ID = "7c6d5e4f3a2b10819293a4b5c6d7e801"
S2_ID = "7c6d5e4f3a2b10819293a4b5c6d7e802"

# Tokeny FIKCYJNE z expectations.json (nie sekrety) — dlatego noqa: S105.
U1_TOKEN = "ragflow-FIXTURE-u1-plain"  # noqa: S105
U2_TOKEN = "ragflow-FIXTURE-u2-beta"  # noqa: S105

#: Etapy potrzebne, by odczyt przez API (§6) widział czaty, sesje i dostęp (kontrakt §5).
API_ONLY: tuple[str, ...] = ("users", "models", "datasets", "chats", "sessions", "keys", "access")


@contextmanager
def source_writer(dsn: str) -> Iterator[pymysql.connections.Connection]:
    """Zapisywalne połączenie ze źródłem (sesja `Source` jest READ ONLY) — modyfikacje testu."""
    parts = urlsplit(dsn)
    conn = pymysql.connect(
        host=parts.hostname,
        port=parts.port or 3306,
        user=unquote(parts.username or ""),
        password=unquote(parts.password or ""),
        database=unquote(parts.path.lstrip("/")),
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        yield conn
    finally:
        conn.close()


async def scalar(
    sm: async_sessionmaker[AsyncSession], sql: str, params: dict[str, Any] | None = None
) -> Any:
    """Pojedyncza wartość z bazy WD (świeża transakcja)."""
    async with sm() as session:
        result = await session.execute(text(sql), params or {})
        return result.scalar_one()


async def row(
    sm: async_sessionmaker[AsyncSession], sql: str, params: dict[str, Any]
) -> dict[str, Any]:
    """Pierwszy wiersz jako słownik (wielokolumnowe asercje)."""
    async with sm() as session:
        result = await session.execute(text(sql), params)
        found = result.mappings().first()
        return dict(found) if found is not None else {}


async def rows(
    sm: async_sessionmaker[AsyncSession], sql: str, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Wszystkie wiersze jako słowniki (asercje na listach powiązań)."""
    async with sm() as session:
        result = await session.execute(text(sql), params or {})
        return [dict(record) for record in result.mappings().all()]


def client(settings: Any, tmp_path: Any) -> TestClient:
    """Aplikacja na bazie WD testu (storage w katalogu tymczasowym), jak w test_stage_keys."""
    app_settings = settings.model_copy(update={"storage_root": str(tmp_path)})
    return TestClient(
        create_app(app_settings, Container(app_settings)), base_url="https://testserver"
    )


def bearer(token: str) -> dict[str, str]:
    """Nagłówek uwierzytelnienia kluczem przeniesionym z RAGFlow (§6)."""
    return {"Authorization": f"Bearer {token}"}


async def migrate(
    source: Source,
    wd_db: WdDb,
    ctx: RunContext,
    only: Sequence[str] | None = None,
    dry_run: bool = False,
) -> list[StageResult]:
    """Bieg etapów na fixture'u; ``only=None`` → etapy ``API_ONLY`` obecne w rejestrze.

    Kolejność etapów bierze ``run_all`` z ``ORDER``, więc ``only`` jest zbiorem nazw.
    """
    selected = (
        list(only) if only is not None else [name for name in API_ONLY if name in stages.STAGES]
    )
    return await run_all(source, wd_db.sm, ctx, only=selected, dry_run=dry_run)
