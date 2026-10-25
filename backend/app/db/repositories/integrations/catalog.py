"""Kontenery i mapowania elementów — SQL wg kontraktu E4-1 C2 (część pakietu ``integrations``).

Bez ``commit``/``rollback`` — transakcję otwiera wywołująca (``app.db.uow.transaction``).
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.integrations.rows import (
    ContainerRow,
    MappingRow,
    _container_row,
    _mapping_row,
)

_UPSERT_CONTAINER_SQL = text(
    "INSERT INTO integration_containers (integration_id, container_id, name, discovered_at)"
    " VALUES (:integration_id, :container_id, :name, :now_ms)"
    " ON DUPLICATE KEY UPDATE name = VALUES(name)"
)

_CONTAINER_COLUMNS = "integration_id, container_id, name, delta_cursor, last_sync_at, discovered_at"

_GET_CONTAINER_SQL = text(
    f"SELECT {_CONTAINER_COLUMNS} FROM integration_containers"  # noqa: S608 — stała
    " WHERE integration_id = :integration_id AND container_id = :container_id"
)

_LIST_CONTAINERS_SQL = text(
    f"SELECT {_CONTAINER_COLUMNS} FROM integration_containers"  # noqa: S608 — stała
    " WHERE integration_id = :integration_id ORDER BY container_id"
)

_SET_CONTAINER_CURSOR_SQL = text(
    "UPDATE integration_containers SET delta_cursor = :cursor, last_sync_at = :now_ms"
    " WHERE integration_id = :integration_id AND container_id = :container_id"
)

_RESET_CURSORS_SQL = text(
    "UPDATE integration_containers SET delta_cursor = NULL WHERE integration_id = :integration_id"
)

_UPSERT_MAPPING_SQL = text(
    "INSERT INTO integration_item_mappings (integration_id, container_id, item_id, document_id,"
    " content_tag, meta_tag, name, path, web_url, last_status, last_error, updated_at)"
    " VALUES (:integration_id, :container_id, :item_id, :document_id, :content_tag, :meta_tag,"
    " :name, :path, :web_url, :last_status, :last_error, :updated_at)"
    " ON DUPLICATE KEY UPDATE document_id = VALUES(document_id),"
    " content_tag = VALUES(content_tag), meta_tag = VALUES(meta_tag), name = VALUES(name),"
    " path = VALUES(path), web_url = VALUES(web_url), last_status = VALUES(last_status),"
    " last_error = VALUES(last_error), updated_at = VALUES(updated_at)"
)

_MAPPING_COLUMNS = (
    "integration_id, container_id, item_id, document_id, content_tag, meta_tag, name, path,"
    " web_url, last_status, last_error, updated_at"
)

_GET_MAPPING_SQL = text(
    f"SELECT {_MAPPING_COLUMNS} FROM integration_item_mappings"  # noqa: S608 — stała
    " WHERE integration_id = :integration_id AND container_id = :container_id"
    " AND item_id = :item_id"
)

_LIST_MAPPINGS_SQL = text(
    f"SELECT {_MAPPING_COLUMNS} FROM integration_item_mappings"  # noqa: S608 — stała
    " WHERE integration_id = :integration_id AND container_id = :container_id ORDER BY item_id"
)

_DELETE_MAPPING_SQL = text(
    "DELETE FROM integration_item_mappings"
    " WHERE integration_id = :integration_id AND container_id = :container_id"
    " AND item_id = :item_id"
)


async def upsert_container(
    session: AsyncSession, integration_id: int, container_id: str, *, name: str, now_ms: int
) -> None:
    """Wstawia kontener lub odświeża ``name``; ``discovered_at`` tylko przy INSERT (kontrakt C2)."""
    await session.execute(
        _UPSERT_CONTAINER_SQL,
        {
            "integration_id": integration_id,
            "container_id": container_id,
            "name": name,
            "now_ms": now_ms,
        },
    )


async def get_container(
    session: AsyncSession, integration_id: int, container_id: str
) -> ContainerRow | None:
    """Kontener po kluczu; ``None`` gdy brak (kontrakt C2)."""
    row = (
        (
            await session.execute(
                _GET_CONTAINER_SQL,
                {"integration_id": integration_id, "container_id": container_id},
            )
        )
        .mappings()
        .first()
    )
    return None if row is None else _container_row(row)


async def list_containers(session: AsyncSession, integration_id: int) -> list[ContainerRow]:
    """Kontenery integracji po ``container_id`` (kontrakt C2)."""
    rows = (
        (await session.execute(_LIST_CONTAINERS_SQL, {"integration_id": integration_id}))
        .mappings()
        .all()
    )
    return [_container_row(row) for row in rows]


async def set_container_cursor(
    session: AsyncSession,
    integration_id: int,
    container_id: str,
    *,
    cursor: str | None,
    now_ms: int,
) -> None:
    """Zapisuje ``delta_cursor`` i ``last_sync_at`` kontenera (kontrakt C2)."""
    await session.execute(
        _SET_CONTAINER_CURSOR_SQL,
        {
            "integration_id": integration_id,
            "container_id": container_id,
            "cursor": cursor,
            "now_ms": now_ms,
        },
    )


async def reset_cursors(session: AsyncSession, integration_id: int) -> None:
    """Zeruje ``delta_cursor`` wszystkich kontenerów integracji (kontrakt C2)."""
    await session.execute(_RESET_CURSORS_SQL, {"integration_id": integration_id})


async def get_mapping(
    session: AsyncSession, integration_id: int, container_id: str, item_id: str
) -> MappingRow | None:
    """Mapowanie po kluczu; ``None`` gdy brak (kontrakt C2)."""
    row = (
        (
            await session.execute(
                _GET_MAPPING_SQL,
                {
                    "integration_id": integration_id,
                    "container_id": container_id,
                    "item_id": item_id,
                },
            )
        )
        .mappings()
        .first()
    )
    return None if row is None else _mapping_row(row)


async def upsert_mapping(session: AsyncSession, row: MappingRow) -> None:
    """Wstawia mapowanie lub nadpisuje wszystkie pola poza kluczem (kontrakt C2)."""
    await session.execute(
        _UPSERT_MAPPING_SQL,
        {
            "integration_id": row.integration_id,
            "container_id": row.container_id,
            "item_id": row.item_id,
            "document_id": row.document_id,
            "content_tag": row.content_tag,
            "meta_tag": row.meta_tag,
            "name": row.name,
            "path": row.path,
            "web_url": row.web_url,
            "last_status": row.last_status,
            "last_error": row.last_error,
            "updated_at": row.updated_at,
        },
    )


async def delete_mapping(
    session: AsyncSession, integration_id: int, container_id: str, item_id: str
) -> None:
    """Usuwa mapowanie po kluczu (kontrakt C2)."""
    await session.execute(
        _DELETE_MAPPING_SQL,
        {"integration_id": integration_id, "container_id": container_id, "item_id": item_id},
    )


async def list_mappings(
    session: AsyncSession, integration_id: int, container_id: str
) -> list[MappingRow]:
    """Mapowania kontenera po ``item_id`` (kontrakt C2)."""
    rows = (
        (
            await session.execute(
                _LIST_MAPPINGS_SQL,
                {"integration_id": integration_id, "container_id": container_id},
            )
        )
        .mappings()
        .all()
    )
    return [_mapping_row(row) for row in rows]
