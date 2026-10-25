"""Testy etapu `chats` migracji RAGFlow→WD (brief T1, kontrakt §2 i §6) — wymagają MariaDB."""

import json
from dataclasses import replace
from typing import Any

import pytest

from app.tools.ragflow_migrate.model_map import MappedModel, ModelMap
from app.tools.ragflow_migrate.runner import plan_all
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import RunContext, StageResult
from tests.integration.ragflow_migrate._chat_fixtures import (
    D1_ID,
    D2_ID,
    U1_ID,
    U1_TOKEN,
    U2_TOKEN,
    bearer,
    client,
    migrate,
    row,
    rows,
    scalar,
    source_writer,
)
from tests.integration.ragflow_migrate.conftest import SourceDb, WdDb

pytestmark = pytest.mark.db

DS1_ID = "d1e2f3a4b5c60718293a4b5c6d7e8f01"
DS2_ID = "d1e2f3a4b5c60718293a4b5c6d7e8f02"
DS3_ID = "d1e2f3a4b5c60718293a4b5c6d7e8f03"

ID_ORPHAN = "e1f2a3b4c5d60718293a4b5c6d7e8f99"
ID_COLLISION_A = "e1f2a3b4c5d60718293a4b5c6d7e8f11"
ID_COLLISION_B = "e1f2a3b4c5d60718293a4b5c6d7e8f12"
ID_MISSING_DS = "e1f2a3b4c5d60718293a4b5c6d7e8f21"
ID_UNMAPPED = "e1f2a3b4c5d60718293a4b5c6d7e8f31"
ID_BAD_JSON = "e1f2a3b4c5d60718293a4b5c6d7e8f41"
ID_EMPTY_KB = "e1f2a3b4c5d60718293a4b5c6d7e8f42"

CHAT_KEY = "fake-chat@OpenAI-API-Compatible"
EMBEDDING_KEY = "fake-embed-1024@OpenAI-API-Compatible"
EXTRA_EMBEDDING_KEY = "fake-embed-2048@OpenAI-API-Compatible"
EXTRA_EMBEDDING_NAME = "fake-embed-2048"
MISSING_DATASET_ID = "nie-ma"

#: Etapy potrzebne samemu etapowi `chats` (kontrakt §5).
CHAT_ONLY = ["users", "models", "datasets", "chats"]

#: Bieg bez etapu `models`: `ctx.shared['model_names']` zostaje puste, więc mapowanie idzie
#: wyłącznie przez `ctx.model_map` (przypadki `chat_llm_unmapped` i różnych embeddingów).
NO_MODELS_ONLY = ["users", "datasets", "chats"]

SOURCE_DIALOGS = 2
COLLIDING_DIALOGS = 2
D1_LINKS = 2
ORPHAN_TENANT_ID = "b0a1c2d3e4f5061728394a5b6c7d8e99"
HTTP_OK = 200

#: Mapa modeli fixture'u (``model-map.yaml``) — jawne wpisy dla przypadków bez etapu `models`.
FIXTURE_MODELS = {
    CHAT_KEY: MappedModel(name="fake-chat", model_type="chat", dimension=None),
    "fake-chat@Tongyi-Qianwen": MappedModel(
        name="fake-chat-tongyi", model_type="chat", dimension=None
    ),
    EMBEDDING_KEY: MappedModel(name="fake-embed-1024", model_type="embedding", dimension=1024),
}

_DIALOG_DEFAULTS: dict[str, Any] = {
    "create_time": 1759306080000,
    "update_time": 1759306080000,
    "tenant_id": U1_ID,
    "name": "nowy-czat",
    "description": None,
    "icon": None,
    "language": "English",
    "llm_id": CHAT_KEY,
    "llm_setting": '{"temperature": 0.5}',
    "prompt_type": "simple",
    "prompt_config": '{"system": "Test."}',
    "meta_data_filter": None,
    "similarity_threshold": 0.2,
    "vector_similarity_weight": 0.3,
    "top_n": 6,
    "top_k": 1024,
    "do_refer": "1",
    "rerank_id": "",
    "kb_ids": "[]",
    "status": "1",
}

_DIALOG_INSERT = (
    "INSERT INTO `dialog` (`id`,`create_time`,`create_date`,`update_time`,`update_date`,"
    "`tenant_id`,`name`,`description`,`icon`,`language`,`llm_id`,`llm_setting`,`prompt_type`,"
    "`prompt_config`,`meta_data_filter`,`similarity_threshold`,`vector_similarity_weight`,"
    "`top_n`,`top_k`,`do_refer`,`rerank_id`,`kb_ids`,`status`)"
    " VALUES (%s, %s, NOW(), %s, NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
    " %s, %s, %s, %s, %s)"
)


def insert_dialog(conn: Any, dialog_id: str, **overrides: Any) -> None:
    """Wstawia wiersz ``dialog`` do źródła (brief pkt 3f — bez edycji ``data.sql``)."""
    values = {**_DIALOG_DEFAULTS, **overrides}
    params = (
        dialog_id,
        values["create_time"],
        values["update_time"],
        values["tenant_id"],
        values["name"],
        values["description"],
        values["icon"],
        values["language"],
        values["llm_id"],
        values["llm_setting"],
        values["prompt_type"],
        values["prompt_config"],
        values["meta_data_filter"],
        values["similarity_threshold"],
        values["vector_similarity_weight"],
        values["top_n"],
        values["top_k"],
        values["do_refer"],
        values["rerank_id"],
        values["kb_ids"],
        values["status"],
    )
    with conn.cursor() as cursor:
        cursor.execute(_DIALOG_INSERT, params)


def issue_ids(result: StageResult, code: str) -> set[str]:
    """Zbiór id uwag o danym kodzie w wyniku etapu."""
    return {row_id for issue in result.issues if issue.code == code for row_id in issue.ids}


def severities(result: StageResult, code: str) -> list[str]:
    """Wagi uwag o danym kodzie (kolejność jak w wyniku etapu)."""
    return [issue.severity for issue in result.issues if issue.code == code]


async def test_run_migrates_chats_with_links(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(a) Dwa dialogi → dwa czaty; `chat_datasets` z `ordinal` 0,1 dla d1; id zachowane."""
    results = await migrate(source, wd_db, run_ctx, only=CHAT_ONLY)
    chats = results[-1]
    assert chats.stage == "chats"
    assert chats.source_count == SOURCE_DIALOGS
    assert (chats.created, chats.updated, chats.skipped) == (SOURCE_DIALOGS, 0, 0)
    assert chats.target_count == SOURCE_DIALOGS
    assert chats.issues == []
    assert await scalar(wd_db.sm, "SELECT COUNT(*) FROM chats") == SOURCE_DIALOGS
    assert (
        await scalar(wd_db.sm, "SELECT name FROM chats WHERE id = :id", {"id": D1_ID}) == "chat-rag"
    )
    assert await rows(
        wd_db.sm,
        "SELECT chat_id, dataset_id, ordinal FROM chat_datasets ORDER BY chat_id, ordinal",
    ) == [
        {"chat_id": D1_ID, "dataset_id": DS1_ID, "ordinal": 0},
        {"chat_id": D1_ID, "dataset_id": DS2_ID, "ordinal": 1},
        {"chat_id": D2_ID, "dataset_id": DS3_ID, "ordinal": 0},
    ]
    assert run_ctx.shared["chat_ids"] == {D1_ID, D2_ID}


async def test_run_maps_llm_ids_to_wd_names(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(b) `llm_id` zmapowane przez mapę modeli: `fake-chat` (d1), `fake-chat-tongyi` (d2)."""
    await migrate(source, wd_db, run_ctx, only=CHAT_ONLY)
    assert (
        await scalar(wd_db.sm, "SELECT llm_id FROM chats WHERE id = :id", {"id": D1_ID})
        == "fake-chat"
    )
    assert (
        await scalar(wd_db.sm, "SELECT llm_id FROM chats WHERE id = :id", {"id": D2_ID})
        == "fake-chat-tongyi"
    )


async def test_second_run_is_idempotent(source: Source, wd_db: WdDb, run_ctx: RunContext) -> None:
    """(c) Drugi bieg: created 0, updated 0, skipped 2 — liczba powiązań bez zmian."""
    await migrate(source, wd_db, run_ctx, only=CHAT_ONLY)
    links = await scalar(wd_db.sm, "SELECT COUNT(*) FROM chat_datasets")
    second = (await migrate(source, wd_db, run_ctx, only=CHAT_ONLY))[-1]
    assert (second.created, second.updated, second.skipped) == (0, 0, SOURCE_DIALOGS)
    assert second.target_count == SOURCE_DIALOGS
    assert await scalar(wd_db.sm, "SELECT COUNT(*) FROM chat_datasets") == links


async def test_changed_dialog_is_updated_with_links(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(c) Zmiana nazwy i datasetów w źródle → `updated` i przepisane powiązania."""
    await migrate(source, wd_db, run_ctx, only=CHAT_ONLY)
    with source_writer(ragflow_src.dsn) as conn, conn.cursor() as cursor:
        cursor.execute(
            "UPDATE `dialog` SET `name` = %s, `kb_ids` = %s WHERE `id` = %s",
            ("chat-book-2", json.dumps([DS2_ID]), D2_ID),
        )
    second = (await migrate(source, wd_db, run_ctx, only=CHAT_ONLY))[-1]
    assert (second.created, second.updated, second.skipped) == (0, 1, 1)
    assert (
        await scalar(wd_db.sm, "SELECT name FROM chats WHERE id = :id", {"id": D2_ID})
        == "chat-book-2"
    )
    assert await rows(
        wd_db.sm,
        "SELECT dataset_id FROM chat_datasets WHERE chat_id = :id",
        {"id": D2_ID},
    ) == [{"dataset_id": DS2_ID}]


async def test_dry_run_writes_nothing(source: Source, wd_db: WdDb, run_ctx: RunContext) -> None:
    """(d) `--dry-run` nie zostawia wierszy w `chats`/`chat_datasets`, ale ustawia `chat_ids`."""
    results = await migrate(source, wd_db, run_ctx, only=CHAT_ONLY, dry_run=True)
    assert results[-1].created == SOURCE_DIALOGS
    assert await scalar(wd_db.sm, "SELECT COUNT(*) FROM chats") == 0
    assert await scalar(wd_db.sm, "SELECT COUNT(*) FROM chat_datasets") == 0
    assert run_ctx.shared["chat_ids"] == {D1_ID, D2_ID}


async def test_source_dialog_table_is_untouched(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(e) Licznik `dialog` w źródle bez zmian po biegu etapu."""
    before = source.count("dialog")
    await migrate(source, wd_db, run_ctx, only=CHAT_ONLY)
    assert source.count("dialog") == before == SOURCE_DIALOGS


async def test_plan_counts_and_writes_nothing(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(g) `plan`: licznik `dialog`, brak uwag i brak zapisu do celu."""
    inventory = plan_all(source, run_ctx, only=["chats"])[0]
    assert inventory.stage == "chats"
    assert inventory.source_counts == {"dialog": SOURCE_DIALOGS}
    assert inventory.not_migrated == {}
    assert inventory.issues == []
    assert await scalar(wd_db.sm, "SELECT COUNT(*) FROM chats") == 0


async def test_missing_owner_is_critical(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(f) Właściciel spoza `user` → critical `chat_owner_missing`, bieg nie commituje."""
    with source_writer(ragflow_src.dsn) as conn:
        insert_dialog(conn, ID_ORPHAN, tenant_id=ORPHAN_TENANT_ID, name="chat-orphan")
    inventory = plan_all(source, run_ctx, only=["chats"])[0]
    assert {issue.code for issue in inventory.issues} == {"chat_owner_missing"}
    result = (await migrate(source, wd_db, run_ctx, only=CHAT_ONLY))[-1]
    assert result.source_count == SOURCE_DIALOGS + 1
    assert result.skipped == 1
    assert issue_ids(result, "chat_owner_missing") == {ID_ORPHAN}
    assert severities(result, "chat_owner_missing") == ["critical"]
    assert await scalar(wd_db.sm, "SELECT COUNT(*) FROM chats") == 0


async def test_name_collision_is_critical(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(f) Dwie nazwy różniące się wielkością liter u jednego tenanta → critical dla obu."""
    with source_writer(ragflow_src.dsn) as conn:
        insert_dialog(conn, ID_COLLISION_A, name="Chat X")
        insert_dialog(conn, ID_COLLISION_B, name="chat x")
    inventory = plan_all(source, run_ctx, only=["chats"])[0]
    assert {issue.code for issue in inventory.issues} == {"chat_name_collision"}
    result = (await migrate(source, wd_db, run_ctx, only=CHAT_ONLY))[-1]
    assert issue_ids(result, "chat_name_collision") == {ID_COLLISION_A, ID_COLLISION_B}
    assert severities(result, "chat_name_collision") == ["critical"]
    assert result.skipped == COLLIDING_DIALOGS
    assert await scalar(wd_db.sm, "SELECT COUNT(*) FROM chats") == 0


async def test_missing_dataset_warns_and_skips_link(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(f) `kb_ids` z nieistniejącym datasetem → warning `chat_dataset_missing`, czat zapisany."""
    with source_writer(ragflow_src.dsn) as conn:
        insert_dialog(
            conn,
            ID_MISSING_DS,
            name="chat-brak",
            kb_ids=json.dumps([MISSING_DATASET_ID]),
        )
    result = (await migrate(source, wd_db, run_ctx, only=CHAT_ONLY))[-1]
    assert issue_ids(result, "chat_dataset_missing") == {ID_MISSING_DS, MISSING_DATASET_ID}
    assert severities(result, "chat_dataset_missing") == ["warning"]
    assert result.created == SOURCE_DIALOGS + 1
    assert await scalar(wd_db.sm, "SELECT COUNT(*) FROM chats") == SOURCE_DIALOGS + 1
    assert (
        await scalar(
            wd_db.sm,
            "SELECT COUNT(*) FROM chat_datasets WHERE chat_id = :id",
            {"id": ID_MISSING_DS},
        )
        == 0
    )


async def test_unmapped_llm_and_rerank_warn(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(f) `llm_id`/`rerank_id` bez mapowania → warningi i puste wartości w celu."""
    with source_writer(ragflow_src.dsn) as conn:
        insert_dialog(
            conn,
            ID_UNMAPPED,
            name="chat-niemapowany",
            llm_id="brak@nikt",
            rerank_id="rerank@nikt",
        )
    inventory = plan_all(source, run_ctx, only=["chats"])[0]
    assert issue_ids(inventory, "chat_llm_unmapped") == {ID_UNMAPPED}
    assert issue_ids(inventory, "chat_rerank_unmapped") == {ID_UNMAPPED}
    result = (await migrate(source, wd_db, run_ctx, only=NO_MODELS_ONLY))[-1]
    assert severities(result, "chat_llm_unmapped") == ["warning"]
    assert severities(result, "chat_rerank_unmapped") == ["warning"]
    assert await row(
        wd_db.sm,
        "SELECT llm_id, rerank_id FROM chats WHERE id = :id",
        {"id": ID_UNMAPPED},
    ) == {"llm_id": "", "rerank_id": ""}


async def test_invalid_json_falls_back(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(f) Niepoprawny JSON → `chat_json_invalid` i wartości domyślne; puste `kb_ids` bez uwagi."""
    meta = '{"method": "auto", "from_llm": false}'
    with source_writer(ragflow_src.dsn) as conn:
        insert_dialog(
            conn,
            ID_BAD_JSON,
            name="chat-json",
            llm_setting="{nie-json",
            prompt_config="[1]",
            kb_ids="{nie-json",
            meta_data_filter=meta,
        )
        insert_dialog(conn, ID_EMPTY_KB, name="chat-puste", kb_ids="")
    result = (await migrate(source, wd_db, run_ctx, only=CHAT_ONLY))[-1]
    assert issue_ids(result, "chat_json_invalid") == {ID_BAD_JSON}
    assert severities(result, "chat_json_invalid") == ["warning", "warning", "warning"]
    assert await row(
        wd_db.sm,
        "SELECT llm_setting, prompt_config, meta_data_filter FROM chats WHERE id = :id",
        {"id": ID_BAD_JSON},
    ) == {
        "llm_setting": "{}",
        "prompt_config": "{}",
        "meta_data_filter": meta,
    }
    assert (
        await scalar(
            wd_db.sm,
            "SELECT COUNT(*) FROM chat_datasets WHERE chat_id = :id",
            {"id": ID_BAD_JSON},
        )
        == 0
    )
    assert result.created == SOURCE_DIALOGS + 2


async def test_embedding_mismatch_warns_and_chat_is_written(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(f) Datasety czatu z różnymi embeddingami → warning `chat_embedding_mismatch`."""
    with source_writer(ragflow_src.dsn) as conn, conn.cursor() as cursor:
        cursor.execute(
            "UPDATE `knowledgebase` SET `embd_id` = %s WHERE `id` = %s",
            (EXTRA_EMBEDDING_KEY, DS2_ID),
        )
    ctx = replace(
        run_ctx,
        model_map=ModelMap(
            {
                **FIXTURE_MODELS,
                EXTRA_EMBEDDING_KEY: MappedModel(
                    name=EXTRA_EMBEDDING_NAME, model_type="embedding", dimension=2048
                ),
            }
        ),
    )
    result = (await migrate(source, wd_db, ctx, only=NO_MODELS_ONLY))[-1]
    assert (
        await scalar(
            wd_db.sm, "SELECT embedding_model FROM datasets WHERE id = :id", {"id": DS2_ID}
        )
        == EXTRA_EMBEDDING_NAME
    )
    assert issue_ids(result, "chat_embedding_mismatch") == {D1_ID}
    assert severities(result, "chat_embedding_mismatch") == ["warning"]
    assert result.created == SOURCE_DIALOGS
    assert (
        await scalar(
            wd_db.sm,
            "SELECT COUNT(*) FROM chat_datasets WHERE chat_id = :id",
            {"id": D1_ID},
        )
        == D1_LINKS
    )


async def test_api_lists_migrated_chats(
    source: Source, wd_db: WdDb, run_ctx: RunContext, tmp_path: Any
) -> None:
    """(h) `GET /api/v1/chats` profilem 0.24: właściciel widzi swój czat z datasetami i modelem.

    Bieg bez etapu `access` (T3 WP E4-6b2): po jego dołączeniu alice widziałaby także czat d1
    z grantu (K7), co zmieniłoby intencję tego testu (widoczność właścicielska).
    """
    await migrate(source, wd_db, run_ctx, only=[*CHAT_ONLY, "keys"])
    with client(wd_db.settings, tmp_path) as http:
        u1_response = http.get("/api/v1/chats", headers=bearer(U1_TOKEN))
        u2_response = http.get("/api/v1/chats", headers=bearer(U2_TOKEN))
    assert u1_response.status_code == HTTP_OK
    u1_body = u1_response.json()
    assert u1_body["code"] == 0, u1_body
    # u1 to admin fixture'u (superuser), więc widzi czaty wszystkich tenantów (07 §7) —
    # asertujemy wiersz d1, a nie długość listy.
    u1_items = {item["id"]: item for item in u1_body["data"]}
    assert set(u1_items) == {D1_ID, D2_ID}
    assert u1_items[D1_ID]["name"] == "chat-rag"
    assert [item["id"] for item in u1_items[D1_ID]["datasets"]] == [DS1_ID, DS2_ID]
    assert u1_items[D1_ID]["llm"]["model_name"] == "fake-chat"
    u2_body = u2_response.json()
    assert u2_body["code"] == 0, u2_body
    assert [item["id"] for item in u2_body["data"]] == [D2_ID]
    assert u2_body["data"][0]["name"] == "chat-book"
    assert [item["id"] for item in u2_body["data"][0]["datasets"]] == [DS3_ID]
    assert u2_body["data"][0]["llm"]["model_name"] == "fake-chat-tongyi"
