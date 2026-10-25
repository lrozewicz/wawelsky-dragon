"""Wnioski E4-6b spłacone w E4-6c (CONTRACT §7): ``source_ref``/``source_type`` dokumentów
z mapowań SharePoint, ``access.created_at`` przy źródłowym NULL-u, ``plan`` →
``chat_embedding_mismatch``. Testy wymagają MariaDB (marker ``db``).
"""

from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.tools.ragflow_migrate.model_map import MappedModel, ModelMap
from app.tools.ragflow_migrate.runner import plan_all
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.access import resolve_access
from app.tools.ragflow_migrate.stages.base import RunContext, StageInventory, StageResult
from tests.integration.ragflow_migrate._chat_fixtures import D1_ID, migrate, row, source_writer
from tests.integration.ragflow_migrate.conftest import SourceDb, WdDb

pytestmark = pytest.mark.db

#: Etapy biegu sprawdzającego `source_ref` (CONTRACT §7 pkt 1, brief T6).
DOC_STAGES = ["users", "models", "datasets", "documents", "integrations"]

#: Etapy samego etapu `chats` bez `models` — mapowanie modeli idzie wtedy przez `ctx.model_map`
#: (wzór: `test_stage_chats.py`, przypadki `NO_MODELS_ONLY`).
CHAT_STAGES = ["users", "datasets", "chats"]

DOC_F01 = "f1a2b3c4d5e60718293a4b5c6d7e8f01"  # mapowanie SharePoint (item …0001)
DOC_F02 = "f1a2b3c4d5e60718293a4b5c6d7e8f02"  # mapowanie SharePoint (item …0002)
DOC_F03 = "f1a2b3c4d5e60718293a4b5c6d7e8f03"  # bez mapowania, `source_type='notion'`
DOC_F04 = "f1a2b3c4d5e60718293a4b5c6d7e8f04"  # bez mapowania, `source_type='sharepoint'`

#: Wiersze mapowań źródła wskazujące DOC_F01/DOC_F02 (dane fixture'u, nie hipoteza testu).
INTEGRATION_ID = 1
DRIVE_ID = "b!FIXTUREDRIVE0000000000000001"
ITEM_F01 = "01FIXTUREITEM0000000000000001"
ITEM_F02 = "01FIXTUREITEM0000000000000002"
NEW_ITEM = "01FIXTUREITEM0000000000000009"

#: Datasety czatu D1 (kb1, kb2) i klucze modeli embeddingu (CONTRACT §7 pkt 3).
DS1_ID = "d1e2f3a4b5c60718293a4b5c6d7e8f01"
DS2_ID = "d1e2f3a4b5c60718293a4b5c6d7e8f02"
CHAT_KEY = "fake-chat@OpenAI-API-Compatible"
TONGYI_KEY = "fake-chat@Tongyi-Qianwen"
EMBEDDING_KEY = "fake-embed-1024@OpenAI-API-Compatible"
EXTRA_EMBEDDING_KEY = "fake-embed-2048@OpenAI-API-Compatible"
EXTRA_EMBEDDING_NAME = "fake-embed-2048"

#: Mapa modeli biegu z dodatkowym embeddingiem (jak `FIXTURE_MODELS` w `test_stage_chats.py`).
CHAT_MODEL_MAP = ModelMap(
    {
        CHAT_KEY: MappedModel(name="fake-chat", model_type="chat", dimension=None),
        TONGYI_KEY: MappedModel(name="fake-chat-tongyi", model_type="chat", dimension=None),
        EMBEDDING_KEY: MappedModel(name="fake-embed-1024", model_type="embedding", dimension=1024),
        EXTRA_EMBEDDING_KEY: MappedModel(
            name=EXTRA_EMBEDDING_NAME, model_type="embedding", dimension=2048
        ),
    }
)

NOW_MS = 1759999999000
TARGET_CREATED_AT = 1759306260000


def _by_stage(results: list[StageResult], stage: str) -> StageResult:
    """Wynik etapu o podanej nazwie."""
    return next(result for result in results if result.stage == stage)


def _issue_codes(result: StageResult | StageInventory, code: str) -> list[str]:
    """Id w uwagach o podanym kodzie (`ids` każdej uwagi sklejone w jedną listę)."""
    return [row_id for issue in result.issues if issue.code == code for row_id in issue.ids]


async def _document(sm: async_sessionmaker[AsyncSession], document_id: str) -> dict[str, Any]:
    """`source_type`/`source_ref` wiersza `documents` (brak wiersza → puste wartości)."""
    return await row(
        sm,
        "SELECT source_type, source_ref FROM documents WHERE id = :id",
        {"id": document_id},
    )


def _mapping(source: Source, document_id: str) -> dict[str, Any]:
    """Wiersz `ai_hub_integration_file_mappings` wskazujący dokument (dane źródła testu)."""
    found = source.rows(
        "ai_hub_integration_file_mappings",
        where="ragflow_document_id = %s",
        params=(document_id,),
    )
    assert len(found) == 1, f"oczekiwano jednego mapowania dla {document_id}, jest {len(found)}"
    return found[0]


def _source_ref_of(mapping: dict[str, Any]) -> str:
    """Oczekiwany `source_ref` policzony z wiersza mapowania źródła (CONTRACT §7, format)."""
    return f"{mapping['integration_id']}:{mapping['drive_id']}:{mapping['external_item_id']}"


async def test_mapped_documents_get_source_ref_from_mapping(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(a) Dokument z mapowania: `source_type='sharepoint'`, `source_ref` z wiersza mapowania."""
    await migrate(source, wd_db, run_ctx, only=DOC_STAGES)

    for document_id, item_id in ((DOC_F01, ITEM_F01), (DOC_F02, ITEM_F02)):
        mapping = _mapping(source, document_id)
        assert (mapping["integration_id"], mapping["drive_id"], mapping["external_item_id"]) == (
            INTEGRATION_ID,
            DRIVE_ID,
            item_id,
        )
        assert await _document(wd_db.sm, document_id) == {
            "source_type": "sharepoint",
            "source_ref": _source_ref_of(mapping),
        }


async def test_unmapped_documents_keep_source_type_and_null_ref(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(b) Dokument bez mapowania: `source_ref` NULL, `source_type` jak dotąd (CONTRACT §7)."""
    await migrate(source, wd_db, run_ctx, only=DOC_STAGES)

    assert await _document(wd_db.sm, DOC_F03) == {"source_type": "notion", "source_ref": None}
    assert await _document(wd_db.sm, DOC_F04) == {"source_type": "sharepoint", "source_ref": None}


async def test_second_run_updates_no_document(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(c) Drugi bieg nie zmienia dokumentów (`source_ref` idempotentny)."""
    await migrate(source, wd_db, run_ctx, only=DOC_STAGES)

    documents = _by_stage(await migrate(source, wd_db, run_ctx, only=DOC_STAGES), "documents")
    assert (documents.created, documents.updated) == (0, 0)


async def test_changed_mapping_item_id_updates_document(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(d) Nowy `external_item_id` w mapowaniu źródła → UPDATE dokumentu w kolejnym biegu."""
    await migrate(source, wd_db, run_ctx, only=DOC_STAGES)
    with source_writer(ragflow_src.dsn) as conn, conn.cursor() as cursor:
        cursor.execute(
            "UPDATE `ai_hub_integration_file_mappings` SET `external_item_id` = %s"
            " WHERE `ragflow_document_id` = %s",
            (NEW_ITEM, DOC_F01),
        )

    documents = _by_stage(await migrate(source, wd_db, run_ctx, only=DOC_STAGES), "documents")
    assert documents.updated == 1
    assert await _document(wd_db.sm, DOC_F01) == {
        "source_type": "sharepoint",
        "source_ref": f"{INTEGRATION_ID}:{DRIVE_ID}:{NEW_ITEM}",
    }


def test_null_source_created_at_keeps_existing_target_time() -> None:
    """(e) Źródłowy `created_at` NULL: wiersz celu zachowuje swój czas, nowy dostaje `now_ms`.

    To gałąź CONTRACT §7 pkt 2 sprawdzona bezpośrednio na czystej funkcji etapu — kolumna
    `ai_hub_user_assistant_access.created_at` schematu źródłowego jest `NOT NULL`, więc fixture
    nie pozwala ustawić NULL-a w bazie (patrz test `(f)` niżej).
    """
    source_row: dict[str, Any] = {
        "email": "Admin@RF.Test",
        "dialog_id": D1_ID,
        "created_by": None,
        "created_at": None,
    }
    stored = {("admin@rf.test", D1_ID): {"created_at": TARGET_CREATED_AT}}

    kept, issues = resolve_access([source_row], {D1_ID}, NOW_MS, stored)
    assert kept[0]["created_at"] == TARGET_CREATED_AT
    assert issues == []

    fresh, issues = resolve_access([source_row], {D1_ID}, NOW_MS, {})
    assert fresh[0]["created_at"] == NOW_MS
    assert issues == []


@pytest.mark.skip(
    reason=(
        "schemat źródłowy fixture'u ma `ai_hub_user_assistant_access.created_at` jako"
        " timestamp NOT NULL (schema.sql), więc NULL-a nie da się tam zapisać bez zmiany"
        " schematu, której zakres T6 zabrania; zachowanie sprawdza test (e) na czystej funkcji"
    )
)
async def test_null_source_created_at_keeps_target_row(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(f) Bieg `access` przy źródłowym NULL-u `created_at`: czas celu bez zmian, bez UPDATE."""
    assert source.has_table("ai_hub_user_assistant_access")


async def test_plan_reports_chat_embedding_mismatch(
    source: Source, ragflow_src: SourceDb, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(g) Datasety czatu o różnych `embd_id` → `chat_embedding_mismatch` w `plan` i w `run`."""
    with source_writer(ragflow_src.dsn) as conn, conn.cursor() as cursor:
        cursor.execute(
            "UPDATE `knowledgebase` SET `embd_id` = %s WHERE `id` = %s",
            (EXTRA_EMBEDDING_KEY, DS2_ID),
        )
    ctx = replace(run_ctx, model_map=CHAT_MODEL_MAP)

    inventory = plan_all(source, ctx, only=["chats"])[0]
    mismatch = [issue for issue in inventory.issues if issue.code == "chat_embedding_mismatch"]
    assert len(mismatch) == 1
    assert mismatch[0].severity == "warning"
    assert mismatch[0].ids == [D1_ID]

    runs = await migrate(source, wd_db, ctx, only=CHAT_STAGES)
    assert _issue_codes(_by_stage(runs, "chats"), "chat_embedding_mismatch") == [D1_ID]
    assert await row(
        wd_db.sm,
        "SELECT embedding_model FROM datasets WHERE id = :id",
        {"id": DS2_ID},
    ) == {"embedding_model": EXTRA_EMBEDDING_NAME}


async def test_fixture_without_embedding_mismatch_reports_none(
    source: Source, wd_db: WdDb, run_ctx: RunContext
) -> None:
    """(h) Nietknięty fixture: ani `plan`, ani `run` nie zgłaszają `chat_embedding_mismatch`."""
    inventory: StageInventory = plan_all(source, run_ctx, only=["chats"])[0]
    assert _issue_codes(inventory, "chat_embedding_mismatch") == []

    runs = await migrate(source, wd_db, run_ctx, only=["users", "models", "datasets", "chats"])
    assert _issue_codes(_by_stage(runs, "chats"), "chat_embedding_mismatch") == []
    assert await row(
        wd_db.sm,
        "SELECT embedding_model FROM datasets WHERE id = :id",
        {"id": DS2_ID},
    ) == {"embedding_model": "fake-embed-1024"}
