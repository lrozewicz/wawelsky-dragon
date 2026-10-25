"""Testy profilu zgodności (C7) — wzór: tests/unit/api/test_principal.py.

Mała aplikacja FastAPI + install_error_handlers, preset principal w middleware,
fałszywy kontener (settings + api_keys) w app.state.container. Trasa pod /api/v1,
żeby błędy szły w kopertę ragflow.
"""

from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.api.auth.principal import PrincipalDep
from app.api.errors import install_error_handlers
from app.api.ragflow.compat import CompatDep
from app.core.error_codes import RetCode
from app.domain.policy import Principal

# Domyślna ustawiona na "ragflow_0_24", by odróżnić fallback od wartości jwt/wymuszonych.
DEFAULT_PROFILE = "ragflow_0_24"
KEY_ID = "key-1"
_OK = 200


class FakeApiKeys:
    """Podstawka container.api_keys — profil z definicji słownika."""

    def __init__(self, profiles: dict[str, str | None]) -> None:
        self.profiles = profiles
        self.asked: list[str] = []

    async def compat_profile(self, api_key_id: str) -> str | None:
        self.asked.append(api_key_id)
        return self.profiles.get(api_key_id)


def make_client(
    principal: Principal, profiles: dict[str, str | None] | None = None
) -> tuple[TestClient, FakeApiKeys]:
    """Aplikacja z trasą /api/v1/probe i podstawionym kontenerem (brief)."""
    app = FastAPI()
    install_error_handlers(app)
    fake = FakeApiKeys(profiles or {})
    app.state.container = SimpleNamespace(
        settings=SimpleNamespace(api_compat_default=DEFAULT_PROFILE), api_keys=fake
    )

    @app.middleware("http")
    async def preset_principal(request: Request, call_next):
        request.state.principal = principal
        return await call_next(request)

    @app.get("/api/v1/probe")
    async def probe(principal: PrincipalDep, compat: CompatDep) -> dict[str, str]:
        return {"profile": compat}

    return TestClient(app), fake


def api_key_principal() -> Principal:
    """Principal klucza API z api_key_id (ten sam klucz w fake'u)."""
    return Principal("u-1", "jan@x.pl", False, False, "api_key", api_key_id=KEY_ID)


def test_jwt_returns_0_27_even_with_compat_header() -> None:
    """jwt → zawsze ragflow_0_27, przed nagłówkiem i usługą (C7)."""
    client, fake = make_client(Principal("u-1", "j@x.pl", False, False, "jwt"))
    response = client.get("/api/v1/probe", headers={"X-RAGFlow-Compat": "0.24"})
    assert response.status_code == _OK
    assert response.json() == {"profile": "ragflow_0_27"}
    assert fake.asked == []


def test_session_cookie_returns_0_27() -> None:
    """session_cookie → ragflow_0_27."""
    client, _ = make_client(Principal("u-1", "j@x.pl", False, False, "session_cookie"))
    assert client.get("/api/v1/probe").json() == {"profile": "ragflow_0_27"}


def test_header_wins_over_key_profile() -> None:
    """api_key + nagłówek 0.24 → ragflow_0_24 mimo klucza z ragflow_0_27; usługa nie wołana."""
    client, fake = make_client(api_key_principal(), {KEY_ID: "ragflow_0_27"})
    response = client.get("/api/v1/probe", headers={"X-RAGFlow-Compat": "0.24"})
    assert response.json() == {"profile": "ragflow_0_24"}
    assert fake.asked == []


def test_query_wins_over_key_profile() -> None:
    """api_key, brak nagłówka, query compat=0.27 → ragflow_0_27 mimo klucza ragflow_0_24."""
    client, fake = make_client(api_key_principal(), {KEY_ID: "ragflow_0_24"})
    response = client.get("/api/v1/probe?compat=0.27")
    assert response.json() == {"profile": "ragflow_0_27"}
    assert fake.asked == []


def test_key_profile_used_when_no_header_or_query() -> None:
    """api_key bez nagłówka/query → profil klucza z usługi."""
    client, fake = make_client(api_key_principal(), {KEY_ID: "ragflow_0_24"})
    response = client.get("/api/v1/probe")
    assert response.json() == {"profile": "ragflow_0_24"}
    assert fake.asked == [KEY_ID]


def test_key_without_profile_falls_back_to_settings_default() -> None:
    """Usługa zwraca None → settings.api_compat_default (tu ragflow_0_24)."""
    client, fake = make_client(api_key_principal(), {KEY_ID: None})
    response = client.get("/api/v1/probe")
    assert response.json() == {"profile": DEFAULT_PROFILE}
    assert fake.asked == [KEY_ID]


def test_legacy_token_without_key_uses_settings_default() -> None:
    """legacy_token bez api_key_id → settings.api_compat_default."""
    client, fake = make_client(Principal("u-1", "j@x.pl", False, False, "legacy_token"))
    response = client.get("/api/v1/probe")
    assert response.json() == {"profile": DEFAULT_PROFILE}
    assert fake.asked == []


def test_unknown_header_value_is_ragflow_101_envelope() -> None:
    """Nagłówek '1.0' → ValidationFailed: HTTP 200, kod 101 w kopercie ragflow."""
    client, _ = make_client(api_key_principal())
    response = client.get("/api/v1/probe", headers={"X-RAGFlow-Compat": "1.0"})
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == RetCode.ARGUMENT_ERROR
    assert body["message"] == "Invalid compat profile: 1.0. Expected '0.24' or '0.27'."


def test_unknown_query_value_is_ragflow_101_envelope() -> None:
    """Query 'compat=x' → ta sama walidacja co nagłówek."""
    client, _ = make_client(api_key_principal())
    response = client.get("/api/v1/probe?compat=x")
    assert response.json()["code"] == RetCode.ARGUMENT_ERROR


def test_compat_dep_annotation_resolves_profile() -> None:
    """CompatDep da się rozwiązać przez FastAPI (annotacja z Depends)."""
    client, _ = make_client(Principal("u-1", "j@x.pl", False, False, "jwt"))
    assert client.get("/api/v1/probe").status_code == _OK
