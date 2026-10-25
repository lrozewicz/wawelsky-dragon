"""Redakcja ``input`` w błędach walidacji przestrzeni ``wd`` (K3 §5, errata zmiany 14).

Kopertę i redakcję robi wyłącznie globalny handler K3 (``app/api/errors.py``): dla ``wd``
(elementy ``details.errors``) i przestrzeni domyślnej wypadają ``ctx``, ``url`` oraz ``input``.
Klasa trasy ``WdRoute`` (DEC-082) zniknęła — ten test pilnuje zachowania handlera na trasie
z prawdziwym modelem żądania z ``integrations/schemas.py`` (bez bazy).
"""

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.api.errors import install_error_handlers
from app.api.wd.integrations.schemas import ConnectionTestRequest, IntegrationCreateRequest

BAD_REQUEST = 400
OK = 200

CLIENT_SECRET = "s3cr3t-abcd"  # noqa: S105 — sekret wyłącznie testowy
VALIDATION_FAILED = "validation_failed"


def make_client() -> TestClient:
    """Klient na syntetycznej aplikacji WD: ten sam handler K3 i prefiks ``/api/wd/v1``."""
    app = FastAPI()
    install_error_handlers(app)
    router = APIRouter(prefix="/api/wd/v1")

    @router.post("/integrations")
    async def create(body: IntegrationCreateRequest) -> dict[str, object]:
        """Trasa syntetyczna create (ciało z ``client_secret``)."""
        return {"data": body.model_dump()}

    @router.post("/integrations/test")
    async def test_connection(body: ConnectionTestRequest) -> dict[str, object]:
        """Trasa syntetyczna testu połączenia (ciało z ``client_secret``)."""
        return {"data": body.model_dump()}

    app.include_router(router)
    return TestClient(app)


def create_body(**over: object) -> dict[str, object]:
    """Poprawne ciało create; ``over`` nadpisuje/dokłada pola."""
    body: dict[str, object] = {
        "type": "sharepoint",
        "name": "SP test",
        "dataset_id": "a" * 32,
        "tenant_id": "t-tenant",
        "client_id": "c-client",
        "client_secret": CLIENT_SECRET,
        "site_url": "https://contoso.sharepoint.com/sites/eng",
    }
    body.update(over)
    return body


def test_valid_body_still_reaches_the_route() -> None:
    """Kontrola: redakcja nie psuje ścieżki sukcesu — poprawne ciało daje 200 z ``data``."""
    response = make_client().post("/api/wd/v1/integrations", json=create_body())

    assert response.status_code == OK, response.text
    assert response.json()["data"]["client_secret"] == CLIENT_SECRET


def test_missing_field_does_not_leak_secret_into_input() -> None:
    """Brak ``type`` → ``missing``, ale ``input`` (całe ciało z sekretem) wypada z odpowiedzi."""
    body = create_body()
    del body["type"]

    response = make_client().post("/api/wd/v1/integrations", json=body)

    assert response.status_code == BAD_REQUEST, response.text
    assert CLIENT_SECRET not in response.text
    error = response.json()["error"]
    assert error["code"] == VALIDATION_FAILED
    first = error["details"]["errors"][0]
    assert first["type"] == "missing"
    assert "input" not in first


def test_missing_field_is_redacted_for_connection_test() -> None:
    """To samo dla ``POST /integrations/test`` (drugi model żądania WD)."""
    body = create_body()
    del body["type"]

    response = make_client().post("/api/wd/v1/integrations/test", json=body)

    assert response.status_code == BAD_REQUEST, response.text
    assert CLIENT_SECRET not in response.text
    assert "input" not in response.json()["error"]["details"]["errors"][0]


def test_redaction_removes_scalar_input_too() -> None:
    """K3 §5: ``input`` wypada zawsze — także gdy niesie wartość skalarną wadliwego pola."""
    response = make_client().post(
        "/api/wd/v1/integrations", json=create_body(scan_interval_seconds="x")
    )

    assert response.status_code == BAD_REQUEST, response.text
    first = response.json()["error"]["details"]["errors"][0]
    assert "input" not in first
    assert CLIENT_SECRET not in response.text


def test_non_object_body_is_redacted() -> None:
    """Ciało-liśta → ``model_attributes_type`` z ``input`` = lista (z sekretem) → wypada."""
    response = make_client().post("/api/wd/v1/integrations", json=[create_body()])

    assert response.status_code == BAD_REQUEST, response.text
    assert CLIENT_SECRET not in response.text
    first = response.json()["error"]["details"]["errors"][0]
    assert first["type"] == "model_attributes_type"
    assert "input" not in first
