"""Kolumny, SQL i idempotencja tabel integracji WD (kontrakt §8 i §9).

Wydzielone z ``stages/integrations.py`` (limit rozmiaru pliku, kontrakt C2). ``_Target`` opisuje
zapis jednej tabeli celu; ``write_rows`` wykonuje INSERT/UPDATE/skip wg klucza i porównania wiersza.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationFailed
from app.integrations.secrets import decrypt_secret
from app.tools.ragflow_migrate.stages.common import same_json
from app.tools.ragflow_migrate.stages.integration_rows import Row

#: Tabele źródłowe objęte etapem (liczniki inwentarza). ``integration_sharepoint`` nie ma własnej
#: tabeli źródłowej — powstaje z wiersza ``ai_hub_sharepoint_integrations``.
SOURCE_INTEGRATIONS = "ai_hub_sharepoint_integrations"
SOURCE_DRIVES = "ai_hub_sharepoint_integration_drives"
SOURCE_RUNS = "ai_hub_integration_sync_runs"
SOURCE_EVENTS = "ai_hub_integration_sync_events"
SOURCE_MAPPINGS = "ai_hub_integration_file_mappings"
SOURCE_TABLES: tuple[str, ...] = (
    SOURCE_INTEGRATIONS,
    SOURCE_DRIVES,
    SOURCE_RUNS,
    SOURCE_EVENTS,
    SOURCE_MAPPINGS,
)

#: Kolumny celu pisane przez etap (kolejność = lista INSERT).
INTEGRATION_COLUMNS: tuple[str, ...] = (
    "id",
    "type",
    "name",
    "dataset_id",
    "owner_id",
    "config",
    "secret_enc",
    "secret_last4",
    "max_file_size_bytes",
    "ignored_extensions",
    "scan_interval_seconds",
    "delete_propagation",
    "is_active",
    "is_running",
    "lock_acquired_at",
    "lock_owner",
    "cancel_requested",
    "last_sync_at",
    "last_sync_status",
    "created_at",
    "updated_at",
)
SHAREPOINT_COLUMNS: tuple[str, ...] = (
    "integration_id",
    "tenant_id",
    "client_id",
    "site_url",
    "site_id",
    "site_display_name",
    "excluded_library_names",
)
CONTAINER_COLUMNS: tuple[str, ...] = (
    "integration_id",
    "container_id",
    "name",
    "delta_cursor",
    "last_sync_at",
    "discovered_at",
)
RUN_COLUMNS: tuple[str, ...] = (
    "id",
    "integration_id",
    "integration_type",
    "run_trigger",
    "started_at",
    "finished_at",
    "status",
    "added",
    "updated",
    "renamed",
    "deleted",
    "failed",
    "skipped",
)
EVENT_COLUMNS: tuple[str, ...] = (
    "id",
    "run_id",
    "integration_id",
    "integration_type",
    "level",
    "message",
    "file_path",
    "container_id",
    "container_name",
    "created_at",
)
MAPPING_COLUMNS: tuple[str, ...] = (
    "integration_id",
    "container_id",
    "item_id",
    "document_id",
    "content_tag",
    "meta_tag",
    "name",
    "path",
    "web_url",
    "last_status",
    "last_error",
    "updated_at",
)

#: Kolumny JSON porównywane strukturalnie (kontrakt §8/§9).
INTEGRATION_JSON: frozenset[str] = frozenset({"config", "ignored_extensions"})
SHAREPOINT_JSON: frozenset[str] = frozenset({"excluded_library_names"})

_INTEGRATION_KEYS: tuple[str, ...] = ("id",)
_SHAREPOINT_KEYS: tuple[str, ...] = ("integration_id",)
_CONTAINER_KEYS: tuple[str, ...] = ("integration_id", "container_id")
_RUN_KEYS: tuple[str, ...] = ("id",)
_EVENT_KEYS: tuple[str, ...] = ("id",)
_MAPPING_KEYS: tuple[str, ...] = ("integration_id", "container_id", "item_id")

#: Klucz wiersza w mapie istniejących wierszy celu.
Key = tuple[str, ...]


def _insert_sql(table: str, columns: tuple[str, ...]) -> str:
    # Nazwy tabel i kolumn to stałe modułu (nie dane), więc interpolacja jest bezpieczna.
    names = ", ".join(columns)
    values = ", ".join(":" + column for column in columns)
    return f"INSERT INTO {table} ({names}) VALUES ({values})"  # noqa: S608


def _where(keys: tuple[str, ...]) -> str:
    return " AND ".join(f"{column} = :{column}" for column in keys)


def _update_sql(table: str, columns: tuple[str, ...], keys: tuple[str, ...]) -> str:
    assignments = ", ".join(f"{column} = :{column}" for column in columns if column not in keys)
    return f"UPDATE {table} SET {assignments} WHERE {_where(keys)}"  # noqa: S608


def _select_sql(table: str, columns: tuple[str, ...], column: str) -> str:
    names = ", ".join(columns)
    return f"SELECT {names} FROM {table} WHERE {column} IN :ids"  # noqa: S608


_INTEGRATION_INSERT = _insert_sql("integrations", INTEGRATION_COLUMNS)
_INTEGRATION_UPDATE = _update_sql("integrations", INTEGRATION_COLUMNS, _INTEGRATION_KEYS)
_INTEGRATION_SELECT = _select_sql("integrations", INTEGRATION_COLUMNS, "id")
_SHAREPOINT_INSERT = _insert_sql("integration_sharepoint", SHAREPOINT_COLUMNS)
_SHAREPOINT_UPDATE = _update_sql("integration_sharepoint", SHAREPOINT_COLUMNS, _SHAREPOINT_KEYS)
_SHAREPOINT_SELECT = _select_sql("integration_sharepoint", SHAREPOINT_COLUMNS, "integration_id")
_CONTAINER_INSERT = _insert_sql("integration_containers", CONTAINER_COLUMNS)
_CONTAINER_UPDATE = _update_sql("integration_containers", CONTAINER_COLUMNS, _CONTAINER_KEYS)
_CONTAINER_SELECT = _select_sql("integration_containers", CONTAINER_COLUMNS, "integration_id")
_RUN_INSERT = _insert_sql("integration_sync_runs", RUN_COLUMNS)
_RUN_UPDATE = _update_sql("integration_sync_runs", RUN_COLUMNS, _RUN_KEYS)
_RUN_SELECT = _select_sql("integration_sync_runs", RUN_COLUMNS, "id")
_EVENT_INSERT = _insert_sql("integration_sync_events", EVENT_COLUMNS)
_EVENT_UPDATE = _update_sql("integration_sync_events", EVENT_COLUMNS, _EVENT_KEYS)
_EVENT_SELECT = _select_sql("integration_sync_events", EVENT_COLUMNS, "id")
_MAPPING_INSERT = _insert_sql("integration_item_mappings", MAPPING_COLUMNS)
_MAPPING_UPDATE = _update_sql("integration_item_mappings", MAPPING_COLUMNS, _MAPPING_KEYS)
_MAPPING_SELECT = _select_sql("integration_item_mappings", MAPPING_COLUMNS, "integration_id")

#: Zapytania pomocnicze etapu (istniejący dataset/dokument, licznik integracji celu).
DATASET_OWNERS = "SELECT id, created_by FROM datasets WHERE id IN :ids"
DOCUMENT_IDS = "SELECT id FROM documents WHERE id IN :ids"
TARGET_COUNT = "SELECT COUNT(*) FROM integrations"


def unchanged(
    existing: Mapping[str, Any],
    computed: Mapping[str, Any],
    json_columns: frozenset[str] = frozenset(),
) -> bool:
    """True, gdy istniejący wiersz celu równa się wyliczonemu (idempotencja, kontrakt §9)."""
    for column, value in computed.items():
        if column in json_columns:
            if not same_json(existing[column], value):
                return False
        elif str(existing[column]) != str(value):
            return False
    return True


def integration_unchanged(
    existing: Mapping[str, Any], computed: Mapping[str, Any], wd_key: str, plaintext: str
) -> bool:
    """Idempotencja ``integrations``: ``secret_enc`` z odszyfrowania celu (nonce jest losowy)."""
    for column in INTEGRATION_COLUMNS:
        if column == "secret_enc":
            stored = existing[column]
            if stored is None:
                return False
            try:
                if decrypt_secret(wd_key, int(computed["id"]), str(stored)) != plaintext:
                    return False
            except ValidationFailed:
                return False
        elif column in INTEGRATION_JSON:
            if not same_json(existing[column], computed[column]):
                return False
        elif str(existing[column]) != str(computed[column]):
            return False
    return True


def _id_key(row: Mapping[str, Any]) -> Key:
    """Klucz wiersza po kolumnie ``id``."""
    return (str(row["id"]),)


def _integration_key(row: Mapping[str, Any]) -> Key:
    """Klucz ``integration_sharepoint`` (PK = ``integration_id``)."""
    return (str(row["integration_id"]),)


def _container_key(row: Mapping[str, Any]) -> Key:
    """Klucz ``integration_containers`` (PK = ``integration_id``, ``container_id``)."""
    return (str(row["integration_id"]), str(row["container_id"]))


def _mapping_key(row: Mapping[str, Any]) -> Key:
    """Klucz ``integration_item_mappings`` (PK = id integracji, kontenera i elementu)."""
    return (str(row["integration_id"]), str(row["container_id"]), str(row["item_id"]))


def _id_of(row: Mapping[str, Any]) -> str:
    """Wartość ``id`` wiersza — do ``WHERE id IN :ids``."""
    return str(row["id"])


def _integration_of(row: Mapping[str, Any]) -> str:
    """Wartość ``integration_id`` wiersza — do ``WHERE integration_id IN :ids``."""
    return str(row["integration_id"])


@dataclass(frozen=True)
class Target:
    """Opis zapisu jednej tabeli celu: SQL, klucz wiersza i porównanie idempotencji."""

    insert: str
    update: str
    select: str
    key_of: Callable[[Mapping[str, Any]], Key]
    ids_of: Callable[[Mapping[str, Any]], str]
    unchanged: Callable[[Mapping[str, Any], Mapping[str, Any]], bool] = unchanged


SHAREPOINT_TARGET = Target(
    insert=_SHAREPOINT_INSERT,
    update=_SHAREPOINT_UPDATE,
    select=_SHAREPOINT_SELECT,
    key_of=_integration_key,
    ids_of=_integration_of,
    unchanged=lambda existing, computed: unchanged(existing, computed, SHAREPOINT_JSON),
)
CONTAINER_TARGET = Target(
    insert=_CONTAINER_INSERT,
    update=_CONTAINER_UPDATE,
    select=_CONTAINER_SELECT,
    key_of=_container_key,
    ids_of=_integration_of,
)
RUN_TARGET = Target(
    insert=_RUN_INSERT,
    update=_RUN_UPDATE,
    select=_RUN_SELECT,
    key_of=_id_key,
    ids_of=_id_of,
)
EVENT_TARGET = Target(
    insert=_EVENT_INSERT,
    update=_EVENT_UPDATE,
    select=_EVENT_SELECT,
    key_of=_id_key,
    ids_of=_id_of,
)
MAPPING_TARGET = Target(
    insert=_MAPPING_INSERT,
    update=_MAPPING_UPDATE,
    select=_MAPPING_SELECT,
    key_of=_mapping_key,
    ids_of=_integration_of,
)


def integrations_target(wd_key: str, secrets: dict[int, str]) -> Target:
    """Opis zapisu ``integrations`` z idempotencją sekretu (odszyfrowanie wiersza celu)."""
    return Target(
        insert=_INTEGRATION_INSERT,
        update=_INTEGRATION_UPDATE,
        select=_INTEGRATION_SELECT,
        key_of=_id_key,
        ids_of=_id_of,
        unchanged=lambda existing, computed: integration_unchanged(
            existing, computed, wd_key, secrets[int(computed["id"])]
        ),
    )


async def write_rows(
    session: AsyncSession, target: Target, rows: list[Row]
) -> tuple[int, int, int]:
    """Zapis wierszy do jednej tabeli celu; zwraca ``(created, updated, skipped)``."""
    values = [target.ids_of(row) for row in rows]
    existing: dict[Key, Mapping[str, Any]] = {}
    if values:
        statement = text(target.select).bindparams(bindparam("ids", expanding=True))
        result = await session.execute(statement, {"ids": values})
        existing = {
            target.key_of(cast(Mapping[str, Any], row)): cast(Mapping[str, Any], row)
            for row in result.mappings().all()
        }
    created = updated = skipped = 0
    for row in rows:
        current = existing.get(target.key_of(row))
        if current is None:
            await session.execute(text(target.insert), row)
            created += 1
        elif target.unchanged(current, row):
            skipped += 1
        else:
            await session.execute(text(target.update), row)
            updated += 1
    return created, updated, skipped
