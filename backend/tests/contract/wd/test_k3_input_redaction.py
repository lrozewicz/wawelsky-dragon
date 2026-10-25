"""K3 §5: błąd walidacji nie echuje ciała żądania — sekretu brak w każdej przestrzeni.

Wniosek TL E4-3b (DEC-082): elementy ``details.errors`` niosły ``input`` Pydantic, a przy błędzie
``missing`` jest to **całe ciało** żądania (plaintext sekretów). Po zmianie 14 (K3 §5) robi to
globalny handler ``app/api/errors.py``: w ``wd`` i przestrzeni domyślnej ``input`` wypada zawsze,
a w ``ragflow`` wartość ``Value:`` jest redagowana.

Jedno żądanie na przestrzeń (brak pola wymaganego + pole sekretu w ciele) → wartość sekretu nie
występuje w ``response.text``. ``wd``/``hub-compat``/``ragflow`` idą realnymi trasami aplikacji
(fixture'y z ``tests.contract.wd.admin_support`` przez ``tests/contract/wd/conftest.py``),
a przestrzeń domyślna — syntetyczną trasą pod ``/x``, bo aplikacja nie ma produkcyjnej trasy
z ciałem poza tabelą K3 §3.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.api.errors import install_error_handlers
from tests.contract.wd.admin_support import SVC_SECRET

pytestmark = pytest.mark.contract

BAD_REQUEST = 400
OK = 200

CLIENT_SECRET = "s3cr3t-abcd"  # noqa: S105 — sekret wyłącznie testowy
RAGFLOW_PASSWORD = "r4gflow-pass"  # noqa: S105 — hasło wyłącznie testowe
HUB_COMPAT_PASSWORD = "hub-compat-pass"  # noqa: S105 — hasło wyłącznie testowe
DEFAULT_PASSWORD = "default-pass"  # noqa: S105 — hasło wyłącznie testowe
CLAIM_SECRET = "claim-secret"  # noqa: S105 — sekret wyłącznie testowy

DEFAULT_PATH = "/x"
RAGFLOW_PATH = "/api/v1/k3"


class _DefaultBody(BaseModel):
    """Ciało trasy poza tabelą K3 §3 (przestrzeń domyślna)."""

    name: str
    password: str


class _ClaimBody(BaseModel):
    """Ciało syntetycznej trasy ``ragflow`` z polem wymaganym i sekretem."""

    name: str
    password: str


def _default_client() -> TestClient:
    """Aplikacja z jedną trasą pod ``/x`` (przestrzeń domyślna) i handlerami K3."""
    app = FastAPI()
    install_error_handlers(app)

    @app.post(DEFAULT_PATH)
    async def _handler(body: _DefaultBody) -> dict[str, str]:
        return {"ok": body.name}

    return TestClient(app)


def _ragflow_client() -> TestClient:
    """Aplikacja z jedną trasą pod ``/api/v1`` (przestrzeń ``ragflow``) i handlerami K3."""
    app = FastAPI()
    install_error_handlers(app)

    @app.post(RAGFLOW_PATH)
    async def _handler(body: _ClaimBody) -> dict[str, str]:
        return {"ok": body.name}

    return TestClient(app)


async def test_wd_validation_error_does_not_echo_the_body(admin: httpx.AsyncClient) -> None:
    """``wd``: brak ``name`` + ``client_secret`` → 400 bez ``input`` i bez wartości sekretu."""
    body = {
        "type": "sharepoint",
        "dataset_id": "a" * 32,
        "tenant_id": "t-tenant",
        "client_id": "c-client",
        "client_secret": CLIENT_SECRET,
        "site_url": "https://contoso.sharepoint.com/sites/eng",
    }

    response = await admin.post("/api/wd/v1/integrations", json=body)

    assert response.status_code == BAD_REQUEST, response.text
    assert CLIENT_SECRET not in response.text
    first = response.json()["error"]["details"]["errors"][0]
    assert first["type"] == "missing"
    assert "input" not in first


async def test_ragflow_validation_error_does_not_echo_the_password(app: FastAPI) -> None:
    """``ragflow``: rejestracja bez ``nickname`` z ``password`` → hasła brak w odpowiedzi."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/users", json={"email": "k3@example.com", "password": RAGFLOW_PASSWORD}
        )

    assert RAGFLOW_PASSWORD not in response.text


async def test_hub_compat_validation_error_does_not_echo_the_password(app: FastAPI) -> None:
    """``hub-compat``: ``POST /api/users`` bez ``email``, z ``password`` → hasła brak
    w odpowiedzi."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Secret": SVC_SECRET},
    ) as client:
        response = await client.post("/api/users", json={"password": HUB_COMPAT_PASSWORD})

    assert response.status_code == BAD_REQUEST, response.text
    assert HUB_COMPAT_PASSWORD not in response.text


def test_default_validation_error_does_not_echo_the_password() -> None:
    """Przestrzeń domyślna: trasa ``/x`` bez ``name``, z ``password`` → 400 bez echa sekretu."""
    response = _default_client().post(DEFAULT_PATH, json={"password": DEFAULT_PASSWORD})

    assert response.status_code == BAD_REQUEST, response.text
    assert DEFAULT_PASSWORD not in response.text
    first = response.json()["error"]["details"]["errors"][0]
    assert "input" not in first


def test_ragflow_validation_error_redacts_container_input() -> None:
    """``ragflow`` z ``input``-kontenerem: ``Value:`` pokazuje klucze, nie wartości (K3 §5)."""
    response = _ragflow_client().post(RAGFLOW_PATH, json={"password": CLAIM_SECRET})

    assert response.status_code == OK, response.text
    assert CLAIM_SECRET not in response.text
    assert response.json()["message"].endswith("Value: {'password': '***'}")
