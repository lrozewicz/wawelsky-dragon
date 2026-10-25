"""Wiersz ``integration_sharepoint`` i sekret integracji — SQL wg kontraktu E4-2b.

Bez ``commit``/``rollback`` — transakcję otwiera wywołująca (``app.db.uow.transaction``).
"""

import json
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.integrations.rows import _json_value, _rowcount

_SHAREPOINT_COLUMNS = (
    "integration_id, tenant_id, client_id, site_url, site_id, site_display_name,"
    " excluded_library_names"
)

_GET_SHAREPOINT_SQL = text(
    f"SELECT {_SHAREPOINT_COLUMNS} FROM integration_sharepoint"  # noqa: S608 — stała
    " WHERE integration_id = :integration_id"
)

_UPSERT_SHAREPOINT_SQL = text(
    "INSERT INTO integration_sharepoint (integration_id, tenant_id, client_id, site_url,"
    " site_id, site_display_name, excluded_library_names)"
    " VALUES (:integration_id, :tenant_id, :client_id, :site_url, :site_id,"
    " :site_display_name, :excluded_library_names)"
    " ON DUPLICATE KEY UPDATE tenant_id = VALUES(tenant_id), client_id = VALUES(client_id),"
    " site_url = VALUES(site_url), site_id = VALUES(site_id),"
    " site_display_name = VALUES(site_display_name),"
    " excluded_library_names = VALUES(excluded_library_names)"
)

_DELETE_SHAREPOINT_SQL = text(
    "DELETE FROM integration_sharepoint WHERE integration_id = :integration_id"
)

_SET_SECRET_SQL = text(
    "UPDATE integrations SET secret_enc = :secret_enc, secret_last4 = :secret_last4,"
    " updated_at = :now_ms WHERE id = :id"
)


@dataclass(frozen=True)
class SharePointRow:
    """Wiersz ``integration_sharepoint`` (kontrakt E4-2b)."""

    integration_id: int
    tenant_id: str
    client_id: str
    site_url: str
    site_id: str | None
    site_display_name: str | None
    excluded_library_names: list[str]


def _sharepoint_row(row: RowMapping) -> SharePointRow:
    """RowMapping → SharePointRow (JSON tolerancyjnie przez ``_json_value``)."""
    return SharePointRow(
        integration_id=int(row["integration_id"]),
        tenant_id=row["tenant_id"],
        client_id=row["client_id"],
        site_url=row["site_url"],
        site_id=row["site_id"],
        site_display_name=row["site_display_name"],
        excluded_library_names=list(_json_value(row["excluded_library_names"])),
    )


async def get_sharepoint(session: AsyncSession, integration_id: int) -> SharePointRow | None:
    """Wiersz SharePoint po ``integration_id``; ``None`` gdy brak (kontrakt E4-2b)."""
    row = (
        (await session.execute(_GET_SHAREPOINT_SQL, {"integration_id": integration_id}))
        .mappings()
        .first()
    )
    return None if row is None else _sharepoint_row(row)


async def upsert_sharepoint(  # noqa: PLR0913 — kształt kontraktu E4-2b
    session: AsyncSession,
    *,
    integration_id: int,
    tenant_id: str,
    client_id: str,
    site_url: str,
    site_id: str | None = None,
    site_display_name: str | None = None,
    excluded_library_names: list[str] | None = None,
) -> None:
    """Wstawia wiersz SharePoint lub nadpisuje wszystkie kolumny po kluczu (kontrakt E4-2b)."""
    await session.execute(
        _UPSERT_SHAREPOINT_SQL,
        {
            "integration_id": integration_id,
            "tenant_id": tenant_id,
            "client_id": client_id,
            "site_url": site_url,
            "site_id": site_id,
            "site_display_name": site_display_name,
            "excluded_library_names": json.dumps(
                excluded_library_names if excluded_library_names is not None else [],
                ensure_ascii=False,
            ),
        },
    )


async def delete_sharepoint(session: AsyncSession, integration_id: int) -> bool:
    """Usuwa wiersz SharePoint po ``integration_id``; ``rowcount == 1`` (kontrakt E4-2b)."""
    result = await session.execute(_DELETE_SHAREPOINT_SQL, {"integration_id": integration_id})
    return _rowcount(result) == 1


async def set_secret(
    session: AsyncSession,
    integration_id: int,
    *,
    secret_enc: str,
    secret_last4: str,
    now_ms: int,
) -> bool:
    """Zapisuje zaszyfrowany sekret i ``updated_at`` integracji; ``rowcount == 1`` (E4-2b)."""
    result = await session.execute(
        _SET_SECRET_SQL,
        {
            "id": integration_id,
            "secret_enc": secret_enc,
            "secret_last4": secret_last4,
            "now_ms": now_ms,
        },
    )
    return _rowcount(result) == 1
