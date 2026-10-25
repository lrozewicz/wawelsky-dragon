"""Testy stubu Microsoft Graph: login, Graph, delta, download, `/__test/*` (C3)."""

from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest

from fake_graph.app import DEFAULT_PORT, create_server, main

FAKE_GRAPH_DIR = Path(__file__).resolve().parents[1]
FIXTURES = FAKE_GRAPH_DIR / "fixtures"

HTTP_OK = 200
HTTP_CREATED = 201
HTTP_NO_CONTENT = 204
HTTP_FOUND = 302
HTTP_UNAUTHORIZED = 401
HTTP_NOT_FOUND = 404
HTTP_GONE = 410

DOCS = "drive-docs"
ARCH = "drive-arch"
DOCS_FILES = 3
OAUTH_PATH = "/tenant-e2e/oauth2/v2.0/token"
SITE_PATH = "/v1.0/sites/contoso.sharepoint.test:/sites/e2e"
SITE_ID = "site-e2e"
SITE_NAME = "E2E Site"
AUTH = {"Authorization": "Bearer fake-graph-token"}
CONTENT_TYPE_OCTET = "application/octet-stream"


def _token_form(secret: str) -> dict[str, str]:
    """Pola formularza loginu wg C3."""
    return {
        "client_id": "client-e2e",
        "client_secret": secret,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }


def _delta_ok(client: httpx.Client, drive_id: str) -> dict[str, Any]:
    """Pełne przejście delty napędu z autoryzacją."""
    response = client.get(f"/v1.0/drives/{drive_id}/root/delta", headers=AUTH)
    assert response.status_code == HTTP_OK
    body: dict[str, Any] = response.json()
    return body


def test_token_returns_access_token(client: httpx.Client) -> None:
    response = client.post(OAUTH_PATH, data=_token_form("fake-graph-secret"))
    assert response.status_code == HTTP_OK
    assert response.json() == {
        "access_token": "fake-graph-token",
        "token_type": "Bearer",
        "expires_in": 3599,
    }


def test_token_invalid_secret(client: httpx.Client) -> None:
    response = client.post(OAUTH_PATH, data=_token_form("zly"))
    assert response.status_code == HTTP_UNAUTHORIZED
    assert response.json() == {
        "error": "invalid_client",
        "error_description": "AADSTS7000215: Invalid client secret provided.",
    }


def test_graph_without_token_unauthorized(client: httpx.Client) -> None:
    response = client.get(SITE_PATH)
    assert response.status_code == HTTP_UNAUTHORIZED
    assert response.json() == {
        "error": {
            "code": "InvalidAuthenticationToken",
            "message": "Access token is empty or invalid.",
        }
    }


def test_graph_with_wrong_scheme_unauthorized(client: httpx.Client) -> None:
    response = client.get(SITE_PATH, headers={"Authorization": "Token fake-graph-token"})
    assert response.status_code == HTTP_UNAUTHORIZED


def test_graph_with_wrong_token_unauthorized(client: httpx.Client) -> None:
    response = client.get(SITE_PATH, headers={"Authorization": "Bearer nope"})
    assert response.status_code == HTTP_UNAUTHORIZED


def test_site_ok(client: httpx.Client) -> None:
    response = client.get(SITE_PATH, headers=AUTH)
    assert response.status_code == HTTP_OK
    assert response.json() == {"id": SITE_ID, "displayName": SITE_NAME}


def test_site_other_path_not_found(client: httpx.Client) -> None:
    response = client.get("/v1.0/sites/contoso.sharepoint.test:/sites/other", headers=AUTH)
    assert response.status_code == HTTP_NOT_FOUND
    assert response.json() == {"error": {"code": "itemNotFound", "message": "site not found"}}


def test_drives(client: httpx.Client) -> None:
    response = client.get(f"/v1.0/sites/{SITE_ID}/drives", headers=AUTH)
    assert response.status_code == HTTP_OK
    body = response.json()
    assert body == {"value": [{"id": DOCS, "name": "Dokumenty"}, {"id": ARCH, "name": "Archiwum"}]}
    assert "@odata.nextLink" not in body


def test_delta_full_docs(client: httpx.Client, base_url: str) -> None:
    body = _delta_ok(client, DOCS)
    assert [item["name"] for item in body["value"]] == ["sample.pdf", "sample.docx", "notatka.txt"]
    assert body["@odata.deltaLink"] == f"{base_url}/v1.0/drives/{DOCS}/root/delta?token=T0"


def test_delta_full_arch(client: httpx.Client) -> None:
    body = _delta_ok(client, ARCH)
    assert [item["name"] for item in body["value"]] == ["arch.txt"]
    assert body["@odata.deltaLink"].endswith("?token=T0")


def test_delta_accepts_select(client: httpx.Client) -> None:
    response = client.get(
        f"/v1.0/drives/{DOCS}/root/delta", params={"$select": "id,name"}, headers=AUTH
    )
    assert response.status_code == HTTP_OK


def test_delta_incremental_after_new_file(client: httpx.Client, base_url: str) -> None:
    created = client.post(
        "/__test/files", json={"drive_id": DOCS, "name": "nowy.txt", "text": "nowa tresc\n"}
    )
    assert created.status_code == HTTP_CREATED
    assert created.json() == {"id": "item-1"}

    response = client.get(f"/v1.0/drives/{DOCS}/root/delta", params={"token": "T0"}, headers=AUTH)
    body: dict[str, Any] = response.json()
    assert [item["name"] for item in body["value"]] == ["nowy.txt"]
    assert body["@odata.deltaLink"] == f"{base_url}/v1.0/drives/{DOCS}/root/delta?token=T1"


def test_delta_token_without_new_files_is_empty(client: httpx.Client) -> None:
    response = client.get(f"/v1.0/drives/{DOCS}/root/delta", params={"token": "T0"}, headers=AUTH)
    body: dict[str, Any] = response.json()
    assert body["value"] == []
    assert body["@odata.deltaLink"].endswith("?token=T0")


def test_delta_bad_token_gone(client: httpx.Client) -> None:
    response = client.get(f"/v1.0/drives/{DOCS}/root/delta", params={"token": "nope"}, headers=AUTH)
    assert response.status_code == HTTP_GONE
    assert response.json() == {
        "error": {"code": "resyncRequired", "message": "delta token expired"}
    }


def test_delta_unknown_drive_not_found(client: httpx.Client) -> None:
    response = client.get("/v1.0/drives/nie-ma/root/delta", headers=AUTH)
    assert response.status_code == HTTP_NOT_FOUND


def test_get_item_ok(client: httpx.Client) -> None:
    response = client.get(f"/v1.0/drives/{DOCS}/items/item-pdf", headers=AUTH)
    assert response.status_code == HTTP_OK
    assert response.json() == {
        "id": "item-pdf",
        "name": "sample.pdf",
        "size": (FIXTURES / "sample.pdf").stat().st_size,
        "cTag": "citem-pdf-0",
        "eTag": "eitem-pdf-0",
        "file": {"mimeType": "application/pdf"},
        "parentReference": {"path": f"/drives/{DOCS}/root:"},
        "webUrl": "https://contoso.sharepoint.test/sites/e2e/Dokumenty/sample.pdf",
        "lastModifiedDateTime": "2026-09-01T10:00:00Z",
    }


def test_get_item_missing_not_found(client: httpx.Client) -> None:
    response = client.get(f"/v1.0/drives/{DOCS}/items/nie-ma", headers=AUTH)
    assert response.status_code == HTTP_NOT_FOUND


def test_get_item_wrong_drive_not_found(client: httpx.Client) -> None:
    response = client.get(f"/v1.0/drives/{ARCH}/items/item-pdf", headers=AUTH)
    assert response.status_code == HTTP_NOT_FOUND


def test_content_redirect_then_download(client: httpx.Client, base_url: str) -> None:
    response = client.get(f"/v1.0/drives/{DOCS}/items/item-pdf/content", headers=AUTH)
    assert response.status_code == HTTP_FOUND
    expected = f"{base_url}/download/{DOCS}/item-pdf"
    assert response.headers["Location"] == expected

    download = client.get(expected)
    assert download.status_code == HTTP_OK
    assert download.headers["Content-Type"] == CONTENT_TYPE_OCTET
    assert download.headers["Content-Length"] == str((FIXTURES / "sample.pdf").stat().st_size)
    assert download.content == (FIXTURES / "sample.pdf").read_bytes()


def test_content_docx_matches_fixture(client: httpx.Client) -> None:
    download = client.get(f"/download/{DOCS}/item-docx")
    assert download.content == (FIXTURES / "sample.docx").read_bytes()


def test_download_text_item(client: httpx.Client) -> None:
    download = client.get(f"/download/{DOCS}/item-txt")
    assert download.content == b"Notatka z SharePointa, smok wawelski.\n"


def test_download_arch_item(client: httpx.Client) -> None:
    download = client.get(f"/download/{ARCH}/item-arch")
    assert download.content == b"Archiwum, stary dokument.\n"


def test_content_missing_not_found(client: httpx.Client) -> None:
    response = client.get(f"/v1.0/drives/{DOCS}/items/nie-ma/content", headers=AUTH)
    assert response.status_code == HTTP_NOT_FOUND


def test_download_missing_not_found(client: httpx.Client) -> None:
    response = client.get(f"/download/{DOCS}/nie-ma")
    assert response.status_code == HTTP_NOT_FOUND


def test_health(client: httpx.Client) -> None:
    response = client.get("/health")
    assert response.status_code == HTTP_OK
    assert response.text == "ok"


def test_reset_restores_initial_state(client: httpx.Client) -> None:
    client.post("/__test/files", json={"drive_id": DOCS, "name": "x.txt", "text": "x\n"})
    after_add = _delta_ok(client, DOCS)
    assert after_add["@odata.deltaLink"].endswith("?token=T1")

    reset = client.post("/__test/reset")
    assert reset.status_code == HTTP_NO_CONTENT

    after_reset = _delta_ok(client, DOCS)
    assert len(after_reset["value"]) == DOCS_FILES
    assert after_reset["@odata.deltaLink"].endswith("?token=T0")


def test_unknown_graph_path_not_found(client: httpx.Client) -> None:
    response = client.get("/v1.0/nieznane", headers=AUTH)
    assert response.status_code == HTTP_NOT_FOUND


def test_unknown_path_not_found(client: httpx.Client) -> None:
    response = client.get("/inna/sciezka")
    assert response.status_code == HTTP_NOT_FOUND


def test_unknown_post_path_not_found(client: httpx.Client) -> None:
    response = client.post("/inna/sciezka")
    assert response.status_code == HTTP_NOT_FOUND


def test_create_server_returns_threading_http_server() -> None:
    httpd = create_server(0)
    try:
        assert isinstance(httpd, ThreadingHTTPServer)
    finally:
        httpd.server_close()


class _StubServer:
    """Atrapa serwera dla `main`: notuje wywołanie `serve_forever`."""

    def __init__(self, captured: dict[str, Any]) -> None:
        self._captured = captured

    def serve_forever(self) -> None:
        self._captured["served"] = True


def _stub_create_server(captured: dict[str, Any], port: int) -> Any:
    """Zastępuje `create_server`, notując port i zwracając atrapę."""
    captured["port"] = port
    return _StubServer(captured)


def test_main_uses_env_port(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def factory(port: int) -> _StubServer:
        return _stub_create_server(captured, port)

    monkeypatch.setattr("fake_graph.app.create_server", factory)
    monkeypatch.setenv("FAKE_GRAPH_PORT", "9999")
    main()
    assert captured == {"port": 9999, "served": True}


def test_main_default_port(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def factory(port: int) -> _StubServer:
        return _stub_create_server(captured, port)

    monkeypatch.setattr("fake_graph.app.create_server", factory)
    monkeypatch.delenv("FAKE_GRAPH_PORT", raising=False)
    main()
    assert captured["port"] == DEFAULT_PORT
