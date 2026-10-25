"""Testy loadera konfiguracji SharePoint na prawdziwej MariaDB (brief T2, kontrakt E4-2b)."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.core.errors import ValidationFailed
from app.db.repositories import integrations as integrations_repo
from app.db.repositories.integrations import get_integration, set_secret, upsert_sharepoint
from app.db.uow import transaction
from app.integrations.secrets import encrypt_secret
from app.integrations.sharepoint.config import IntegrationConfigError, SharePointConfig
from app.integrations.sharepoint.loader import make_load_config
from tests.fakes.clock import FrozenClock
from tests.integration.integrations.conftest import TIME_MS, seed_dataset_and_user

pytestmark = pytest.mark.db

SM = async_sessionmaker[AsyncSession]

CRYPTO_KEY = "ab" * 32
SECRET = "s3cret"  # noqa: S105 — sekret wyłącznie testowy
OTHER_INTEGRATION_ID = 424_242
TENANT_ID = "contoso.onmicrosoft.com"
CLIENT_ID = "client-1"
SITE_URL = "https://contoso.sharepoint.com/sites/eng"
SITE_ID = "contoso.sharepoint.com,aaa,bbb"
EXCLUDED = ["Obrazy", "Archiwum"]
DEFAULT_MAX_FILE_SIZE = 209_715_200
OVERRIDE_MAX_FILE_SIZE = 4096


@pytest.fixture
async def sp_container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener z kluczem szyfrującym (w `test` Settings dopuszcza pusty WD_CRYPTO_KEY)."""
    instance = Container(
        migrated_db.model_copy(
            update={"storage_root": str(tmp_path), "crypto_key": SecretStr(CRYPTO_KEY)}
        ),
        clock=FrozenClock(TIME_MS),
    )
    await instance.start()
    yield instance
    await instance.aclose()


async def _insert_integration(sm: SM, *, max_file_size_bytes: int = DEFAULT_MAX_FILE_SIZE) -> int:
    """Wstawia integrację typu `sharepoint` (bez wiersza SP i sekretu)."""
    owner_id, dataset_id = await seed_dataset_and_user(sm)
    async with transaction(sm) as session:
        return await integrations_repo.insert_integration(
            session,
            type="sharepoint",
            name="SP test",
            dataset_id=dataset_id,
            owner_id=owner_id,
            config={},
            now_ms=TIME_MS,
            max_file_size_bytes=max_file_size_bytes,
        )


async def _attach_row(sm: SM, integration_id: int) -> None:
    """Dokłada wiersz `integration_sharepoint` do integracji."""
    async with transaction(sm) as session:
        await upsert_sharepoint(
            session,
            integration_id=integration_id,
            tenant_id=TENANT_ID,
            client_id=CLIENT_ID,
            site_url=SITE_URL,
            site_id=SITE_ID,
            site_display_name="Engineering",
            excluded_library_names=EXCLUDED,
        )


async def _attach_secret(sm: SM, integration_id: int, *, for_id: int | None = None) -> None:
    """Zapisuje sekret `SECRET` zaszyfrowany dla `for_id` (domyślnie dla tej integracji)."""
    enc, last4 = encrypt_secret(CRYPTO_KEY, for_id or integration_id, SECRET)
    async with transaction(sm) as session:
        await set_secret(
            session,
            integration_id,
            secret_enc=enc,
            secret_last4=last4,
            now_ms=TIME_MS,
        )


async def _load(container: Container, sm: SM, integration_id: int) -> object:
    """Woła loader na aktualnym wierszu integracji."""
    async with transaction(sm) as session:
        row = await get_integration(session, integration_id)
    assert row is not None
    return await make_load_config(container)(row)


async def test_load_builds_config(sm: SM, sp_container: Container) -> None:
    """Wiersz SP + sekret → cfg z odszyfrowanym sekretem i polami wiersza (kontrakt E4-2b)."""
    integration_id = await _insert_integration(sm, max_file_size_bytes=OVERRIDE_MAX_FILE_SIZE)
    await _attach_row(sm, integration_id)
    await _attach_secret(sm, integration_id)

    cfg = await _load(sp_container, sm, integration_id)

    assert isinstance(cfg, SharePointConfig)
    assert cfg.integration_id == integration_id
    assert cfg.tenant_id == TENANT_ID
    assert cfg.client_id == CLIENT_ID
    assert cfg.client_secret.get_secret_value() == SECRET
    assert cfg.site_url == SITE_URL
    assert cfg.site_id == SITE_ID
    assert cfg.excluded_library_names == EXCLUDED
    assert cfg.max_file_size_bytes == OVERRIDE_MAX_FILE_SIZE


async def test_load_missing_row_raises(sm: SM, sp_container: Container) -> None:
    """Brak wiersza SP → IntegrationConfigError, komunikat bez sekretu (kontrakt E4-2b)."""
    integration_id = await _insert_integration(sm)
    await _attach_secret(sm, integration_id)

    with pytest.raises(IntegrationConfigError) as excinfo:
        await _load(sp_container, sm, integration_id)

    assert str(excinfo.value) == "SharePoint configuration missing"
    assert SECRET not in str(excinfo.value)


async def test_load_missing_secret_raises(sm: SM, sp_container: Container) -> None:
    """Brak sekretu → IntegrationConfigError, komunikat bez sekretu (kontrakt E4-2b)."""
    integration_id = await _insert_integration(sm)
    await _attach_row(sm, integration_id)

    with pytest.raises(IntegrationConfigError) as excinfo:
        await _load(sp_container, sm, integration_id)

    assert str(excinfo.value) == "SharePoint secret missing"
    assert SECRET not in str(excinfo.value)


async def test_load_secret_for_other_integration_raises(sm: SM, sp_container: Container) -> None:
    """Sekret zaszyfrowany dla innego `id` → ValidationFailed bez treści sekretu (E4-2b)."""
    integration_id = await _insert_integration(sm)
    await _attach_row(sm, integration_id)
    await _attach_secret(sm, integration_id, for_id=OTHER_INTEGRATION_ID)

    with pytest.raises(ValidationFailed) as excinfo:
        await _load(sp_container, sm, integration_id)

    assert SECRET not in str(excinfo.value)
