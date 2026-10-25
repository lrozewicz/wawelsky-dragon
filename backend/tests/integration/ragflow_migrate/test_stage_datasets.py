"""Testy etapu `datasets` na fixture źródła RAGFlow (brief T6, kontrakt §4) — wymagają MariaDB."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import Any
from urllib.parse import unquote, urlsplit

import pymysql
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.tools.ragflow_migrate import stages
from app.tools.ragflow_migrate.model_map import MappedModel, ModelMap
from app.tools.ragflow_migrate.runner import plan_all, run_all
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import RunContext, StageInventory, StageResult
from tests.integration.ragflow_migrate.conftest import SourceDb, WdDb

pytestmark = pytest.mark.db

KB1_ID = "d1e2f3a4b5c60718293a4b5c6d7e8f01"
KB2_ID = "d1e2f3a4b5c60718293a4b5c6d7e8f02"
KB3_ID = "d1e2f3a4b5c60718293a4b5c6d7e8f03"
U1_ID = "b0a1c2d3e4f5061728394a5b6c7d8e91"
U2_ID = "b0a1c2d3e4f5061728394a5b6c7d8e92"
EXTRA_KB_ID = "d1e2f3a4b5c60718293a4b5c6d7e8f09"
SOURCE_DATASETS = 3
EMBEDDING_MODEL = "fake-embed-1024"
EMBEDDING_KEY = "fake-embed-1024@OpenAI-API-Compatible"
EMBEDDING_DIM = 1024
LEGACY_KEY = "wd_legacy_parser_config"
KB_CREATE_TIME = 1759305840000

#: Kolumny, którymi etap zapisuje `datasets` (kontrakt §4) — do asercji po biegu.
DATASET_COLUMNS = (
    "id",
    "tenant_id",
    "created_by",
    "name",
    "description",
    "avatar",
    "language",
    "embedding_model",
    "embedding_dim",
    "permission",
    "chunk_method",
    "parser_config",
    "similarity_threshold",
    "vector_similarity_weight",
    "pagerank",
    "document_count",
    "chunk_count",
    "token_num",
    "status",
    "create_time",
)


@contextmanager
def _source_writer(dsn: str) -> Iterator[pymysql.connections.Connection]:
    """Zapisywalne połączenie ze źródłem (sesja `Source` jest READ ONLY) — na modyfikacje testu."""
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


def _insert_knowledgebase(
    conn: pymysql.connections.Connection,
    *,
    kb_id: str,
    name: str,
    parser_id: str,
    tenant_id: str = U1_ID,
) -> None:
    """Dokłada wiersz `knowledgebase` do źródła (test kolizji nazwy i nieznanej metody)."""
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO `knowledgebase` (`id`,`create_time`,`create_date`,`update_time`,"
            " `update_date`,`avatar`,`tenant_id`,`name`,`language`,`description`,`embd_id`,"
            " `permission`,`created_by`,`doc_num`,`token_num`,`chunk_num`,`similarity_threshold`,"
            " `vector_similarity_weight`,`parser_id`,`pipeline_id`,`parser_config`,`pagerank`,"
            " `status`) VALUES (%s,%s,NOW(),%s,NOW(),NULL,%s,%s,'English','Kolizja (test).',%s,"
            " 'me',%s,0,0,0,0.2,0.3,%s,NULL,'{\"chunk_token_num\": 64}',0,'1')",
            (
                kb_id,
                KB_CREATE_TIME,
                KB_CREATE_TIME,
                tenant_id,
                name,
                EMBEDDING_KEY,
                tenant_id,
                parser_id,
            ),
        )


async def _scalar(
    sm: async_sessionmaker[AsyncSession], sql: str, params: dict[str, Any] | None = None
) -> Any:
    """Pojedyncza wartość z bazy WD (świeża transakcja)."""
    async with sm() as session:
        result = await session.execute(text(sql), params or {})
        return result.scalar_one()


async def _count(sm: async_sessionmaker[AsyncSession]) -> int:
    """Liczba wierszy `datasets`."""
    return int(await _scalar(sm, "SELECT COUNT(*) FROM datasets"))


async def _dataset(sm: async_sessionmaker[AsyncSession], dataset_id: str) -> dict[str, Any]:
    """Wiersz `datasets` o podanym id (kolumny etapu + generowana `name_ci`)."""
    columns = ", ".join((*DATASET_COLUMNS, "name_ci"))
    async with sm() as session:
        row = (
            (
                await session.execute(
                    text(f"SELECT {columns} FROM datasets WHERE id = :id"),  # noqa: S608
                    {"id": dataset_id},
                )
            )
            .mappings()
            .first()
        )
    return dict(row) if row is not None else {}


async def _ids(sm: async_sessionmaker[AsyncSession]) -> set[str]:
    """Zbiór id w `datasets`."""
    async with sm() as session:
        result = await session.execute(text("SELECT id FROM datasets"))
        return {str(value) for value in result.scalars().all()}


def _migrate(source: Source, wd_db: WdDb, ctx: RunContext, **kwargs: Any) -> Any:
    """Bieg `users` + `models` + `datasets` (kolejność `ORDER`); zwraca wszystkie wyniki."""
    return run_all(source, wd_db.sm, ctx, only=["users", "models", "datasets"], **kwargs)


async def _migrate_datasets(
    source: Source, wd_db: WdDb, ctx: RunContext, **kwargs: Any
) -> StageResult:
    """Bieg trzech etapów i wynik etapu `datasets`."""
    results = await _migrate(source, wd_db, ctx, **kwargs)
    assert [result.stage for result in results] == ["users", "models", "datasets"]
    return results[-1]


def _issue_ids(inventory: Any, code: str) -> set[str]:
    """Zbiór id uwag o danym kodzie."""
    return {row_id for issue in inventory.issues if issue.code == code for row_id in issue.ids}


def test_plan_counts_and_issues(source: Source, wd_db: WdDb, run_ctx: RunContext) -> None:
    """`plan` podaje licznik `knowledgebase` i nie zgłasza uwag dla fixture'u (bez zapisu)."""
    inventory = plan_all(source, run_ctx, only=["datasets"])[0]
    assert inventory.stage == "datasets"
    assert inventory.source_counts == {"knowledgebase": SOURCE_DATASETS}
    assert inventory.not_migrated == {}
    assert inventory.issues == []


async def test_plan_writes_nothing(source: Source, wd_db: WdDb, run_ctx: RunContext) -> None:
    """`plan` nie pisze do `datasets`."""
    plan_all(source, run_ctx, only=["datasets"])
    assert await _count(wd_db.sm) == 0


async def test_run_migrates_datasets_with_source_ids(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """`run` tworzy 3 datasety z zachowaniem id i mapuje liczniki źródła."""
    result = await _migrate_datasets(source, wd_db, run_ctx)
    assert (result.created, result.updated, result.skipped) == (SOURCE_DATASETS, 0, 0)
    assert result.source_count == SOURCE_DATASETS
    assert result.target_count == SOURCE_DATASETS
    assert result.issues == []
    assert await _ids(wd_db.sm) == {KB1_ID, KB2_ID, KB3_ID}

    kb1 = await _dataset(wd_db.sm, KB1_ID)
    assert kb1["tenant_id"] == U1_ID
    assert kb1["created_by"] == U1_ID
    assert kb1["name"] == "kb-naive"
    assert kb1["name_ci"] == "kb-naive"
    assert kb1["chunk_method"] == "naive"
    assert kb1["permission"] == "me"
    assert kb1["embedding_model"] == EMBEDDING_MODEL
    assert kb1["embedding_dim"] == EMBEDDING_DIM
    assert kb1["similarity_threshold"] == pytest.approx(0.2)
    assert kb1["vector_similarity_weight"] == pytest.approx(0.3)
    assert kb1["pagerank"] == 0
    assert (kb1["document_count"], kb1["chunk_count"], kb1["token_num"]) == (2, 10, 1000)
    assert kb1["status"] == "1"
    assert kb1["create_time"] == KB_CREATE_TIME

    kb2 = await _dataset(wd_db.sm, KB2_ID)
    assert kb2["chunk_method"] == "qa"
    assert kb2["permission"] == "team"

    kb3 = await _dataset(wd_db.sm, KB3_ID)
    assert kb3["chunk_method"] == "book"
    assert kb3["tenant_id"] == U2_ID
    assert kb3["created_by"] == U2_ID
    assert kb3["embedding_model"] == EMBEDDING_MODEL


async def test_parser_config_keeps_known_keys_and_nests_unknown(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """kb1: znane klucze na wierzchu, nieznany klucz pod `wd_legacy_parser_config` (kontrakt §4)."""
    await _migrate_datasets(source, wd_db, run_ctx)
    kb1 = json.loads(str((await _dataset(wd_db.sm, KB1_ID))["parser_config"]))
    assert kb1 == {
        "chunk_token_num": 128,
        "delimiter": "\n",
        "layout_recognize": "DeepDOC",
        LEGACY_KEY: {"unknown_key": 1},
    }
    kb2 = json.loads(str((await _dataset(wd_db.sm, KB2_ID))["parser_config"]))
    assert kb2 == {
        "chunk_token_num": 256,
        "delimiter": "\n",
        "auto_keywords": 0,
        "auto_questions": 0,
    }
    unknown = await _scalar(
        wd_db.sm,
        f"SELECT JSON_EXTRACT(parser_config, '$.{LEGACY_KEY}.unknown_key')"  # noqa: S608
        " FROM datasets WHERE id = :id",
        {"id": KB1_ID},
    )
    assert json.loads(str(unknown)) == 1


async def test_second_run_is_idempotent(source: Source, wd_db: WdDb, run_ctx: RunContext) -> None:
    """Drugi bieg: `created == 0`, `updated == 0`, wszystko pominięte, liczba wierszy bez zmian."""
    first = await _migrate_datasets(source, wd_db, run_ctx)
    second = await _migrate_datasets(source, wd_db, run_ctx)
    assert first.created == SOURCE_DATASETS
    assert (second.created, second.updated, second.skipped) == (0, 0, SOURCE_DATASETS)
    assert second.source_count == SOURCE_DATASETS
    assert second.target_count == first.target_count == SOURCE_DATASETS
    assert await _count(wd_db.sm) == SOURCE_DATASETS


async def test_dry_run_writes_nothing(source: Source, wd_db: WdDb, run_ctx: RunContext) -> None:
    """`dry_run=True`: raport liczy wiersze, ale po biegu `datasets` jest puste (rollback)."""
    result = await _migrate_datasets(source, wd_db, run_ctx, dry_run=True)
    assert result.created == SOURCE_DATASETS
    assert result.target_count == SOURCE_DATASETS
    assert await _count(wd_db.sm) == 0


async def test_all_stages_in_one_run_and_second_run_is_idempotent(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """Pełny bieg `users`+`models`+`datasets`+`keys`: etap datasets 3 utworzone, drugi bieg pusty.

    Współpraca etapów w jednej sesji: `datasets` bierze właścicieli i modele z `ctx.shared`
    poprzednich etapów, a `keys` domyka bieg bez Issue `critical` (commit całego biegu).
    """
    stages = ["users", "models", "datasets", "keys"]
    first = await run_all(source, wd_db.sm, run_ctx, only=stages)
    assert [result.stage for result in first] == stages
    assert all(issue.severity != "critical" for result in first for issue in result.issues)
    datasets = _by_stage(first, "datasets")
    assert (datasets.created, datasets.updated, datasets.skipped) == (SOURCE_DATASETS, 0, 0)
    assert datasets.target_count == SOURCE_DATASETS

    second = await run_all(source, wd_db.sm, run_ctx, only=stages)
    datasets_again = _by_stage(second, "datasets")
    assert (datasets_again.created, datasets_again.updated, datasets_again.skipped) == (
        0,
        0,
        SOURCE_DATASETS,
    )
    assert datasets_again.target_count == SOURCE_DATASETS
    assert await _count(wd_db.sm) == SOURCE_DATASETS


def _by_stage(results: list[StageResult], stage: str) -> StageResult:
    """Wynik etapu o podanej nazwie."""
    return next(result for result in results if result.stage == stage)


async def test_only_datasets_uses_target_users_and_models(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """`--only datasets` bez wcześniejszych etapów w sesji: właściciele i wymiar z celu.

    Kontekst drugiego biegu ma puste `shared` i mapę bez wymiaru — etap musi policzyć właścicieli
    z tabeli `users` i wymiar embeddingu z tabeli `models` (brief T6 pkt 3).
    """
    await run_all(source, wd_db.sm, run_ctx, only=["users", "models"])
    without_dimension = ModelMap({EMBEDDING_KEY: MappedModel(EMBEDDING_MODEL, "embedding", None)})
    ctx = replace(run_ctx, shared={}, model_map=without_dimension)
    results = await run_all(source, wd_db.sm, ctx, only=["datasets"])
    assert [result.created for result in results] == [SOURCE_DATASETS]
    assert [issue.code for issue in results[0].issues] == []
    kb1 = await _dataset(wd_db.sm, KB1_ID)
    assert kb1["embedding_model"] == EMBEDDING_MODEL
    assert kb1["embedding_dim"] == EMBEDDING_DIM  # z tabeli `models` (mapa bez wymiaru)


async def test_name_collision_is_critical_and_rows_are_not_written(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(a) Duplikat nazwy w tenancie → `critical dataset_name_collision`, brak zapisu obu wierszy.

    Oba wiersze kolidujące są pomijane, a Issue `critical` wstrzymuje commit całego biegu.
    """
    with _source_writer(ragflow_src.dsn) as conn:
        _insert_knowledgebase(conn, kb_id=EXTRA_KB_ID, name="kb-naive", parser_id="naive")
    result = await _migrate_datasets(source, wd_db, run_ctx)
    collisions = [issue for issue in result.issues if issue.code == "dataset_name_collision"]
    assert len(collisions) == 1
    assert collisions[0].severity == "critical"
    assert set(collisions[0].ids) == {KB1_ID, EXTRA_KB_ID}
    assert result.source_count == SOURCE_DATASETS + 1
    assert (result.created, result.updated, result.skipped) == (SOURCE_DATASETS - 1, 0, 2)
    assert await _count(wd_db.sm) == 0  # rollback całego biegu (Issue critical)

    # Sam etap też nie pisze kolidujących wierszy: przy ręcznym commicie zostają kb2 i kb3.
    async with wd_db.sm() as session:
        await stages.STAGES["users"].run(source, session, run_ctx)
        await stages.STAGES["models"].run(source, session, run_ctx)
        await session.commit()
        direct = await stages.STAGES["datasets"].run(source, session, run_ctx)
        await session.commit()
    assert direct.created == SOURCE_DATASETS - 1
    assert await _ids(wd_db.sm) == {KB2_ID, KB3_ID}


async def test_unknown_chunk_method_is_critical_and_row_is_not_written(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(b) `parser_id='resume'` (nieobsługiwany w WD) → `critical chunk_method_unsupported`."""
    with _source_writer(ragflow_src.dsn) as conn:
        _insert_knowledgebase(conn, kb_id=EXTRA_KB_ID, name="kb-resume", parser_id="resume")
    result = await _migrate_datasets(source, wd_db, run_ctx)
    unsupported = [issue for issue in result.issues if issue.code == "chunk_method_unsupported"]
    assert len(unsupported) == 1
    assert unsupported[0].severity == "critical"
    assert unsupported[0].ids == [EXTRA_KB_ID]
    assert result.created == SOURCE_DATASETS
    assert result.skipped == 1
    assert await _count(wd_db.sm) == 0  # rollback całego biegu (Issue critical)


def test_plan_reports_unknown_chunk_method(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(c) `plan` widzi nieobsługiwany `parser_id` bez bazy celu."""
    with _source_writer(ragflow_src.dsn) as conn:
        _insert_knowledgebase(conn, kb_id=EXTRA_KB_ID, name="kb-tag", parser_id="tag")
    inventory: StageInventory = plan_all(source, run_ctx, only=["datasets"])[0]
    assert _issue_ids(inventory, "chunk_method_unsupported") == {EXTRA_KB_ID}
    assert inventory.source_counts == {"knowledgebase": SOURCE_DATASETS + 1}
