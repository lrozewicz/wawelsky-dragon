"""Loader konfiguracji SharePoint: wiersz `integrations` + `integration_sharepoint` (E4-2b).

Sesję bierze z `container.sessionmaker` w chwili wywołania; sekret odszyfrowuje kluczem
`container.settings.crypto_key`, więc nigdy nie trafia do logu ani komunikatu wyjątku.
"""

from typing import cast

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.container import Container
from app.db.repositories.integrations import IntegrationRow, get_sharepoint
from app.db.uow import transaction
from app.integrations.registry import ConfigLoader
from app.integrations.secrets import decrypt_secret
from app.integrations.sharepoint.config import IntegrationConfigError, SharePointConfig


def make_load_config(container: Container) -> ConfigLoader:
    """Zwraca loader `IntegrationRow` → `SharePointConfig` (kontrakt E4-2b)."""

    async def load(row: IntegrationRow) -> SharePointConfig:
        sessionmaker = cast("async_sessionmaker[AsyncSession]", container.sessionmaker)
        async with transaction(sessionmaker) as session:
            sharepoint = await get_sharepoint(session, row.id)
        if sharepoint is None:
            raise IntegrationConfigError("SharePoint configuration missing")
        if row.secret_enc is None:
            raise IntegrationConfigError("SharePoint secret missing")
        secret = decrypt_secret(
            container.settings.crypto_key.get_secret_value(), row.id, row.secret_enc
        )
        return SharePointConfig(
            integration_id=row.id,
            tenant_id=sharepoint.tenant_id,
            client_id=sharepoint.client_id,
            client_secret=SecretStr(secret),
            site_url=sharepoint.site_url,
            site_id=sharepoint.site_id,
            excluded_library_names=sharepoint.excluded_library_names,
            max_file_size_bytes=row.max_file_size_bytes,
        )

    return load
