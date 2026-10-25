"""Schemat OpenAPI i straż dostępu tras WD integracji (brief T2, kontrakt E4-3b §0 p. 6, §5).

W T2 routery WD są puste (trasy dokładają T3/T4), więc pilnujemy tu samego dokumentu: żadna
operacja pod ``/api/wd/v1`` nie deklaruje 422, a trasa resetu testowego nie trafia do schematu.
Test ``build_openapi`` na aplikacji syntetycznej sprawdza samą regułę usuwania 422 (nie jest
pusty dopiero wtedy, gdy trasy WD istnieją).
"""

import httpx
import pytest
from fastapi import FastAPI

from app.api.openapi import build_openapi
from app.api.openapi_export import export_settings
from app.main import create_app

pytestmark = pytest.mark.contract

_METHODS = ("get", "post", "put", "patch", "delete")
_WD_PREFIX = "/api/wd/v1"
_RESET_PATH = "/api/wd/v1/test/reset"
_OK = 200
_UNAUTHORIZED = 401


def _wd_operations(schema: dict[str, object]) -> list[tuple[str, str, dict[str, object]]]:
    """Operacje dokumentu pod ``/api/wd/v1`` jako ``(ścieżka, metoda, operacja)``."""
    paths: dict[str, dict[str, object]] = schema["paths"]  # type: ignore[assignment]
    return [
        (path, method, path_item[method])
        for path, path_item in paths.items()
        if path.startswith(_WD_PREFIX)
        for method in _METHODS
        if method in path_item
    ]


def test_wd_operations_never_declare_422(app: FastAPI) -> None:
    """Dokument aplikacji nie deklaruje 422 dla żadnej operacji ``/api/wd/v1`` (kontrakt §5)."""
    declared = [
        (path, method, responses)
        for path, method, responses in (
            (path, method, op["responses"]) for path, method, op in _wd_operations(app.openapi())
        )
        if "422" in responses
    ]
    assert declared == []


def test_test_reset_route_is_not_in_schema(app: FastAPI) -> None:
    """``/api/wd/v1/test/reset`` istnieje tylko w ``env == "test"`` (kontrakt §5)."""
    assert _RESET_PATH not in app.openapi()["paths"]


def test_exported_document_has_no_422_under_wd() -> None:
    """Dokument eksportowany (``env=dev``) też nie deklaruje 422 dla tras WD (kontrakt §5)."""
    assert [
        (path, method)
        for path, method, op in _wd_operations(create_app(export_settings()).openapi())
        if "422" in op["responses"]
    ] == []


def test_build_openapi_strips_422_for_wd_route() -> None:
    """Trasa WD z parametrem typowanym: ``build_openapi`` usuwa 422, inne trasy zostawia."""
    app = FastAPI()

    @app.get("/api/wd/v1/integrations/{integration_id}")
    def get_integration(integration_id: int) -> dict[str, int]:
        """Trasa syntetyczna — generuje deklarację 422, którą ``build_openapi`` ma usunąć."""
        return {"integration_id": integration_id}

    @app.get("/other/{item_id}")
    def other(item_id: int) -> dict[str, int]:
        """Trasa poza przestrzenią WD — 422 zostaje (kontrola)."""
        return {"item_id": item_id}

    schema = build_openapi(app)
    assert (
        "422" not in schema["paths"]["/api/wd/v1/integrations/{integration_id}"]["get"]["responses"]
    )
    assert "422" in schema["paths"]["/other/{item_id}"]["get"]["responses"]


async def test_client_fixtures_authenticate(
    admin: httpx.AsyncClient, member: httpx.AsyncClient, anon: httpx.AsyncClient
) -> None:
    """Tokeny fixture'ów działają: admin i member → 200 na ``/users/me``, anon → 401.

    Trasy WD są w T2 puste, więc fixtures klientów (potrzebne w T3/T4) sprawdzamy na istniejącej
    trasie wymagającej principala.
    """
    assert (await admin.get("/api/v1/users/me")).status_code == _OK
    assert (await member.get("/api/v1/users/me")).status_code == _OK
    assert (await anon.get("/api/v1/users/me")).status_code == _UNAUTHORIZED
