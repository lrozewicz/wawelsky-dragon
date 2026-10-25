"""Trasy legacy ``/v1/system/*``, ``/v1/api/stats``, ``/v1/llm/my_llms`` (brief E2-2a T3).

Trasy v0.24 wyłącznie (K11 §10d p. 17) pod krótkim prefiksem ``/v1``: część bez
uwierzytelnienia (``ping``, ``config``, alias ``healthz``), reszta z JWT legacy — nagłówkiem
``Authorization`` z logowania ``/api/v1/auth/login`` (jak krok ``auth: jwt`` harnessu).
Kształty kopert są zgodne ze złotem scenariusza ``system`` (kroki 16-25); test sprawdza
klucze i wartości istotne dla zachowania (liczba i typ pól, własność tokenów).

Test bezpieczeństwa (wymaganie 4 briefu): użytkownik B nie może usunąć tokenu użytkownika A
— odpowiedź to odmowa 108, a token A zostaje na liście A (CONTRACT C0 p. 9; upstream kasuje
cicho i oddaje sukces, WD odmawia).
"""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.core.container import Container
from app.main import create_app
from tests.integration.ingest.pipeline_helpers import make_container

pytestmark = pytest.mark.db

_OK = 200
_UNAUTHORIZED = 401
_CODE_SUCCESS = 0
_CODE_LACK_PERMISSION = 108
PASSWORD = "Secret-pass1"  # noqa: S105 — celowa atrapa hasła w teście

_A_EMAIL = "legacy-a@x.pl"
_B_EMAIL = "legacy-b@x.pl"

# Klucze kopert ze złota v0.24.0 scenariusza system (kroki 16-25).
_STATUS_KEYS = {
    "database",
    "doc_engine",
    "redis",
    "storage",
    "task_executor_heartbeats",
}
_TOKEN_KEYS = {
    "beta",
    "create_date",
    "create_time",
    "dialog_id",
    "source",
    "tenant_id",
    "token",
    "update_date",
    "update_time",
}
_CREATED_TOKEN_KEYS = {
    "beta",
    "create_date",
    "create_time",
    "tenant_id",
    "token",
    "update_date",
    "update_time",
}
_STATS_KEYS = {"pv", "round", "speed", "thumb_up", "tokens", "uv"}
_LLM_ENTRY_KEYS = {"name", "status", "type", "used_token"}
_FACTORY = "OpenAI-API-Compatible"


@pytest.fixture
def settings(auth_settings: Settings, tmp_path: Path) -> Settings:
    """Ustawienia auth + storage w katalogu tymczasowym (wzór briefu)."""
    return auth_settings.model_copy(update={"storage_root": str(tmp_path)})


@pytest.fixture
async def container(settings: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener testowy (modele fake-llm w rejestrze, storage w tmp_path)."""
    instance = await make_container(settings, tmp_path)
    yield instance
    await instance.aclose()


@pytest.fixture
def app(settings: Settings, container: Container) -> FastAPI:
    """Aplikacja na tym samym kontenerze co test (bez sieci, ASGITransport)."""
    return create_app(settings, container)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Klient ASGI; testy JWT używają nagłówka z logowania, nie klucza API."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def _create_user(container: Container, email: str) -> str:
    """Konto lokalne (bez admina); zwraca jego id."""
    assert container.users is not None
    user = await container.users.create(email=email, password=PASSWORD, is_superuser=False)
    return user.id


async def _login(client: httpx.AsyncClient, email: str) -> dict[str, str]:
    """Nagłówki JWT legacy z logowania (wartość nagłówka ``Authorization`` z odpowiedzi)."""
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == _OK, response.text
    assert response.json()["code"] == _CODE_SUCCESS
    return {"Authorization": response.headers["authorization"]}


def _data(response: httpx.Response) -> Any:
    """``data`` koperty sukcesu (HTTP 200, code 0)."""
    assert response.status_code == _OK, response.text
    payload = response.json()
    assert payload["code"] == _CODE_SUCCESS, payload
    return payload["data"]


async def _create_token(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    """Token właściciela przez ``POST /v1/system/new_token``."""
    created = cast(
        "dict[str, Any]", _data(await client.post("/v1/system/new_token", headers=headers))
    )
    assert set(created) == _CREATED_TOKEN_KEYS
    assert "name" not in created  # K20 §1: pola name nie ma w legacy v0.24
    return cast(str, created["token"])


async def _listed_tokens(client: httpx.AsyncClient, headers: dict[str, str]) -> list[str]:
    """Tokeny z ``GET /v1/system/token_list`` (kolejność jak zwraca usługa)."""
    listed = cast(
        "list[dict[str, Any]]", _data(await client.get("/v1/system/token_list", headers=headers))
    )
    for entry in listed:
        assert set(entry) == _TOKEN_KEYS
        assert "name" not in entry  # K20 §1: legacy v0.24 bez pola name (złoto system--21)
    return [cast(str, entry["token"]) for entry in listed]


async def test_public_routes_need_no_authorization(client: httpx.AsyncClient) -> None:
    """``ping``, ``config`` i alias ``healthz`` działają bez nagłówka (złoto 16, 18, 19)."""
    ping = await client.get("/v1/system/ping")
    assert ping.status_code == _OK
    assert ping.headers["content-type"] == "text/html; charset=utf-8"
    assert ping.text == "pong"

    config = await client.get("/v1/system/config")
    assert _data(config) == {"registerEnabled": 0}

    healthz = await client.get("/v1/system/healthz")
    assert healthz.status_code == _OK
    assert set(healthz.json()) == {"db", "doc_engine", "redis", "status", "storage"}


async def test_missing_authorization_in_v024_profile(client: httpx.AsyncClient) -> None:
    """Braki nagłówka na trasach JWT: 401 bez profilu, koperta v0.24 z nagłówkiem (§10d p. 14).

    Profil przy braku uwierzytelnienia bierze się z nagłówka/query — bez nich działa 0.27 (401).
    ``version`` jest na liście, bo upstream ma tam ``@login_required``, a scenariusz ``auth: jwt``.
    """
    for path in ("/v1/system/status", "/v1/system/version"):
        bare = await client.get(path)
        assert bare.status_code == _UNAUTHORIZED

        shim = await client.get(path, headers={"X-RAGFlow-Compat": "0.24"})
        assert shim.status_code == _OK
        assert shim.json() == {
            "code": _CODE_SUCCESS,
            "message": "`Authorization` can't be empty",
            "data": False,
        }


async def test_status_and_stats_shapes(client: httpx.AsyncClient, container: Container) -> None:
    """``version``, ``status`` i ``api/stats`` mają kształty złota (kroki 17, 20 i 24)."""
    await _create_user(container, _A_EMAIL)
    headers = await _login(client, _A_EMAIL)

    version = await client.get("/v1/system/version", headers=headers)
    assert _data(version) == "v0.24.0"

    status = cast("dict[str, Any]", _data(await client.get("/v1/system/status", headers=headers)))
    assert set(status) == _STATUS_KEYS
    assert set(cast("dict[str, Any]", status["database"])) == {"database", "elapsed", "status"}
    assert cast("dict[str, Any]", status["database"])["database"] == "mysql"
    assert set(cast("dict[str, Any]", status["storage"])) == {"elapsed", "status", "storage"}

    stats = cast("dict[str, Any]", _data(await client.get("/v1/api/stats", headers=headers)))
    assert set(stats) == _STATS_KEYS
    assert all(value == [] for value in stats.values())


async def test_token_list_create_delete_round_trip(
    client: httpx.AsyncClient, container: Container
) -> None:
    """Token założony przez ``new_token`` trafia na listę i daje się usunąć (kroki 21-23)."""
    await _create_user(container, _A_EMAIL)
    headers = await _login(client, _A_EMAIL)
    assert await _listed_tokens(client, headers) == []

    token = await _create_token(client, headers)
    assert token.startswith("ragflow-")
    assert await _listed_tokens(client, headers) == [token]

    removed = await client.delete(f"/v1/system/token/{token}", headers=headers)
    assert _data(removed) is True
    assert await _listed_tokens(client, headers) == []


async def test_my_llms_groups_models_by_factory(
    client: httpx.AsyncClient, container: Container
) -> None:
    """``my_llms``: jedna fabryka, wpisy z sufiksem fabryki i statusem "1" (krok 25)."""
    await _create_user(container, _A_EMAIL)
    headers = await _login(client, _A_EMAIL)

    body = cast("dict[str, Any]", _data(await client.get("/v1/llm/my_llms", headers=headers)))
    assert set(body) == {_FACTORY}
    factory = cast("dict[str, Any]", body[_FACTORY])
    assert set(factory) == {"llm", "tags"}
    llm = cast("list[dict[str, Any]]", factory["llm"])
    assert {entry["name"] for entry in llm} == {
        "fake-chat___OpenAI-API",
        "fake-embed-1024___OpenAI-API",
    }
    for entry in llm:
        assert set(entry) == _LLM_ENTRY_KEYS
        assert entry["status"] == "1"
        assert entry["used_token"] == 0


async def test_foreign_token_delete_is_refused_and_token_survives(
    client: httpx.AsyncClient, container: Container
) -> None:
    """B nie usuwa tokenu A: odmowa 108 i token A nadal na liście A (C0 p. 9, wymaganie 4)."""
    await _create_user(container, _A_EMAIL)
    await _create_user(container, _B_EMAIL)
    headers_a = await _login(client, _A_EMAIL)
    headers_b = await _login(client, _B_EMAIL)
    token_a = await _create_token(client, headers_a)

    response = await client.delete(f"/v1/system/token/{token_a}", headers=headers_b)
    assert response.status_code == _OK, response.text
    assert response.json() == {"code": _CODE_LACK_PERMISSION, "message": "You don't own the token."}

    assert await _listed_tokens(client, headers_a) == [token_a]
    assert await _listed_tokens(client, headers_b) == []


async def test_delete_unknown_token_is_refused(
    client: httpx.AsyncClient, container: Container
) -> None:
    """Token spoza rejestru właściciela też jest odmową — nigdy sukces (C0 p. 9)."""
    await _create_user(container, _A_EMAIL)
    headers = await _login(client, _A_EMAIL)

    response = await client.delete("/v1/system/token/ragflow-nie-ma-takiego", headers=headers)
    assert response.status_code == _OK
    assert response.json()["code"] == _CODE_LACK_PERMISSION
