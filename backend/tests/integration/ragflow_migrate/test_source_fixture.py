"""Harness źródła fixture'u: liczniki, tabele hub-compat, tylko-odczyt, mapa modeli (T3, p. 5)."""

import hashlib
from pathlib import Path

import pymysql
import pytest
from sqlalchemy import inspect

from app.tools.ragflow_migrate.model_map import MappedModel, ModelMap
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import RunContext
from tests.integration.ragflow_migrate.conftest import FIXTURES_DIR, WdDb

pytestmark = pytest.mark.db

#: Wymiar modelu `fake-embed-1024` w źródle fixture'u (CONTRACT §5).
FAKE_EMBED_DIM = 1024

#: Liczby wierszy źródła po rozszerzeniu E4-6b1 (CONTRACT §10).
EXPECTED_FILE_ROWS = 10
EXPECTED_FILE2DOCUMENT_ROWS = 4
EXPECTED_DOCUMENT_ROWS = 6


def test_source_counts_match_expectations(source: Source, expectations: dict[str, object]) -> None:
    """Liczby wierszy w źródle = liczby z `expectations.json` i CONTRACT §10."""
    users = expectations["users"]
    tokens = expectations["tokens"]
    assert isinstance(users, dict)
    assert isinstance(tokens, list)
    assert source.count("user") == len(users)
    assert source.count("api_token") == len(tokens)
    assert source.count("file") == EXPECTED_FILE_ROWS
    assert source.count("file2document") == EXPECTED_FILE2DOCUMENT_ROWS
    assert source.count("document") == EXPECTED_DOCUMENT_ROWS


def test_fixture_blobs_match_expectations(expectations: dict[str, object]) -> None:
    """Bloby z `expectations.json` zgadzają się z dyskiem; brak plików spoza listy (§10)."""
    blobs = expectations["blobs"]
    assert isinstance(blobs, list)
    files_root = FIXTURES_DIR / "files"
    expected: set[Path] = set()
    for blob in blobs:
        assert isinstance(blob, dict)
        path = files_root / str(blob["bucket"]) / str(blob["location"])
        assert path.is_file()
        assert path.stat().st_size == blob["size"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == blob["sha256"]
        expected.add(path)
    on_disk = {path for path in files_root.rglob("*") if path.is_file()}
    assert on_disk == expected


def test_source_has_hub_compat_table(source: Source) -> None:
    """Tabele `ai_hub_*` (hub-compat) są w źródle fixture'u."""
    assert source.has_table("ai_hub_user_assistant_access")
    assert source.has_table("ai_hub_sharepoint_integrations")


def test_source_refuses_writes(source: Source) -> None:
    """Sesja źródła jest tylko-do-odczytu — INSERT i DELETE padają na poziomie serwera."""
    with pytest.raises(pymysql.err.OperationalError), source._conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO `user` (`id`, `email`) VALUES ('ffffffffffffffffffffffffffffffff',"
            " 'harness@rf.test')"
        )
    with pytest.raises(pymysql.err.OperationalError), source._conn.cursor() as cursor:
        cursor.execute("DELETE FROM `api_token`")
    # po odmowie połączenie dalej tylko czyta
    assert source.count("user") > 0


def test_model_map_fixture_loads(model_map_path: Path) -> None:
    """`model-map.yaml` fixture'u ładuje się i zwraca wpisy z briefu T3, p. 4."""
    model_map = ModelMap.load(model_map_path)
    assert model_map.get("fake-chat@Tongyi-Qianwen") == MappedModel(
        name="fake-chat-tongyi", model_type="chat", dimension=None
    )
    assert model_map.get("fake-chat@OpenAI-API-Compatible") == MappedModel(
        name="fake-chat", model_type="chat", dimension=None
    )
    assert model_map.get("fake-embed-1024@OpenAI-API-Compatible") == MappedModel(
        name="fake-embed-1024", model_type=None, dimension=1024
    )


async def test_wd_db_is_migrated(wd_db: WdDb) -> None:
    """`wd_db` to baza WD po migracjach — etapy T4-T7 piszą do `users`, `models` i `datasets`."""
    async with wd_db.engine.connect() as conn:
        names = await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))
    assert {"users", "api_keys", "models", "datasets", "documents"} <= names


def test_run_ctx_uses_migrated_wd_db(run_ctx: RunContext, wd_db: WdDb) -> None:
    """`run_ctx` stoi na zmigrowanej bazie WD, z mapą fixture'u i pustym `shared`."""
    assert run_ctx.settings.db_name == wd_db.settings.db_name
    assert run_ctx.shared == {}
    mapped = run_ctx.model_map.get("fake-embed-1024@OpenAI-API-Compatible")
    assert mapped is not None
    assert mapped.dimension == FAKE_EMBED_DIM
