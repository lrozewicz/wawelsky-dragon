"""Konfigurowalne URL SharePoint w `Settings` — kontrakt C1 (brief T1).

Przykłady wejście → wyjście z briefu przepisane dosłownie.
"""

import os

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.integrations.sharepoint.auth import LOGIN_BASE_URL
from app.integrations.sharepoint.graph import GRAPH_BASE_URL

DEFAULT_LOGIN_BASE_URL = "https://login.microsoftonline.com"
DEFAULT_GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
FAKE_GRAPH_URL = "http://fake-graph:8095/v1.0"
FAKE_GRAPH_ORIGIN = "http://fake-graph:8095"


@pytest.fixture(autouse=True)
def _clean_wd_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Izolacja od env procesu (verify.sh eksportuje WD_* itd.)."""
    for name in [key for key in os.environ if key.startswith("WD_")]:
        monkeypatch.delenv(name, raising=False)


def test_defaults_match_production_constants() -> None:
    """Domyślne `Settings` są równe stałym produkcyjnym konektora (kontrakt C1)."""
    settings = Settings(env="dev")

    assert settings.sp_login_base_url == DEFAULT_LOGIN_BASE_URL == LOGIN_BASE_URL
    assert settings.sp_graph_base_url == DEFAULT_GRAPH_BASE_URL == GRAPH_BASE_URL


def test_custom_graph_url_is_accepted() -> None:
    """Adres bez końcowego `/` (stub Graph) jest poprawną wartością."""
    settings = Settings(env="dev", sp_graph_base_url=FAKE_GRAPH_URL)

    assert settings.sp_graph_base_url == FAKE_GRAPH_URL


@pytest.mark.parametrize(
    "value",
    ["ftp://x", "http://x/", "graph.microsoft.com", "https://x/v1.0/"],
)
def test_invalid_urls_are_rejected(value: str) -> None:
    """Schemat inny niż http(s) albo końcowy `/` → `ValidationError` (kontrakt C1)."""
    with pytest.raises(ValidationError, match="must start with http"):
        Settings(env="dev", sp_login_base_url=value)
    with pytest.raises(ValidationError, match="must start with http"):
        Settings(env="dev", sp_graph_base_url=value)


def test_error_message_names_the_env_var() -> None:
    """Komunikat błędu wskazuje nazwę zmiennej środowiskowej pola."""
    with pytest.raises(ValidationError, match="WD_SP_GRAPH_BASE_URL"):
        Settings(env="dev", sp_graph_base_url="ftp://x")


def test_env_vars_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """`WD_SP_*_BASE_URL` nadpisują domyślne wartości (brief T1, wymaganie 4)."""
    monkeypatch.setenv("WD_SP_GRAPH_BASE_URL", FAKE_GRAPH_URL)
    monkeypatch.setenv("WD_SP_LOGIN_BASE_URL", FAKE_GRAPH_ORIGIN)

    settings = Settings(env="dev")

    assert settings.sp_graph_base_url == FAKE_GRAPH_URL
    assert settings.sp_login_base_url == FAKE_GRAPH_ORIGIN
