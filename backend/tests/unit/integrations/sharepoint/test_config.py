"""Testy SharePointConfig i IntegrationConfigError (WP E4-2b, kontrakt config.py)."""

import pytest
from pydantic import SecretStr, ValidationError

from app.integrations.sharepoint.config import IntegrationConfigError, SharePointConfig

SECRET = "s3cret"  # noqa: S105 — sekret wyłącznie testowy
INTEGRATION_ID = 7
MAX_FILE_SIZE_BYTES = 1024


def make_config() -> SharePointConfig:
    return SharePointConfig(
        integration_id=INTEGRATION_ID,
        tenant_id="tenant-1",
        client_id="client-1",
        client_secret=SecretStr(SECRET),
        site_url="https://contoso.sharepoint.com/sites/team",
        max_file_size_bytes=MAX_FILE_SIZE_BYTES,
    )


def test_defaults() -> None:
    cfg = make_config()
    assert cfg.site_id is None
    assert cfg.excluded_library_names == []


def test_fields() -> None:
    cfg = make_config()
    assert cfg.integration_id == INTEGRATION_ID
    assert cfg.tenant_id == "tenant-1"
    assert cfg.client_id == "client-1"
    assert cfg.site_url == "https://contoso.sharepoint.com/sites/team"
    assert cfg.max_file_size_bytes == MAX_FILE_SIZE_BYTES
    assert cfg.client_secret.get_secret_value() == SECRET


def test_secret_hidden_in_repr_and_str() -> None:
    cfg = make_config()
    assert SECRET not in repr(cfg)
    assert SECRET not in str(cfg)


def test_secret_hidden_in_model_dump_json() -> None:
    assert SECRET not in make_config().model_dump_json()


def test_frozen() -> None:
    cfg = make_config()
    with pytest.raises(ValidationError):
        cfg.site_url = "https://other"  # type: ignore[misc]


def test_config_error_message_without_secret() -> None:
    error = IntegrationConfigError("SharePoint configuration missing")
    assert str(error) == "SharePoint configuration missing"
    assert SECRET not in str(error)
