"""Testy migracji 0001_initial, 0002_hub_compat_access_audit, 0003_integrations,
0004_provider_instances, 0005_api_key_expiry i 0006_searches na świeżej bazie MariaDB
(brief T2 kontrakt C9/C10;
brief E2-4/T1 kontrakt C1; brief E4-1/T1 kontrakt K12 §1; brief E3-6b/T1 kontrakt K13 §1;
brief E2-H1/T1 kontrakt K14 §1; brief E4-4a/T1 kontrakt K15 §1).

Wszystkie testy synchroniczne (`def`) — env.py robi `asyncio.run` (kontrakt C7/C12).
"""

import json
import os
import subprocess
import sys

import pymysql
import pytest

from alembic import command
from app.core.config import Settings
from app.db.schema import SCHEMA_HEAD
from tests.integration.db.helpers import (
    BACKEND_DIR,
    HUB_COMPAT_TABLES,
    INTEGRATION_TABLES,
    K2_TABLES,
    alembic_cfg,
    table_names,
)

pytestmark = pytest.mark.db

# Wartości mixin czasu dla wierszy testowych (create_time, create_date, update_time, update_date).
TIME = "2026-09-27 00:00:00.000"
TIME_COLS = (1, TIME, 1, TIME)

FULLTEXT_INDEXES = {"ft_content", "ft_stem", "ft_title", "ft_important", "ft_question"}

# Tabele migracji 0004 (instancje dostawców, kontrakt K13 §1) — trzymane lokalnie, bo lista
# tabel migracji 0003 w `helpers.py` jest zamknięta dla tamtego WP.
PROVIDER_TABLES = ("provider_instances",)

# Tabele migracji 0006 (wyszukiwarka, kontrakt K15 §1).
SEARCH_TABLES = ("searches", "search_datasets")

# Tabela migracji 0007 (limiter logowania, CONTRACT E5-2a §4).
LOGIN_TABLES = ("login_attempts",)

# Tabele migracji 0008 (agentowy schemat, K2 §6, WP E6-3f).
AGENT_TABLES = ("agents", "agent_sessions", "web_search_providers")

# Tabele migracji 0009 (sesje importu KB + ustawienia instancji, K19 §4 / CONTRACT E7-1f §5).
IMPORT_TABLES = ("dataset_imports", "wd_settings")

# Tabela migracji 0010 (spisy treści dokumentów, K21 §1).
PROFILE_TABLES = ("document_profiles",)

# Wszystkie tabele po `upgrade head`: K2 + hub-compat + integracje + instancje dostawców
# + wyszukiwarka + limiter logowania + schemat agenta + import KB + spisy treści + alembic_version
# (K12 §1, K13 §1, K15 §1, E5-2a §4, K2 §6, K19 §4, K21 §1).
ALL_TABLES = (
    set(K2_TABLES)
    | set(HUB_COMPAT_TABLES)
    | set(INTEGRATION_TABLES)
    | set(PROVIDER_TABLES)
    | set(SEARCH_TABLES)
    | set(LOGIN_TABLES)
    | set(AGENT_TABLES)
    | set(IMPORT_TABLES)
    | set(PROFILE_TABLES)
    | {"alembic_version"}
)


def _connect(settings: Settings) -> pymysql.Connection:
    """Połączenie do bazy testowej danymi z `settings`."""
    return pymysql.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password.get_secret_value(),
        database=settings.db_name,
    )


def _fetchall(settings: Settings, sql: str, args: tuple = ()) -> list[tuple]:
    """Wykonuje zapytanie na świeżym połączeniu i zwraca wszystkie wiersze."""
    connection = _connect(settings)
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, args)
            return list(cursor.fetchall())
    finally:
        connection.close()


def _run_migrate(env_overrides: dict[str, str], fresh_db: Settings) -> subprocess.CompletedProcess:
    """Uruchamia `python -m app.tools.migrate` na bazie testowej `fresh_db`.

    Stałe argumenty, bez shell (ruff S603 nie flaguje listy z `sys.executable`).
    """
    return subprocess.run(
        [sys.executable, "-m", "app.tools.migrate"],
        cwd=BACKEND_DIR,
        env={**os.environ, "WD_ENV": "test", "WD_DB_NAME": fresh_db.db_name, **env_overrides},
        check=False,
        capture_output=True,
        timeout=120,
    )


def test_upgrade_creates_k2_tables(fresh_db: Settings) -> None:
    command.upgrade(alembic_cfg(fresh_db), "head")
    assert table_names(fresh_db) == ALL_TABLES
    rows = _fetchall(fresh_db, "SELECT version_num FROM alembic_version")
    assert rows == [(SCHEMA_HEAD,)]


def test_up_down_up(fresh_db: Settings) -> None:
    cfg = alembic_cfg(fresh_db)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    after_down = table_names(fresh_db)
    assert after_down <= {"alembic_version"}
    assert not set(K2_TABLES) & after_down
    assert not set(HUB_COMPAT_TABLES) & after_down
    assert not set(INTEGRATION_TABLES) & after_down
    assert not set(SEARCH_TABLES) & after_down
    command.upgrade(cfg, "head")
    assert table_names(fresh_db) == ALL_TABLES


def test_up_down_up_0002(fresh_db: Settings) -> None:
    """head → downgrade 0001 (znikają tabele hub-compat, K2 zostaje) → head (wracają)."""
    cfg = alembic_cfg(fresh_db)
    command.upgrade(cfg, "head")
    assert table_names(fresh_db) == ALL_TABLES
    command.downgrade(cfg, "0001")
    after_down = table_names(fresh_db)
    assert after_down == set(K2_TABLES) | {"alembic_version"}
    assert not set(HUB_COMPAT_TABLES) & after_down
    assert _fetchall(fresh_db, "SELECT version_num FROM alembic_version") == [("0001",)]
    command.upgrade(cfg, "head")
    assert table_names(fresh_db) == ALL_TABLES
    assert _fetchall(fresh_db, "SELECT version_num FROM alembic_version") == [(SCHEMA_HEAD,)]


def test_up_down_up_0003(fresh_db: Settings) -> None:
    """head → downgrade 0002 (znikają tabele integracji, K2 i hub-compat zostają) → head."""
    cfg = alembic_cfg(fresh_db)
    command.upgrade(cfg, "head")
    assert table_names(fresh_db) == ALL_TABLES
    command.downgrade(cfg, "0002")
    after_down = table_names(fresh_db)
    assert after_down == set(K2_TABLES) | set(HUB_COMPAT_TABLES) | {"alembic_version"}
    assert not set(INTEGRATION_TABLES) & after_down
    assert _fetchall(fresh_db, "SELECT version_num FROM alembic_version") == [("0002",)]
    command.upgrade(cfg, "head")
    assert table_names(fresh_db) == ALL_TABLES
    assert _fetchall(fresh_db, "SELECT version_num FROM alembic_version") == [(SCHEMA_HEAD,)]


def _column_names(settings: Settings, table: str) -> set[str]:
    """Nazwy kolumn tabeli w bazie testowej (K13 §1)."""
    rows = _fetchall(
        settings,
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS"
        " WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
        (settings.db_name, table),
    )
    return {str(row[0]) for row in rows}


def test_up_down_up_0004(fresh_db: Settings) -> None:
    """head → downgrade 0003 (znika tabela instancji i `models.instance_id`) → head (wracają)."""
    cfg = alembic_cfg(fresh_db)
    command.upgrade(cfg, "head")
    assert table_names(fresh_db) == ALL_TABLES
    assert "instance_id" in _column_names(fresh_db, "models")
    command.downgrade(cfg, "0003")
    after_down = table_names(fresh_db)
    assert after_down == (
        set(K2_TABLES) | set(HUB_COMPAT_TABLES) | set(INTEGRATION_TABLES) | {"alembic_version"}
    )
    assert not set(PROVIDER_TABLES) & after_down
    assert "instance_id" not in _column_names(fresh_db, "models")
    assert _fetchall(fresh_db, "SELECT version_num FROM alembic_version") == [("0003",)]
    command.upgrade(cfg, "head")
    assert table_names(fresh_db) == ALL_TABLES
    assert "instance_id" in _column_names(fresh_db, "models")
    assert _fetchall(fresh_db, "SELECT version_num FROM alembic_version") == [(SCHEMA_HEAD,)]


def _column_meta(settings: Settings, table: str, column: str) -> tuple[int, str, str]:
    """(ORDINAL_POSITION, DATA_TYPE, IS_NULLABLE) kolumny — kolejność i kształt wg K14 §1."""
    rows = _fetchall(
        settings,
        "SELECT ORDINAL_POSITION, DATA_TYPE, IS_NULLABLE FROM information_schema.COLUMNS"
        " WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s",
        (settings.db_name, table, column),
    )
    return (int(rows[0][0]), str(rows[0][1]), str(rows[0][2]))


def _insert_api_key_row(settings: Settings) -> None:
    """Wiersz `api_keys` (z właścicielem — FK) sprzed migracji 0005 (K14 §1)."""
    connection = _connect(settings)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO users (id, email, nickname, create_time, create_date,"
                " update_time, update_date) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                ("u" * 32, "k14@x.pl", "K14", *TIME_COLS),
            )
            cursor.execute(
                "INSERT INTO api_keys (id, user_id, token_hash, token_enc, prefix,"
                " create_time, create_date, update_time, update_date)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                ("k" * 32, "u" * 32, "h" * 64, b"x", "ragflow-0000000000", *TIME_COLS),
            )
        connection.commit()
    finally:
        connection.close()


def test_up_down_up_0005(fresh_db: Settings) -> None:
    """`api_keys.expires_at` BIGINT NULL po `last_used_at`; downgrade 0004 usuwa kolumnę.

    Wiersz istniejący przed migracją ma po upgrade `expires_at IS NULL` (K14 §1).
    """
    cfg = alembic_cfg(fresh_db)
    command.upgrade(cfg, "0004")
    _insert_api_key_row(fresh_db)
    command.upgrade(cfg, "head")
    assert table_names(fresh_db) == ALL_TABLES
    assert _fetchall(fresh_db, "SELECT version_num FROM alembic_version") == [(SCHEMA_HEAD,)]
    position, data_type, nullable = _column_meta(fresh_db, "api_keys", "expires_at")
    assert (data_type, nullable) == ("bigint", "YES")
    assert position == _column_meta(fresh_db, "api_keys", "last_used_at")[0] + 1
    assert _fetchall(fresh_db, "SELECT expires_at FROM api_keys") == [(None,)]
    command.downgrade(cfg, "0004")
    assert "expires_at" not in _column_names(fresh_db, "api_keys")
    assert _fetchall(fresh_db, "SELECT version_num FROM alembic_version") == [("0004",)]
    command.upgrade(cfg, "head")
    assert "expires_at" in _column_names(fresh_db, "api_keys")
    assert _fetchall(fresh_db, "SELECT expires_at FROM api_keys") == [(None,)]
    assert _fetchall(fresh_db, "SELECT version_num FROM alembic_version") == [(SCHEMA_HEAD,)]


USER_ID = "u" * 32
DATASET_A = "d" * 32
DATASET_B = "e" * 32
SEARCH_ID = "s" * 32


def _seed_search_graph(settings: Settings) -> None:
    """users + dwa datasety + wyszukiwarka z dwoma wiązaniami (K15 §1)."""
    connection = _connect(settings)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO users (id, email, nickname, create_time, create_date,"
                " update_time, update_date) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (USER_ID, "k15@x.pl", "K15", *TIME_COLS),
            )
            for dataset_id in (DATASET_A, DATASET_B):
                cursor.execute(
                    "INSERT INTO datasets (id, tenant_id, created_by, name, embedding_model,"
                    " embedding_dim, create_time, create_date, update_time, update_date)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        dataset_id,
                        USER_ID,
                        USER_ID,
                        f"Korpus {dataset_id[0]}",
                        "openai/text-embedding-3-large",
                        3072,
                        *TIME_COLS,
                    ),
                )
            cursor.execute(
                "INSERT INTO searches (id, tenant_id, created_by, name, description, avatar,"
                " search_config, status, create_time, create_date, update_time, update_date)"
                " VALUES (%s, %s, %s, %s, NULL, NULL, '{}', '1', %s, %s, %s, %s)",
                (SEARCH_ID, USER_ID, USER_ID, "K15 search", *TIME_COLS),
            )
            for ordinal, dataset_id in enumerate((DATASET_A, DATASET_B)):
                cursor.execute(
                    "INSERT INTO search_datasets (search_id, dataset_id, ordinal)"
                    " VALUES (%s, %s, %s)",
                    (SEARCH_ID, dataset_id, ordinal),
                )
        connection.commit()
    finally:
        connection.close()


def test_up_down_up_0006(fresh_db: Settings) -> None:
    """Tabele `searches`/`search_datasets` (K15 §1) i kaskady FK po stronie wiązań.

    Po `downgrade 0005` obu tabel nie ma; ponowny upgrade je przywraca.
    """
    cfg = alembic_cfg(fresh_db)
    command.upgrade(cfg, "head")
    assert table_names(fresh_db) == ALL_TABLES
    assert _fetchall(fresh_db, "SELECT version_num FROM alembic_version") == [(SCHEMA_HEAD,)]
    _seed_search_graph(fresh_db)
    assert _fetchall(fresh_db, "SELECT COUNT(*) FROM search_datasets") == [(2,)]
    connection = _connect(fresh_db)
    try:
        with connection.cursor() as cursor:
            # Usunięcie datasetu kasuje TYLKO jego wiersz wiązania (K15 §1).
            cursor.execute("DELETE FROM datasets WHERE id = %s", (DATASET_A,))
        connection.commit()
    finally:
        connection.close()
    assert _fetchall(fresh_db, "SELECT dataset_id FROM search_datasets") == [(DATASET_B,)]
    connection = _connect(fresh_db)
    try:
        with connection.cursor() as cursor:
            # Usunięcie wyszukiwarki kasuje wszystkie jej wiązania (K15 §1).
            cursor.execute("DELETE FROM searches WHERE id = %s", (SEARCH_ID,))
        connection.commit()
    finally:
        connection.close()
    assert _fetchall(fresh_db, "SELECT COUNT(*) FROM search_datasets") == [(0,)]
    command.downgrade(cfg, "0005")
    after_down = table_names(fresh_db)
    assert not set(SEARCH_TABLES) & after_down
    assert _fetchall(fresh_db, "SELECT version_num FROM alembic_version") == [("0005",)]
    command.upgrade(cfg, "head")
    assert set(SEARCH_TABLES) <= table_names(fresh_db)
    assert _fetchall(fresh_db, "SELECT version_num FROM alembic_version") == [(SCHEMA_HEAD,)]


def test_up_down_up_0007(fresh_db: Settings) -> None:
    """Tabela `login_attempts` (CONTRACT E5-2a §4): po upgrade jest, po `downgrade 0006` znika."""
    cfg = alembic_cfg(fresh_db)
    command.upgrade(cfg, "head")
    assert table_names(fresh_db) == ALL_TABLES
    assert _fetchall(fresh_db, "SELECT version_num FROM alembic_version") == [(SCHEMA_HEAD,)]
    assert set(LOGIN_TABLES) <= table_names(fresh_db)
    command.downgrade(cfg, "0006")
    after_down = table_names(fresh_db)
    assert not set(LOGIN_TABLES) & after_down
    assert _fetchall(fresh_db, "SELECT version_num FROM alembic_version") == [("0006",)]
    command.upgrade(cfg, "head")
    assert set(LOGIN_TABLES) <= table_names(fresh_db)
    assert _fetchall(fresh_db, "SELECT version_num FROM alembic_version") == [(SCHEMA_HEAD,)]


def test_provider_instances_constraints(fresh_db: Settings) -> None:
    """FK-i instancji (K13 §1) i unikat nazwy per dostawca bez rozróżniania wielkości liter."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    fk_rows = _fetchall(
        fresh_db,
        "SELECT CONSTRAINT_NAME, REFERENCED_TABLE_NAME, DELETE_RULE"
        " FROM information_schema.REFERENTIAL_CONSTRAINTS"
        " WHERE CONSTRAINT_SCHEMA = %s AND TABLE_NAME = %s",
        (fresh_db.db_name, "provider_instances"),
    )
    assert {tuple(row) for row in fk_rows} == {
        ("fk_provider_instances_created_by", "users", "SET NULL"),
    }
    models_fk = _fetchall(
        fresh_db,
        "SELECT CONSTRAINT_NAME, REFERENCED_TABLE_NAME, DELETE_RULE"
        " FROM information_schema.REFERENTIAL_CONSTRAINTS"
        " WHERE CONSTRAINT_SCHEMA = %s AND CONSTRAINT_NAME = 'fk_models_instance'",
        (fresh_db.db_name,),
    )
    assert models_fk == [("fk_models_instance", "provider_instances", "RESTRICT")]
    connection = _connect(fresh_db)
    try:
        with connection.cursor() as cursor:
            insert = (
                "INSERT INTO provider_instances (id, provider, name, base_url, api_key_enc,"
                " created_by, create_time, create_date, update_time, update_date)"
                " VALUES (%s, 'litellm', %s, 'http://x/v1', NULL, NULL, %s, %s, %s, %s)"
            )
            cursor.execute(insert, ("i" * 32, "Produkcja", *TIME_COLS))
            # Kolacja uca1400_ai_ci: „Produkcja" i „PRODUKCJA" to ta sama nazwa (K13 §1).
            with pytest.raises(pymysql.err.IntegrityError) as dup_error:
                cursor.execute(insert, ("j" * 32, "PRODUKCJA", *TIME_COLS))
            assert dup_error.value.args[0] == ER_DUP_ENTRY
    finally:
        connection.close()


def test_provider_instance_delete_restricted_by_model(fresh_db: Settings) -> None:
    """FK `models.instance_id` RESTRICT: instancji z modelem nie da się usunąć (K13 §1)."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    connection = _connect(fresh_db)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO provider_instances (id, provider, name, base_url, api_key_enc,"
                " created_by, create_time, create_date, update_time, update_date)"
                " VALUES (%s, 'litellm', 'Produkcja', 'http://x/v1', NULL, NULL, %s, %s, %s, %s)",
                ("i" * 32, *TIME_COLS),
            )
            cursor.execute(
                "INSERT INTO models (id, name, model_type, provider, instance_id, is_default,"
                " create_time, create_date, update_time, update_date)"
                " VALUES (%s, 'm-1', 'chat', 'litellm', %s, 0, %s, %s, %s, %s)",
                ("m" * 32, "i" * 32, *TIME_COLS),
            )
            with pytest.raises(pymysql.err.IntegrityError):
                cursor.execute("DELETE FROM provider_instances WHERE id = %s", ("i" * 32,))
            # Po usunięciu modelu instancja jest znowu usuwalna — dowód, że blokował ją FK.
            cursor.execute("DELETE FROM models WHERE id = %s", ("m" * 32,))
            cursor.execute("DELETE FROM provider_instances WHERE id = %s", ("i" * 32,))
        connection.commit()
    finally:
        connection.close()
    assert _fetchall(fresh_db, "SELECT COUNT(*) FROM provider_instances") == [(0,)]


# Kody błędów MariaDB: 4025 = CHECK constraint, 1062 = duplikat klucza (K12 §1).
ER_CONSTRAINT_FAILED = 4025
ER_DUP_ENTRY = 1062

# INSERT integracji z parametrami: dataset_id, owner_id, scan_interval_seconds (K12 §1).
_INSERT_INTEGRATION = (
    "INSERT INTO integrations (type, name, dataset_id, owner_id, config, ignored_extensions,"
    " scan_interval_seconds, created_at, updated_at)"
    " VALUES ('sharepoint', 'Int test', %s, %s, '{}', '[]', %s, 1, 1)"
)


def _seed_user_dataset(settings: Settings) -> tuple[str, str]:
    """Wstawia users + datasets (FK integracji) — zwraca (user_id, dataset_id) (K12 §1)."""
    user_id = "u" * 32
    dataset_id = "d" * 32
    connection = _connect(settings)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO users (id, email, nickname, create_time, create_date,"
                " update_time, update_date) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (user_id, "seed@example.com", "seed", *TIME_COLS),
            )
            cursor.execute(
                "INSERT INTO datasets (id, tenant_id, created_by, name, embedding_model,"
                " embedding_dim, create_time, create_date, update_time, update_date)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    dataset_id,
                    user_id,
                    user_id,
                    "Projekt",
                    "openai/text-embedding-3-large",
                    3072,
                    *TIME_COLS,
                ),
            )
        connection.commit()
    finally:
        connection.close()
    return user_id, dataset_id


def test_integrations_constraints(fresh_db: Settings) -> None:
    """CHECK scan_interval >= 30, unikat dataset_id, kaskada z datasetów i historia bez FK."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    owner_id, dataset_id = _seed_user_dataset(fresh_db)
    connection = _connect(fresh_db)
    try:
        with connection.cursor() as cursor:
            with pytest.raises(pymysql.err.OperationalError) as check_error:
                cursor.execute(_INSERT_INTEGRATION, (dataset_id, owner_id, 10))
            assert check_error.value.args[0] == ER_CONSTRAINT_FAILED
            assert "ck_integrations_scan_interval" in check_error.value.args[1]
            cursor.execute(_INSERT_INTEGRATION, (dataset_id, owner_id, 30))
            integration_id = int(cursor.lastrowid)
            with pytest.raises(pymysql.err.IntegrityError) as dup_error:
                cursor.execute(_INSERT_INTEGRATION, (dataset_id, owner_id, 30))
            assert dup_error.value.args[0] == ER_DUP_ENTRY
            cursor.execute(
                "INSERT INTO integration_sharepoint (integration_id, tenant_id, client_id,"
                " site_url, site_id, site_display_name, excluded_library_names)"
                " VALUES (%s, %s, %s, %s, NULL, NULL, %s)",
                (integration_id, "tenant", "client", "https://example.test", "[]"),
            )
            cursor.execute(
                "INSERT INTO integration_containers (integration_id, container_id, name,"
                " delta_cursor, last_sync_at, discovered_at)"
                " VALUES (%s, %s, %s, NULL, NULL, %s)",
                (integration_id, "container-1", "Dokumenty", 1),
            )
            cursor.execute(
                "INSERT INTO integration_item_mappings (integration_id, container_id, item_id,"
                " document_id, content_tag, meta_tag, name, path, web_url, last_status,"
                " last_error, updated_at)"
                " VALUES (%s, %s, %s, NULL, NULL, NULL, %s, %s, NULL, %s, NULL, %s)",
                (integration_id, "container-1", "item-1", "a.txt", "/a.txt", "ok", 1),
            )
            cursor.execute(
                "INSERT INTO integration_sync_runs (integration_id, integration_type,"
                " run_trigger, started_at, finished_at, status, added, updated, renamed,"
                " deleted, failed, skipped)"
                " VALUES (%s, %s, %s, %s, NULL, %s, 0, 0, 0, 0, 0, 0)",
                (integration_id, "sharepoint", "manual", 1, "success"),
            )
            run_id = int(cursor.lastrowid)
            cursor.execute(
                "INSERT INTO integration_sync_events (run_id, integration_id, integration_type,"
                " level, message, file_path, container_id, container_name, created_at)"
                " VALUES (%s, %s, %s, %s, %s, NULL, %s, %s, %s)",
                (run_id, integration_id, "sharepoint", "info", "ok", "container-1", "Dokumenty", 1),
            )
        connection.commit()
    finally:
        connection.close()
    connection = _connect(fresh_db)
    try:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM datasets WHERE id = %s", (dataset_id,))
        connection.commit()
    finally:
        connection.close()
    # Kaskada po integrations kasuje typ i dzieci; historia (bez FK) zostaje (K12 §1).
    empty = (
        "integrations",
        "integration_sharepoint",
        "integration_containers",
        "integration_item_mappings",
    )
    for table in empty:
        # Nazwa tabeli pochodzi ze stałej krotki `empty`, nie z wejścia — bez ryzyka iniekcji.
        rows = _fetchall(fresh_db, f"SELECT COUNT(*) FROM {table}")  # noqa: S608
        assert rows == [(0,)], table
    assert _fetchall(fresh_db, "SELECT COUNT(*) FROM integration_sync_runs") == [(1,)]
    assert _fetchall(fresh_db, "SELECT COUNT(*) FROM integration_sync_events") == [(1,)]


def test_lock_update_is_atomic_sql(fresh_db: Settings) -> None:
    """`UPDATE ... WHERE id AND is_running=0` daje rowcount 1 tylko raz (K12 §1)."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    owner_id, dataset_id = _seed_user_dataset(fresh_db)
    connection = _connect(fresh_db)
    try:
        with connection.cursor() as cursor:
            cursor.execute(_INSERT_INTEGRATION, (dataset_id, owner_id, 300))
            integration_id = int(cursor.lastrowid)
            lock_sql = "UPDATE integrations SET is_running=1 WHERE id=%s AND is_running=0"
            cursor.execute(lock_sql, (integration_id,))
            assert cursor.rowcount == 1
            cursor.execute(lock_sql, (integration_id,))
            assert cursor.rowcount == 0
        connection.commit()
    finally:
        connection.close()


def _insert_chat_with_grant(settings: Settings) -> str:
    """Wstawia users + chats + assistant_access (FK) — zwraca chat_id (kontrakt C1)."""
    user_id = "u" * 32
    chat_id = "c" * 32
    connection = _connect(settings)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO users (id, email, nickname, create_time, create_date,"
                " update_time, update_date) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (user_id, "seed@example.com", "seed", *TIME_COLS),
            )
            cursor.execute(
                "INSERT INTO chats (id, tenant_id, created_by, name, llm_id, prompt_config,"
                " create_time, create_date, update_time, update_date)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (chat_id, user_id, user_id, "Czat grantu", "fake-chat", "{}", *TIME_COLS),
            )
            cursor.execute(
                "INSERT INTO assistant_access (email, chat_id, created_by, created_at)"
                " VALUES (%s, %s, %s, %s)",
                ("grant@example.com", chat_id, None, 1),
            )
        connection.commit()
    finally:
        connection.close()
    return chat_id


def test_assistant_access_structure(fresh_db: Settings) -> None:
    """PK (email, chat_id) i FK fk_assistant_access_chat → chats ON DELETE CASCADE (C1)."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    pk = _fetchall(
        fresh_db,
        "SELECT COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA = %s"
        " AND TABLE_NAME = 'assistant_access' AND CONSTRAINT_NAME = 'PRIMARY'"
        " ORDER BY ORDINAL_POSITION",
        (fresh_db.db_name,),
    )
    assert [row[0] for row in pk] == ["email", "chat_id"]
    fk = _fetchall(
        fresh_db,
        "SELECT REFERENCED_TABLE_NAME, DELETE_RULE FROM information_schema.REFERENTIAL_CONSTRAINTS"
        " WHERE CONSTRAINT_SCHEMA = %s AND CONSTRAINT_NAME = 'fk_assistant_access_chat'",
        (fresh_db.db_name,),
    )
    assert fk == [("chats", "CASCADE")]


def test_assistant_access_cascade_on_chat_delete(fresh_db: Settings) -> None:
    """Usunięcie czatu usuwa jego granty (FK CASCADE) — zostaje 0 wierszy (C1)."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    chat_id = _insert_chat_with_grant(fresh_db)
    assert _fetchall(fresh_db, "SELECT COUNT(*) FROM assistant_access") == [(1,)]
    connection = _connect(fresh_db)
    try:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM chats WHERE id = %s", (chat_id,))
        connection.commit()
    finally:
        connection.close()
    assert _fetchall(fresh_db, "SELECT COUNT(*) FROM assistant_access") == [(0,)]


def test_audit_log_id_autoincrement(fresh_db: Settings) -> None:
    """`audit_log.id` = BIGINT AUTO_INCREMENT i PK (C1)."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    rows = _fetchall(
        fresh_db,
        "SELECT DATA_TYPE, EXTRA, COLUMN_KEY FROM information_schema.COLUMNS"
        " WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'audit_log' AND COLUMN_NAME = 'id'",
        (fresh_db.db_name,),
    )
    assert rows == [("bigint", "auto_increment", "PRI")]


def test_tables_collation(fresh_db: Settings) -> None:
    command.upgrade(alembic_cfg(fresh_db), "head")
    for table in (
        *K2_TABLES,
        *HUB_COMPAT_TABLES,
        *INTEGRATION_TABLES,
        *PROVIDER_TABLES,
        *SEARCH_TABLES,
        *AGENT_TABLES,
        *IMPORT_TABLES,
        # Tabela spisów treści (K21 §1): table-level DEFAULT CHARSET=utf8mb4 /
        # COLLATE=utf8mb4_uca1400_ai_ci — kolacja z przestrzeni utf8mb4 pinuje oba poziomy.
        *PROFILE_TABLES,
    ):
        rows = _fetchall(
            fresh_db,
            "SELECT TABLE_COLLATION, ENGINE FROM information_schema.TABLES"
            " WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
            (fresh_db.db_name, table),
        )
        assert rows == [("utf8mb4_uca1400_ai_ci", "InnoDB")], table


def test_no_vector_index(fresh_db: Settings) -> None:
    command.upgrade(alembic_cfg(fresh_db), "head")
    for table in ("chunk_vec_d3072", "chunk_vec_d1536"):
        rows = _fetchall(
            fresh_db,
            "SELECT INDEX_NAME FROM information_schema.STATISTICS"
            " WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND INDEX_TYPE = 'VECTOR'",
            (fresh_db.db_name, table),
        )
        assert rows == [], table
    rows = _fetchall(
        fresh_db,
        "SELECT DISTINCT INDEX_NAME FROM information_schema.STATISTICS"
        " WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'chunks' AND INDEX_TYPE = 'FULLTEXT'",
        (fresh_db.db_name,),
    )
    assert {row[0] for row in rows} == FULLTEXT_INDEXES


def test_dataset_defaults(fresh_db: Settings) -> None:
    command.upgrade(alembic_cfg(fresh_db), "head")
    user_id = "u" * 32
    dataset_id = "d" * 32
    connection = _connect(fresh_db)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO users (id, email, nickname, create_time, create_date,"
                " update_time, update_date) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (user_id, "seed@example.com", "seed", *TIME_COLS),
            )
            cursor.execute(
                "INSERT INTO datasets (id, tenant_id, created_by, name, embedding_model,"
                " embedding_dim, create_time, create_date, update_time, update_date)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    dataset_id,
                    user_id,
                    user_id,
                    "Projekt",
                    "openai/text-embedding-3-large",
                    3072,
                    *TIME_COLS,
                ),
            )
        connection.commit()
    finally:
        connection.close()
    rows = _fetchall(
        fresh_db,
        "SELECT JSON_VALUE(parser_config, '$.delimiter') = CHAR(10), name_ci = LOWER(name)"
        " FROM datasets WHERE id = %s",
        (dataset_id,),
    )
    assert rows == [(1, 1)]
    connection = _connect(fresh_db)
    try:
        # Ta sama nazwa w innym case → kolizja uq_datasets_tenant_name_ci (C9).
        with connection.cursor() as cursor, pytest.raises(pymysql.err.IntegrityError):
            cursor.execute(
                "INSERT INTO datasets (id, tenant_id, created_by, name, embedding_model,"
                " embedding_dim, create_time, create_date, update_time, update_date)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    "e" * 32,
                    user_id,
                    user_id,
                    "projekt",
                    "openai/text-embedding-3-large",
                    3072,
                    *TIME_COLS,
                ),
            )
    finally:
        connection.close()


def test_migrate_tool_ok(fresh_db: Settings) -> None:
    result = _run_migrate({}, fresh_db)
    assert result.returncode == 0, result.stderr
    assert set(K2_TABLES) <= table_names(fresh_db)


def test_migrate_tool_fails(fresh_db: Settings) -> None:
    result = _run_migrate({"WD_DB_PASSWORD": "wrong"}, fresh_db)
    assert result.returncode != 0


# --- Migracja 0008 (schemat agenta + seed dostawcy, K2 §6, WP E6-3f) ---

# Stały identyfikator wiersza seedu dostawcy `searxng` (K2 §6).
SEARXNG_SEED_ID = "5ea4c00d5ea4c00d5ea4c00d5ea4c00d"

# Kopia instrukcji seedu z migracji 0008 — test (d) p. 1 briefu sprawdza jej idempotencję
# (NOT EXISTS). Daty/czasy jako %s, żeby wstawić je bez powielania logiki czasu migracji.
SEARXNG_SEED_SQL = (
    "INSERT INTO web_search_providers (id, provider, name, config, api_key_enc, is_default,"
    " created_by, create_time, create_date, update_time, update_date)"
    " SELECT '5ea4c00d5ea4c00d5ea4c00d5ea4c00d', 'searxng', 'searxng',"
    ' \'{"base_url": "http://searxng:8080"}\', NULL, 1, NULL, %s, %s, %s, %s'
    " FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM web_search_providers WHERE name = 'searxng')"
)

AGENT_ID = "a" * 32
SESSION_ID = "b" * 32


def _insert_user(settings: Settings, user_id: str, nickname: str) -> None:
    """Wiersz `users` — właściciel agentów (FK RESTRICT, K2 §6)."""
    connection = _connect(settings)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO users (id, email, nickname, create_time, create_date,"
                " update_time, update_date) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (user_id, f"{user_id[0]}{nickname.lower()}@example.com", nickname, *TIME_COLS),
            )
        connection.commit()
    finally:
        connection.close()


def _insert_agent(settings: Settings, *, agent_id: str, tenant_id: str, title: str) -> None:
    """Wiersz `agents` z domyślnymi kolumnami poza kluczowymi (K2 §6)."""
    connection = _connect(settings)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO agents (id, tenant_id, created_by, title, dsl,"
                " create_time, create_date, update_time, update_date)"
                " VALUES (%s, %s, %s, %s, '{}', %s, %s, %s, %s)",
                (agent_id, tenant_id, tenant_id, title, *TIME_COLS),
            )
        connection.commit()
    finally:
        connection.close()


def test_up_down_up_0008(fresh_db: Settings) -> None:
    """Z bazy `0007` `upgrade head` dokłada 3 tabele agenta; dane `users` bez zmian (K2 §6)."""
    cfg = alembic_cfg(fresh_db)
    command.upgrade(cfg, "0007")
    assert _fetchall(fresh_db, "SELECT version_num FROM alembic_version") == [("0007",)]
    _insert_user(fresh_db, "u" * 32, "Agent")
    command.upgrade(cfg, "head")
    assert set(AGENT_TABLES) <= table_names(fresh_db)
    assert table_names(fresh_db) == ALL_TABLES
    assert _fetchall(fresh_db, "SELECT id, nickname FROM users") == [("u" * 32, "Agent")]
    assert _fetchall(fresh_db, "SELECT version_num FROM alembic_version") == [(SCHEMA_HEAD,)]


def test_seed_searxng_provider(fresh_db: Settings) -> None:
    """Po `upgrade head` jest dokładnie 1 wiersz `searxng` wg K2 §6 (b)."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    assert _fetchall(fresh_db, "SELECT COUNT(*) FROM web_search_providers") == [(1,)]
    rows = _fetchall(
        fresh_db,
        "SELECT id, provider, name, JSON_VALUE(config, '$.base_url'),"
        " api_key_enc IS NULL, is_default, created_by"
        " FROM web_search_providers WHERE name = %s",
        ("searxng",),
    )
    assert rows == [(SEARXNG_SEED_ID, "searxng", "searxng", "http://searxng:8080", 1, 1, None)]
    config_text = _fetchall(
        fresh_db, "SELECT config FROM web_search_providers WHERE name = %s", ("searxng",)
    )[0][0]
    assert json.loads(config_text) == {"base_url": "http://searxng:8080"}


def test_seed_searxng_idempotent(fresh_db: Settings) -> None:
    """Ponowne wykonanie instrukcji seedu nie dubluje wiersza (idempotencja, K2 §6)."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    connection = _connect(fresh_db)
    try:
        with connection.cursor() as cursor:
            cursor.execute(SEARXNG_SEED_SQL, (*TIME_COLS,))
        connection.commit()
    finally:
        connection.close()
    assert _fetchall(fresh_db, "SELECT COUNT(*) FROM web_search_providers") == [(1,)]


def test_up_down_up_0008_downgrade(fresh_db: Settings) -> None:
    """`downgrade 0007` usuwa 3 tabele; ponowny upgrade daje znów 1 wiersz seedu (K2 §6)."""
    cfg = alembic_cfg(fresh_db)
    command.upgrade(cfg, "head")
    assert _fetchall(fresh_db, "SELECT COUNT(*) FROM web_search_providers") == [(1,)]
    command.downgrade(cfg, "0007")
    after_down = table_names(fresh_db)
    assert not set(AGENT_TABLES) & after_down
    assert _fetchall(fresh_db, "SELECT version_num FROM alembic_version") == [("0007",)]
    command.upgrade(cfg, "head")
    assert set(AGENT_TABLES) <= table_names(fresh_db)
    assert _fetchall(fresh_db, "SELECT COUNT(*) FROM web_search_providers") == [(1,)]


def test_agents_constraints(fresh_db: Settings) -> None:
    """FK/unikaty 0008: kaskada sesji, RESTRICT tenanta, unikat (tenant_id, title) (K2 §6)."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    user_id = "u" * 32
    _insert_user(fresh_db, user_id, "Agent")
    _insert_agent(fresh_db, agent_id=AGENT_ID, tenant_id=user_id, title="Agent A")
    connection = _connect(fresh_db)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO agent_sessions (id, agent_id, user_id, owner_id, messages,"
                " reference, dsl, create_time, create_date, update_time, update_date)"
                " VALUES (%s, %s, %s, %s, '[]', '{}', '{}', %s, %s, %s, %s)",
                (SESSION_ID, AGENT_ID, "user", user_id, *TIME_COLS),
            )
            # Unikat (tenant_id, title): druga „Agent A" w tym samym tenancie odrzucona.
            with pytest.raises(pymysql.err.IntegrityError) as dup_error:
                cursor.execute(
                    "INSERT INTO agents (id, tenant_id, created_by, title, dsl,"
                    " create_time, create_date, update_time, update_date)"
                    " VALUES (%s, %s, %s, %s, '{}', %s, %s, %s, %s)",
                    ("c" * 32, user_id, user_id, "Agent A", *TIME_COLS),
                )
            assert dup_error.value.args[0] == ER_DUP_ENTRY
            # FK agents.tenant_id → users RESTRICT: użytkownika z agentem nie da się usunąć.
            with pytest.raises(pymysql.err.IntegrityError):
                cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
            # Kaskada: usunięcie agenta kasuje jego sesje.
            cursor.execute("DELETE FROM agents WHERE id = %s", (AGENT_ID,))
        connection.commit()
    finally:
        connection.close()
    assert _fetchall(fresh_db, "SELECT COUNT(*) FROM agents") == [(0,)]
    assert _fetchall(fresh_db, "SELECT COUNT(*) FROM agent_sessions") == [(0,)]


# --- Migracja 0009 (sesje importu KB, K19 §4 / CONTRACT E7-1f §5) ---

# Kolumny `dataset_imports` w kolejności DDL K19 §4.
IMPORT_COLUMNS = (
    "id",
    "user_id",
    "file_name",
    "size_bytes",
    "received_bytes",
    "state",
    "errors",
    "summary",
    "task_id",
    "expires_at",
    "create_time",
    "create_date",
    "update_time",
    "update_date",
)


def _columns(settings: Settings, table: str) -> list[tuple[str, str]]:
    """(COLUMN_NAME, DATA_TYPE) w kolejności z DDL (K19 §4)."""
    rows = _fetchall(
        settings,
        "SELECT COLUMN_NAME, DATA_TYPE FROM information_schema.COLUMNS"
        " WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION",
        (settings.db_name, table),
    )
    return [(str(row[0]), str(row[1])) for row in rows]


def test_up_down_up_0009(fresh_db: Settings) -> None:
    """Z bazy `0008` `upgrade head` dokłada tabele importu; `downgrade 0008` je usuwa (K19 §4)."""
    cfg = alembic_cfg(fresh_db)
    command.upgrade(cfg, "0008")
    assert _fetchall(fresh_db, "SELECT version_num FROM alembic_version") == [("0008",)]
    command.upgrade(cfg, "head")
    assert set(IMPORT_TABLES) <= table_names(fresh_db)
    assert table_names(fresh_db) == ALL_TABLES
    assert _fetchall(fresh_db, "SELECT version_num FROM alembic_version") == [(SCHEMA_HEAD,)]
    command.downgrade(cfg, "0008")
    after_down = table_names(fresh_db)
    assert not set(IMPORT_TABLES) & after_down
    assert _fetchall(fresh_db, "SELECT version_num FROM alembic_version") == [("0008",)]
    command.upgrade(cfg, "head")
    assert set(IMPORT_TABLES) <= table_names(fresh_db)
    assert _fetchall(fresh_db, "SELECT version_num FROM alembic_version") == [(SCHEMA_HEAD,)]


def test_dataset_imports_schema(fresh_db: Settings) -> None:
    """Kształt `dataset_imports`: kolumny/typy i ENUM stanu wg K19 §4.

    MariaDB trzyma `JSON` jako `longtext` z `CHECK json_valid(...)` — stąd typ kolumn JSON
    i osobne sprawdzenie ograniczeń.
    """
    command.upgrade(alembic_cfg(fresh_db), "head")
    assert _columns(fresh_db, "dataset_imports") == [
        ("id", "char"),
        ("user_id", "char"),
        ("file_name", "varchar"),
        ("size_bytes", "bigint"),
        ("received_bytes", "bigint"),
        ("state", "enum"),
        ("errors", "longtext"),
        ("summary", "longtext"),
        ("task_id", "char"),
        ("expires_at", "bigint"),
        ("create_time", "bigint"),
        ("create_date", "datetime"),
        ("update_time", "bigint"),
        ("update_date", "datetime"),
    ]
    checks = _fetchall(
        fresh_db,
        "SELECT CONSTRAINT_NAME, CHECK_CLAUSE FROM information_schema.CHECK_CONSTRAINTS"
        " WHERE CONSTRAINT_SCHEMA = %s AND TABLE_NAME = 'dataset_imports'"
        " ORDER BY CONSTRAINT_NAME",
        (fresh_db.db_name,),
    )
    assert [str(row[1]) for row in checks] == [
        "json_valid(`errors`)",
        "json_valid(`summary`)",
    ]
    state_type = _fetchall(
        fresh_db,
        "SELECT COLUMN_TYPE FROM information_schema.COLUMNS"
        " WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'dataset_imports' AND COLUMN_NAME = 'state'",
        (fresh_db.db_name,),
    )
    assert state_type == [
        ("enum('uploading','ready','invalid','started','expired')",),
    ]
    assert _column_meta(fresh_db, "dataset_imports", "task_id")[2] == "YES"
    assert _column_meta(fresh_db, "dataset_imports", "summary")[2] == "YES"


def test_dataset_imports_indexes_and_fk(fresh_db: Settings) -> None:
    """PK `id`, indeksy `user`/`expires` i FK `users` ON DELETE CASCADE (K19 §4)."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    indexes = _fetchall(
        fresh_db,
        "SELECT DISTINCT INDEX_NAME FROM information_schema.STATISTICS"
        " WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'dataset_imports'",
        (fresh_db.db_name,),
    )
    assert {row[0] for row in indexes} == {
        "PRIMARY",
        "ix_dataset_imports_user",
        "ix_dataset_imports_expires",
    }
    fks = _fetchall(
        fresh_db,
        "SELECT CONSTRAINT_NAME, REFERENCED_TABLE_NAME, DELETE_RULE"
        " FROM information_schema.REFERENTIAL_CONSTRAINTS"
        " WHERE CONSTRAINT_SCHEMA = %s AND TABLE_NAME = 'dataset_imports'",
        (fresh_db.db_name,),
    )
    assert [tuple(row) for row in fks] == [("fk_dataset_imports_user", "users", "CASCADE")]


def test_dataset_imports_defaults(fresh_db: Settings) -> None:
    """Wiersz bez `received_bytes`/`state`/`errors` dostaje domyślne z K19 §4."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    user_id = "u" * 32
    _insert_user(fresh_db, user_id, "Import")
    connection = _connect(fresh_db)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO dataset_imports (id, user_id, file_name, size_bytes, expires_at,"
                " create_time, create_date, update_time, update_date)"
                " VALUES (%s, %s, 'baza.wdkb.zip', 1024, %s, %s, %s, %s, %s)",
                ("i" * 32, user_id, 1, *TIME_COLS),
            )
        connection.commit()
    finally:
        connection.close()
    rows = _fetchall(
        fresh_db,
        "SELECT received_bytes, state, JSON_LENGTH(errors), summary, task_id"
        " FROM dataset_imports WHERE id = %s",
        ("i" * 32,),
    )
    assert rows == [(0, "uploading", 0, None, None)]


def test_wd_settings_schema(fresh_db: Settings) -> None:
    """`wd_settings`: PK `name` (ascii_bin), `value` TEXT, `update_time` BIGINT (CONTRACT §5)."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    pk = _fetchall(
        fresh_db,
        "SELECT COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE"
        " WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'wd_settings' AND CONSTRAINT_NAME = 'PRIMARY'"
        " ORDER BY ORDINAL_POSITION",
        (fresh_db.db_name,),
    )
    assert [row[0] for row in pk] == ["name"]
    assert _columns(fresh_db, "wd_settings") == [
        ("name", "varchar"),
        ("value", "text"),
        ("update_time", "bigint"),
    ]
    rows = _fetchall(
        fresh_db,
        "SELECT COLUMN_NAME, CHARACTER_SET_NAME, COLLATION_NAME"
        " FROM information_schema.COLUMNS"
        " WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'wd_settings'"
        " AND COLUMN_NAME IN ('name', 'value') ORDER BY COLUMN_NAME",
        (fresh_db.db_name,),
    )
    assert [tuple(row) for row in rows] == [
        ("name", "ascii", "ascii_bin"),
        ("value", "utf8mb4", "utf8mb4_uca1400_ai_ci"),
    ]


# --- Migracja 0010 (spisy treści dokumentów, K21 §1) ---


def _insert_document_row(
    settings: Settings,
    *,
    dataset_id: str,
    created_by: str,
    document_id: str,
    name: str = "doc.pdf",
) -> None:
    """Dokument nadrzędny dla FK `document_profiles.document_id` (kolumny obowiązkowe K2)."""
    connection = _connect(settings)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO documents (id, dataset_id, created_by, name, suffix, type,"
                " location, content_hash, chunk_method, parser_config, create_time,"
                " create_date, update_time, update_date)"
                " VALUES (%s, %s, %s, %s, 'pdf', 'doc', 'files/x.pdf', '0', 'naive', '{}',"
                " %s, %s, %s, %s)",
                (document_id, dataset_id, created_by, name, *TIME_COLS),
            )
        connection.commit()
    finally:
        connection.close()


def _insert_dataset_row(settings: Settings, *, dataset_id: str, created_by: str, name: str) -> None:
    """Dataset nadrzędny dla FK `documents.dataset_id` (kolumny obowiązkowe K2)."""
    connection = _connect(settings)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO datasets (id, tenant_id, created_by, name, embedding_model,"
                " embedding_dim, create_time, create_date, update_time, update_date)"
                " VALUES (%s, %s, %s, %s, 'openai/text-embedding-3-large', 3072, %s, %s, %s, %s)",
                (dataset_id, created_by, created_by, name, *TIME_COLS),
            )
        connection.commit()
    finally:
        connection.close()


def test_up_down_up_0010(fresh_db: Settings) -> None:
    """Z bazy `0009` `upgrade head` dokłada `document_profiles`; `downgrade 0009` ją usuwa."""
    cfg = alembic_cfg(fresh_db)
    command.upgrade(cfg, "0009")
    assert _fetchall(fresh_db, "SELECT version_num FROM alembic_version") == [("0009",)]
    command.upgrade(cfg, "head")
    assert set(PROFILE_TABLES) <= table_names(fresh_db)
    assert table_names(fresh_db) == ALL_TABLES
    assert _fetchall(fresh_db, "SELECT version_num FROM alembic_version") == [(SCHEMA_HEAD,)]
    command.downgrade(cfg, "0009")
    after_down = table_names(fresh_db)
    assert not set(PROFILE_TABLES) & after_down
    assert _fetchall(fresh_db, "SELECT version_num FROM alembic_version") == [("0009",)]
    command.upgrade(cfg, "head")
    assert set(PROFILE_TABLES) <= table_names(fresh_db)
    assert _fetchall(fresh_db, "SELECT version_num FROM alembic_version") == [(SCHEMA_HEAD,)]


def test_document_profiles_schema(fresh_db: Settings) -> None:
    """Kształt `document_profiles`: kolumny/typy i NULL-owalność wg K21 §1.

    MariaDB trzyma `JSON` jako `longtext` z `CHECK json_valid(...)` — stąd typ kolumn JSON
    i osobne sprawdzenie ograniczeń.
    """
    command.upgrade(alembic_cfg(fresh_db), "head")
    assert _columns(fresh_db, "document_profiles") == [
        ("document_id", "char"),
        ("dataset_id", "char"),
        ("outline", "longtext"),
        ("outline_source", "varchar"),
        ("outline_count", "int"),
        ("summary", "mediumtext"),
        ("topics", "longtext"),
        ("model", "varchar"),
        ("create_time", "bigint"),
        ("update_time", "bigint"),
    ]
    checks = _fetchall(
        fresh_db,
        "SELECT CONSTRAINT_NAME, CHECK_CLAUSE FROM information_schema.CHECK_CONSTRAINTS"
        " WHERE CONSTRAINT_SCHEMA = %s AND TABLE_NAME = 'document_profiles'"
        " ORDER BY CONSTRAINT_NAME",
        (fresh_db.db_name,),
    )
    assert [str(row[1]) for row in checks] == [
        "json_valid(`outline`)",
        "json_valid(`topics`)",
    ]
    # `summary`/`topics`/`model` — rezerwa etapu 2, kolumny nullable (K21 §1).
    assert _column_meta(fresh_db, "document_profiles", "summary")[2] == "YES"
    assert _column_meta(fresh_db, "document_profiles", "topics")[2] == "YES"
    assert _column_meta(fresh_db, "document_profiles", "model")[2] == "YES"
    id_collation = _fetchall(
        fresh_db,
        "SELECT COLUMN_NAME, CHARACTER_SET_NAME, COLLATION_NAME FROM information_schema.COLUMNS"
        " WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'document_profiles'"
        " AND COLUMN_NAME IN ('document_id', 'dataset_id') ORDER BY COLUMN_NAME",
        (fresh_db.db_name,),
    )
    assert [tuple(row) for row in id_collation] == [
        ("dataset_id", "ascii", "ascii_bin"),
        ("document_id", "ascii", "ascii_bin"),
    ]


def test_document_profiles_indexes_and_fk(fresh_db: Settings) -> None:
    """PK `document_id`, indeks `dataset` i FK `documents` ON DELETE CASCADE (K21 §1)."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    indexes = _fetchall(
        fresh_db,
        "SELECT DISTINCT INDEX_NAME FROM information_schema.STATISTICS"
        " WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'document_profiles'",
        (fresh_db.db_name,),
    )
    assert {row[0] for row in indexes} == {"PRIMARY", "ix_document_profiles_dataset"}
    fks = _fetchall(
        fresh_db,
        "SELECT CONSTRAINT_NAME, REFERENCED_TABLE_NAME, DELETE_RULE"
        " FROM information_schema.REFERENTIAL_CONSTRAINTS"
        " WHERE CONSTRAINT_SCHEMA = %s AND TABLE_NAME = 'document_profiles'",
        (fresh_db.db_name,),
    )
    assert [tuple(row) for row in fks] == [
        ("fk_document_profiles_document", "documents", "CASCADE")
    ]


def test_document_profiles_defaults(fresh_db: Settings) -> None:
    """Wiersz bez `outline`/`outline_count` dostaje domyślne `'[]'`/0; rezerwy NULL (K21 §1)."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    _insert_user(fresh_db, "u" * 32, "Profile")
    _insert_dataset_row(fresh_db, dataset_id="s" * 32, created_by="u" * 32, name="Baza")
    _insert_document_row(fresh_db, dataset_id="s" * 32, created_by="u" * 32, document_id="d" * 32)
    connection = _connect(fresh_db)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO document_profiles (document_id, dataset_id, outline_source,"
                " create_time, update_time) VALUES (%s, %s, 'none', %s, %s)",
                # Tabela bez mixin czasu (`*_date` z K2) — same BIGINT-y (K21 §1).
                ("d" * 32, "s" * 32, 1, 1),
            )
        connection.commit()
    finally:
        connection.close()
    rows = _fetchall(
        fresh_db,
        "SELECT JSON_LENGTH(outline), outline_count, summary, topics, model"
        " FROM document_profiles WHERE document_id = %s",
        ("d" * 32,),
    )
    assert rows == [(0, 0, None, None, None)]
