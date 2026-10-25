"""Testy repozytorium `integration_sharepoint` na prawdziwej MariaDB (brief T2, kontrakt E4-2b)."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories.integrations import (
    IntegrationRow,
    SharePointRow,
    delete_sharepoint,
    get_integration,
    get_sharepoint,
    set_secret,
    upsert_sharepoint,
)
from app.db.uow import transaction
from tests.integration.integrations.conftest import TIME_MS, make_integration

pytestmark = pytest.mark.db

SM = async_sessionmaker[AsyncSession]

TENANT_ID = "contoso.onmicrosoft.com"
CLIENT_ID = "client-1"
SITE_URL = "https://contoso.sharepoint.com/sites/eng"
SITE_ID = "contoso.sharepoint.com,aaa,bbb"
SITE_NAME = "Engineering"
EXCLUDED = ["Obrazy", "Archiwum"]
UPDATED_CLIENT_ID = "client-2"
UPDATED_EXCLUDED = ["Nowa biblioteka"]
SECRET_ENC = "v1:bm9uY2U=:Ym9keQ=="  # noqa: S105 — szyfrogram wyłącznie testowy
SECRET_LAST4 = "c123"  # noqa: S105 — ostatnie 4 znaki sekretu testowego
SECRET_NOW_MS = TIME_MS + 1000


async def _get(sm: SM, integration_id: int) -> SharePointRow | None:
    async with transaction(sm) as session:
        return await get_sharepoint(session, integration_id)


async def _upsert(sm: SM, **kwargs: object) -> None:
    async with transaction(sm) as session:
        await upsert_sharepoint(session, **kwargs)


async def _delete(sm: SM, integration_id: int) -> bool:
    async with transaction(sm) as session:
        return await delete_sharepoint(session, integration_id)


async def _set_secret(sm: SM, integration_id: int) -> bool:
    async with transaction(sm) as session:
        return await set_secret(
            session,
            integration_id,
            secret_enc=SECRET_ENC,
            secret_last4=SECRET_LAST4,
            now_ms=SECRET_NOW_MS,
        )


async def _integration(sm: SM, integration_id: int) -> IntegrationRow | None:
    async with transaction(sm) as session:
        return await get_integration(session, integration_id)


def _row_fields(integration_id: int) -> dict[str, object]:
    """Pełny zestaw kolumn wiersza SP (kontrakt E4-2b)."""
    return {
        "integration_id": integration_id,
        "tenant_id": TENANT_ID,
        "client_id": CLIENT_ID,
        "site_url": SITE_URL,
        "site_id": SITE_ID,
        "site_display_name": SITE_NAME,
        "excluded_library_names": EXCLUDED,
    }


async def test_upsert_then_get(sm: SM) -> None:
    """Upsert wstawia wiersz; get zwraca wszystkie kolumny (kontrakt E4-2b)."""
    integration_id = await make_integration(sm)
    await _upsert(sm, **_row_fields(integration_id))

    row = await _get(sm, integration_id)

    assert row == SharePointRow(
        integration_id=integration_id,
        tenant_id=TENANT_ID,
        client_id=CLIENT_ID,
        site_url=SITE_URL,
        site_id=SITE_ID,
        site_display_name=SITE_NAME,
        excluded_library_names=EXCLUDED,
    )


async def test_upsert_overrides_all_columns(sm: SM) -> None:
    """Ponowny upsert nadpisuje każdą kolumnę poza kluczem (kontrakt E4-2b)."""
    integration_id = await make_integration(sm)
    await _upsert(sm, **_row_fields(integration_id))
    await _upsert(
        sm,
        integration_id=integration_id,
        tenant_id="other.onmicrosoft.com",
        client_id=UPDATED_CLIENT_ID,
        site_url="https://other.sharepoint.com/sites/nowy",
        site_id=None,
        site_display_name=None,
        excluded_library_names=UPDATED_EXCLUDED,
    )

    row = await _get(sm, integration_id)

    assert row == SharePointRow(
        integration_id=integration_id,
        tenant_id="other.onmicrosoft.com",
        client_id=UPDATED_CLIENT_ID,
        site_url="https://other.sharepoint.com/sites/nowy",
        site_id=None,
        site_display_name=None,
        excluded_library_names=UPDATED_EXCLUDED,
    )


async def test_upsert_defaults_empty_excluded(sm: SM) -> None:
    """Brak `excluded_library_names` → pusta lista (kontrakt E4-2b)."""
    integration_id = await make_integration(sm)
    await _upsert(
        sm,
        integration_id=integration_id,
        tenant_id=TENANT_ID,
        client_id=CLIENT_ID,
        site_url=SITE_URL,
    )

    row = await _get(sm, integration_id)

    assert row is not None
    assert row.excluded_library_names == []
    assert row.site_id is None
    assert row.site_display_name is None


async def test_get_missing_returns_none(sm: SM) -> None:
    """Brak wiersza SP → None (kontrakt E4-2b)."""
    integration_id = await make_integration(sm)

    assert await _get(sm, integration_id) is None


async def test_delete_returns_rowcount(sm: SM) -> None:
    """Delete zwraca True raz i False przy ponowieniu (kontrakt E4-2b)."""
    integration_id = await make_integration(sm)
    await _upsert(sm, **_row_fields(integration_id))

    assert await _delete(sm, integration_id) is True
    assert await _get(sm, integration_id) is None
    assert await _delete(sm, integration_id) is False


async def test_delete_cascades_with_integration(sm: SM) -> None:
    """Usunięcie wiersza `integrations` kasuje wiersz SP (ON DELETE CASCADE)."""
    integration_id = await make_integration(sm)
    await _upsert(sm, **_row_fields(integration_id))

    async with transaction(sm) as session:
        await session.execute(
            text("DELETE FROM integrations WHERE id = :id"), {"id": integration_id}
        )

    assert await _get(sm, integration_id) is None


async def test_set_secret_stores_enc_and_last4(sm: SM) -> None:
    """`set_secret` zapisuje `secret_enc`/`secret_last4` i `updated_at` (kontrakt E4-2b)."""
    integration_id = await make_integration(sm)

    assert await _set_secret(sm, integration_id) is True

    row = await _integration(sm, integration_id)
    assert row is not None
    assert row.secret_enc == SECRET_ENC
    assert row.secret_last4 == SECRET_LAST4
    assert row.updated_at == SECRET_NOW_MS


async def test_set_secret_missing_integration(sm: SM) -> None:
    """`set_secret` dla nieistniejącej integracji → False (kontrakt E4-2b)."""
    integration_id = await make_integration(sm)

    assert await _set_secret(sm, integration_id + 1) is False
