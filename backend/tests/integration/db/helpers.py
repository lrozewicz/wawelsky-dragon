"""Pomocniki testów migracji (brief T2, kontrakt C11/C12): alembic_cfg, K2_TABLES,
HUB_COMPAT_TABLES, INTEGRATION_TABLES, table_names, worker_db_name."""

import os
import uuid
from pathlib import Path

import pymysql
from alembic.config import Config

from app.core.config import Settings

BACKEND_DIR = Path(__file__).resolve().parents[3]


def worker_db_name(prefix: str) -> str:
    """Nazwa bazy testowej: `<prefix>_<worker>_<8 hex>` (kontrakt E5-H7 C1).

    Identyfikator workera xdist (`PYTEST_XDIST_WORKER`, np. `gw3`) wchodzi do nazwy tylko
    w biegu równoległym — ułatwia diagnozę i sprzątanie baz per worker. Bez xdist nazwa
    jest jak dotąd: `<prefix>_<8 hex>`.
    """
    suffix = uuid.uuid4().hex[:8]
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    return f"{prefix}_{worker}_{suffix}" if worker else f"{prefix}_{suffix}"


# Lista tabel K2 §2 (kontrakt C11, 19 pozycji).
K2_TABLES = (
    "users",
    "refresh_sessions",
    "api_keys",
    "models",
    "datasets",
    "documents",
    "chunks",
    "chunk_vec_d3072",
    "chunk_vec_d1536",
    "tasks",
    "chats",
    "chat_datasets",
    "chat_sessions",
    "chat_messages",
    "files",
    "file2document",
    "llm_cache",
    "embedding_cache",
    "worker_heartbeat",
)

# Tabele migracji 0002 (hub-compat user-api, kontrakt C1); K2_TABLES zostaje listą 19 tabel K2.
HUB_COMPAT_TABLES = ("assistant_access", "audit_log")

# Tabele migracji 0003 (framework integracji, kontrakt K12 §1).
INTEGRATION_TABLES = (
    "integrations",
    "integration_sharepoint",
    "integration_containers",
    "integration_item_mappings",
    "integration_sync_runs",
    "integration_sync_events",
)


def alembic_cfg(settings: Settings) -> Config:
    """Konfiguracja Alembic z ustawieniami bazy w `attributes["settings"]` (kontrakt C12)."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["settings"] = settings
    return cfg


def table_names(settings: Settings) -> set[str]:
    """Zbiór nazw tabel w bazie testowej — przez pymysql, dane dostępowe z `settings` (C12)."""
    connection = pymysql.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password.get_secret_value(),
        database=settings.db_name,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s",
                (settings.db_name,),
            )
            return {row[0] for row in cursor.fetchall()}
    finally:
        connection.close()
