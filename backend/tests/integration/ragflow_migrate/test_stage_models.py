"""Testy etapu `models` na fixture źródła RAGFlow (brief T5, kontrakt §4) — wymagają MariaDB."""

from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.tools.ragflow_migrate import cli, stages
from app.tools.ragflow_migrate.model_map import ModelMap
from app.tools.ragflow_migrate.runner import run_all
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import RunContext
from tests.integration.ragflow_migrate.conftest import SourceDb, WdDb

pytestmark = pytest.mark.db

#: Liczba różnych używanych modeli w źródle fixture'u (policzona z `data.sql`): chat OpenAI,
#: chat Tongyi, embedding OpenAI. `unused-model@OpenAI` nie jest używany.
USED_MODELS = 3

#: Wymiar `fake-embed-1024` w mapie fixture'u (`model-map.yaml`, kontrakt §5).
FAKE_EMBED_DIM = 1024

#: Kod wyjścia CLI przy jakimkolwiek Issue `critical` (kontrakt §2).
EXIT_CRITICAL = 2

#: Oczekiwane nazwy WD dla mapy fixture'u (`model-map.yaml`).
EXPECTED_MODEL_NAMES = {
    "fake-chat@OpenAI-API-Compatible": "fake-chat",
    "fake-chat@Tongyi-Qianwen": "fake-chat-tongyi",
    "fake-embed-1024@OpenAI-API-Compatible": "fake-embed-1024",
}

_FAKE_CHAT_KEYS = ["fake-chat@OpenAI-API-Compatible", "fake-chat@Tongyi-Qianwen"]


async def _models(sm: async_sessionmaker[AsyncSession]) -> list[dict[str, object]]:
    """Wiersze tabeli `models` po biegu (osobna sesja — widzi tylko commitowane dane)."""
    async with sm() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id, name, model_type, provider, display_name, base_url, api_key_enc,"
                    " max_tokens, dimension, extra, is_default, is_active, created_by,"
                    " create_time, create_date FROM models"
                )
            )
        ).mappings()
        return [dict(row) for row in rows]


async def _count(sm: async_sessionmaker[AsyncSession], table: str) -> int:
    async with sm() as session:
        return int(
            (await session.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar_one()  # noqa: S608
        )


def test_plan_counts_and_issues(source: Source, run_ctx: RunContext) -> None:
    """`plan` podaje liczniki tabel i Issue `models_unused`; z mapą fixture'u brak critical."""
    inventory = stages.STAGES["models"].plan(source, run_ctx)
    assert inventory.stage == "models"
    assert inventory.source_counts == {"tenant_llm": 4, "llm": 0, "knowledgebase": 3}
    assert inventory.not_migrated == {"llm": 0}
    assert [issue.severity for issue in inventory.issues] == ["info"]
    unused = inventory.issues[0]
    assert unused.code == "models_unused"
    assert unused.ids == []
    assert "1" in unused.message


async def test_run_creates_used_models(source: Source, wd_db: WdDb, run_ctx: RunContext) -> None:
    """`run` pisze dokładnie używane modele i wypełnia `ctx.shared["model_names"]`."""
    results = await run_all(source, wd_db.sm, run_ctx, only=["models"])
    assert [result.created for result in results] == [USED_MODELS]
    assert results[0].skipped == 0

    rows = await _models(wd_db.sm)
    assert {str(row["name"]) for row in rows} == set(EXPECTED_MODEL_NAMES.values())
    by_name = {str(row["name"]): row for row in rows}
    assert by_name["fake-embed-1024"]["dimension"] == FAKE_EMBED_DIM
    assert by_name["fake-chat"]["model_type"] == "chat"
    assert by_name["fake-chat-tongyi"]["model_type"] == "chat"
    assert by_name["fake-chat"]["provider"] == "litellm"
    assert by_name["fake-chat"]["created_by"] is None
    assert by_name["fake-chat"]["api_key_enc"] is None
    assert by_name["fake-chat"]["is_active"] == 1
    assert by_name["fake-chat"]["create_time"] > 0

    assert run_ctx.shared["model_names"] == EXPECTED_MODEL_NAMES


async def test_run_skips_unused_model(source: Source, wd_db: WdDb, run_ctx: RunContext) -> None:
    """`unused-model@OpenAI` (skonfigurowany, ale nieużywany) NIE trafia do `models`."""
    await run_all(source, wd_db.sm, run_ctx, only=["models"])
    names = {str(row["name"]) for row in await _models(wd_db.sm)}
    assert "unused-model" not in names


async def test_second_run_is_idempotent(source: Source, wd_db: WdDb, run_ctx: RunContext) -> None:
    """Drugi bieg: `created == 0`, `skipped == USED_MODELS`, `target_count` bez zmian."""
    first = await run_all(source, wd_db.sm, run_ctx, only=["models"])
    second = await run_all(source, wd_db.sm, run_ctx, only=["models"])
    assert first[0].created == USED_MODELS
    assert second[0].created == 0
    assert second[0].updated == 0
    assert second[0].skipped == USED_MODELS
    assert second[0].target_count == first[0].target_count == USED_MODELS
    assert await _count(wd_db.sm, "models") == USED_MODELS


async def test_run_without_model_map_is_critical_and_rolls_back(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """Pusta mapa → critical `model_ambiguous` dla `fake-chat`; bieg nie commituje."""
    ctx = replace(run_ctx, model_map=ModelMap({}))
    results = await run_all(source, wd_db.sm, ctx, only=["models"])
    critical = [issue for issue in results[0].issues if issue.severity == "critical"]
    assert [issue.code for issue in critical] == ["model_ambiguous"]
    assert critical[0].ids == _FAKE_CHAT_KEYS
    assert results[0].created == 1  # w transakcji: sam embedding
    assert await _count(wd_db.sm, "models") == 0  # rollback


async def test_dry_run_leaves_models_untouched(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """`dry_run` → liczba wierszy `models` równa stanowi sprzed biegu."""
    before = await _count(wd_db.sm, "models")
    await run_all(source, wd_db.sm, run_ctx, only=["models"], dry_run=True)
    assert await _count(wd_db.sm, "models") == before


def test_cli_run_without_model_map_exits_2(
    ragflow_src: SourceDb, wd_db: WdDb, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLI `run` bez mapy: critical `model_ambiguous` → kod wyjścia 2."""
    _export_env(monkeypatch, wd_db)
    code = cli.main(
        [
            "run",
            "--src-mysql",
            ragflow_src.dsn,
            "--report-dir",
            str(tmp_path),
        ]
    )
    assert code == EXIT_CRITICAL
    assert list(tmp_path.glob("migration-report-*.json"))
    assert list(tmp_path.glob("migration-report-*.md"))


def _export_env(monkeypatch: pytest.MonkeyPatch, wd_db: WdDb) -> None:
    """Ustawia env `WD_DB_*` (i `WD_ENV=test`) na bazę docelową testu — CLI tworzy `Settings()`."""
    settings = wd_db.settings
    monkeypatch.setenv("WD_ENV", "test")
    monkeypatch.setenv("WD_DB_HOST", settings.db_host)
    monkeypatch.setenv("WD_DB_PORT", str(settings.db_port))
    monkeypatch.setenv("WD_DB_USER", settings.db_user)
    monkeypatch.setenv("WD_DB_PASSWORD", settings.db_password.get_secret_value())
    monkeypatch.setenv("WD_DB_NAME", settings.db_name)
