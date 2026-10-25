"""Harness testów migracji RAGFlow→WD: źródło `ragflow_src`, `source`, `wd_db`, `run_ctx`
(brief T3, kontrakt §5 i §6 WP E4-6a)."""

import json
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit

import pymysql
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from alembic import command
from app.core.config import Settings
from app.core.ids import UuidV7Generator
from app.core.timeutil import SystemClock
from app.db.engine import make_engine, make_sessionmaker
from app.storage.filesystem import FilesystemStorage
from app.tools.ragflow_migrate.model_map import ModelMap
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import RunContext
from tests.fixtures.ragflow_v024.normalize import normalize
from tests.integration.db.helpers import alembic_cfg, worker_db_name

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "ragflow_v024"


@dataclass(frozen=True)
class SourceDb:
    """Źródło testowe: DSN do `Source.connect` i nazwa bazy źródłowej."""

    dsn: str
    name: str


@dataclass(frozen=True)
class WdDb:
    """Baza docelowa testu po migracjach: ustawienia, silnik i fabryka sesji."""

    settings: Settings
    engine: AsyncEngine
    sm: async_sessionmaker[AsyncSession]


def _root_connection() -> pymysql.connections.Connection:
    """Połączenie root do zakładania i kasowania baz testowych.

    Wzór: `_root_connection` z `tests/integration/conftest.py`.
    """
    return pymysql.connect(
        host=os.environ["WD_DB_HOST"],
        port=int(os.environ["WD_DB_PORT"]),
        user="root",
        password=os.environ.get("WD_TEST_DB_ROOT_PASSWORD", "root-test"),
        autocommit=True,
    )


def _statements(sql: str) -> list[str]:
    """Dzieli zrzut na instrukcje po `;` na końcu linii.

    Fixture nie ma `;` wewnątrz wartości (sprawdzone skanem z uwzględnieniem apostrofów), więc
    podział tekstowy wystarcza; nagłówek `--` w pierwszym kawałku MySQL/MariaDB parsuje sam.
    """
    return [part.strip() for part in sql.split(";\n") if part.strip()]


def _execute_script(conn: pymysql.connections.Connection, sql: str) -> None:
    """Wykonuje zrzut instrukcja po instrukcji (jedna instrukcja = jeden `execute`)."""
    with conn.cursor() as cursor:
        for statement in _statements(sql):
            cursor.execute(statement)


def _source_dsn(settings: Settings, name: str) -> str:
    """DSN źródła z ustawień testu (`mysql://user:hasło@host:port/nazwa`; haseł nie ma w kodzie)."""
    user = quote(settings.db_user, safe="")
    password = quote(settings.db_password.get_secret_value(), safe="")
    return f"mysql://{user}:{password}@{settings.db_host}:{settings.db_port}/{name}"


def _fixture_sql(filename: str) -> str:
    """Zawartość pliku fixture'u po normalizacji MySQL 8 → MariaDB."""
    return normalize((FIXTURES_DIR / filename).read_text(encoding="utf-8"))


@contextmanager
def source_writer(dsn: str) -> Iterator[pymysql.connections.Connection]:
    """Zapisywalne połączenie ze źródłem (sesja `Source` jest READ ONLY) — modyfikacje testu.

    Wzór: `_source_writer` z `test_stage_datasets.py`; publiczne, bo korzystają z niego testy
    kolejnych zadań (m.in. `test_null_times.py`).
    """
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


@pytest.fixture
def ragflow_src() -> Iterator[SourceDb]:
    """Baza `rf_src_<8 hex>` (pod xdist `rf_src_<worker>_<8 hex>`) z `schema.sql` + `data.sql`;
    DROP po teście.

    Zakłada ją root (jak `fresh_db`), nadaje prawa użytkownikowi `wawelsky` i ładuje fixture.
    """
    name = worker_db_name("rf_src")
    root = _root_connection()
    try:
        with root.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            cursor.execute(f"GRANT ALL PRIVILEGES ON `{name}`.* TO 'wawelsky'@'%'")
    finally:
        root.close()

    settings = Settings(env="test", db_name=name)
    loader = pymysql.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password.get_secret_value(),
        database=name,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        _execute_script(loader, _fixture_sql("schema.sql"))
        _execute_script(loader, _fixture_sql("data.sql"))
    finally:
        loader.close()

    yield SourceDb(dsn=_source_dsn(settings, name), name=name)

    root = _root_connection()
    try:
        with root.cursor() as cursor:
            cursor.execute(f"DROP DATABASE IF EXISTS `{name}`")
    finally:
        root.close()


@pytest.fixture
def source(ragflow_src: SourceDb) -> Iterator[Source]:
    """Połączenie tylko-do-odczytu ze źródłem fixture'u; zamykane po teście."""
    src = Source.connect(ragflow_src.dsn)
    yield src
    src.close()


@pytest.fixture
def migrated_wd_db(fresh_db: Settings) -> Settings:
    """Świeża baza WD po migracji do head (wzór: tests/integration/datasets/conftest.py)."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    return fresh_db


@pytest.fixture
async def wd_db(migrated_wd_db: Settings) -> AsyncIterator[WdDb]:
    """Zmigrowana baza WD z silnikiem i fabryką sesji; silnik dispose po teście."""
    engine = make_engine(migrated_wd_db)
    yield WdDb(settings=migrated_wd_db, engine=engine, sm=make_sessionmaker(engine))
    await engine.dispose()


@pytest.fixture
def expectations() -> dict[str, Any]:
    """Zawartość `expectations.json` — znane hasła i tokeny FIKCYJNE (wyrocznia testów etapów)."""
    return json.loads((FIXTURES_DIR / "expectations.json").read_text(encoding="utf-8"))


@pytest.fixture
def model_map_path() -> Path:
    """Ścieżka mapy modeli fixture'u (`model-map.yaml`, kontrakt §2)."""
    return FIXTURES_DIR / "model-map.yaml"


@pytest.fixture
def run_ctx(wd_db: WdDb, tmp_path: Path, expectations: dict[str, Any]) -> RunContext:
    """Kontekst biegu migracji na bazie testowej; `shared` puste (etapy wypełnią je same).

    Klucz sekretów SharePoint bierzemy z `expectations.json` (fixture, nie sekret) — etap
    `integrations` odszyfrowuje nim `client_secret_encrypted` źródła (kontrakt §9).
    """
    return RunContext(
        model_map=ModelMap.load(FIXTURES_DIR / "model-map.yaml"),
        settings=wd_db.settings,
        clock=SystemClock(),
        id_gen=UuidV7Generator(),
        shared={},
        storage=FilesystemStorage(tmp_path / "wd-storage"),
        src_files_dir=FIXTURES_DIR / "files",
        src_sp_crypto_key=SecretStr(expectations["sharepoint"]["src_crypto_key"]),
    )
