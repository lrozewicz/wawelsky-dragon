"""Konfiguracja konektora SharePoint (kontrakt E4-2b, 09 §3/§11).

Budowana przez loader z wiersza `integrations` + `integration_sharepoint`; `client_secret`
nigdy nie wycieka do `repr`/`str`/`model_dump` (pydantic `SecretStr`).
"""

from pydantic import BaseModel, ConfigDict, SecretStr


class IntegrationConfigError(Exception):
    """Brak wiersza konfiguracji integracji albo brak sekretu; komunikat bez sekretu."""


class SharePointConfig(BaseModel):
    """Niezmienna konfiguracja konektora SharePoint (pydantic v2)."""

    model_config = ConfigDict(frozen=True)

    integration_id: int
    tenant_id: str
    client_id: str
    client_secret: SecretStr
    site_url: str
    site_id: str | None = None
    excluded_library_names: list[str] = []
    max_file_size_bytes: int
