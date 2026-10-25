"""Testy `SharePointConnector` na `httpx.MockTransport` (WP E4-2b, kontrakt connector.py)."""

import contextlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from app.integrations.base import ChangeSet, Container, RemoteItem
from app.integrations.sharepoint.config import SharePointConfig
from app.integrations.sharepoint.connector import SharePointConnector
from app.integrations.sharepoint.errors import SizeLimitExceeded
from app.integrations.sharepoint.graph import DELTA_SELECT, GRAPH_BASE_URL
from tests.unit.integrations.sharepoint.conftest import (
    CLIENT_ID,
    TENANT_ID,
    TOKEN_HOST,
    load_fixture,
)

GRAPH_ORIGIN = "https://graph.microsoft.com"
FAKE_GRAPH_BASE_URL = "http://fake-graph:8095/v1.0"
SITE_URL = "https://contoso.sharepoint.com/sites/team"
SITE_CALL_PATH = "/v1.0/sites/contoso.sharepoint.com:/sites/team"
SECRET = "super-secret-value"  # noqa: S105 — sekret wyłącznie testowy
INTEGRATION_ID = 7
MAX_BYTES = 4096
DRIVE_ID = "b!d1"
ITEM_ID = "i1"
C1 = Container(id=DRIVE_ID, name="Documents")
DOWNLOAD_HOST = "download.example.net"
DOWNLOAD_URL = f"https://{DOWNLOAD_HOST}/blob?sig=XYZ"
HELLO = b"hello"
TOO_BIG = b"aaabbb"
TOO_BIG_LIMIT = 3
CONTENT_PATH = f"/v1.0/drives/{DRIVE_ID}/items/{ITEM_ID}/content"
ITEM_PATH = f"/v1.0/drives/{DRIVE_ID}/items/{ITEM_ID}"
DELTA_PATH = f"/v1.0/drives/{DRIVE_ID}/root/delta"
DRIVES_PATH = "/v1.0/sites/S1/drives"
TWO_PAGES = 2
CHECK_NAMES = ["graph_auth", "site_resolution", "dataset_exists"]
LIBS_TOTAL = 3
LIBS_INCLUDED = 2
CLIENT_CALLS = 6
AUTH_ERROR = "AADSTS7000215: Invalid client secret provided."

Handler = Callable[[httpx.Request], httpx.Response]


class RecordingFactory:
    """Fabryka klientów `MockTransport`; śledzi klienty i żądania (dowód braku wycieku)."""

    def __init__(self, handler: Handler) -> None:
        self._handler = handler
        self.clients: list[httpx.AsyncClient] = []
        self.requests: list[httpx.Request] = []

    def __call__(self) -> httpx.AsyncClient:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(self._dispatch),
            base_url=GRAPH_BASE_URL,
            follow_redirects=False,
        )
        self.clients.append(client)
        return client

    def _dispatch(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._handler(request)

    def graph_requests(self) -> list[httpx.Request]:
        return [request for request in self.requests if request.url.host != TOKEN_HOST]

    def graph_urls(self) -> list[str]:
        return [str(request.url) for request in self.graph_requests()]

    def assert_closed(self) -> None:
        assert self.clients, "konektor nie utworzył klienta HTTP"
        assert all(client.is_closed for client in self.clients)


def token_ok() -> httpx.Response:
    return httpx.Response(httpx.codes.OK, json=load_fixture("token_ok.json"))


def ok_handler(*, content: bytes = HELLO) -> Handler:
    """Handler szczęśliwej ścieżki: token, site, drives, delta, item i treść pliku."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == TOKEN_HOST:
            response = token_ok()
        elif request.url.host == DOWNLOAD_HOST:
            response = httpx.Response(httpx.codes.OK, content=content)
        elif request.url.path == CONTENT_PATH:
            response = httpx.Response(httpx.codes.FOUND, headers={"Location": DOWNLOAD_URL})
        elif request.url.path == ITEM_PATH:
            response = httpx.Response(httpx.codes.OK, json=load_fixture("drive_item.json"))
        elif request.url.path == DELTA_PATH:
            # Pierwsza strona bez kursora; nextLink i zapisany deltaLink → ostatnia strona.
            last = request.url.params.get("$skiptoken") or request.url.params.get("token")
            name = "delta_page2.json" if last else "delta_page1.json"
            response = httpx.Response(httpx.codes.OK, json=load_fixture(name))
        elif request.url.path == SITE_CALL_PATH:
            response = httpx.Response(httpx.codes.OK, json=load_fixture("site.json"))
        elif request.url.path.endswith("/drives"):
            last = request.url.params.get("$skiptoken")
            name = "drives_page2.json" if last else "drives_page1.json"
            response = httpx.Response(httpx.codes.OK, json=load_fixture(name))
        else:
            raise AssertionError(f"nieoczekiwane żądanie testu: {request.url}")
        return response

    return handler


def make_config(
    *, site_id: str | None = None, excluded: list[str] | None = None
) -> SharePointConfig:
    return SharePointConfig(
        integration_id=INTEGRATION_ID,
        tenant_id=TENANT_ID,
        client_id=CLIENT_ID,
        client_secret=SecretStr(SECRET),
        site_url=SITE_URL,
        site_id=site_id,
        excluded_library_names=[] if excluded is None else excluded,
        max_file_size_bytes=MAX_BYTES,
    )


def make_item() -> RemoteItem:
    return RemoteItem(
        container_id=DRIVE_ID,
        item_id=ITEM_ID,
        name="report.pdf",
        path="/Docs/report.pdf",
        size=1234,
        content_tag="c:1",
        meta_tag="e:1",
        modified_at=None,
        web_url="https://contoso.sharepoint.com/sites/Docs/report.pdf",
        is_folder=False,
        deleted=False,
    )


async def test_resolve_returns_site_id_and_display_name() -> None:
    site = load_fixture("site.json")
    factory = RecordingFactory(ok_handler())

    resolved = await SharePointConnector(factory).resolve(make_config())

    assert resolved == {"site_id": site["id"], "site_display_name": site["displayName"]}
    assert factory.graph_urls() == [f"{GRAPH_ORIGIN}{SITE_CALL_PATH}"]
    factory.assert_closed()


async def test_list_containers_uses_configured_site_id_and_exclusions() -> None:
    factory = RecordingFactory(ok_handler())

    containers = await SharePointConnector(factory).list_containers(
        make_config(site_id="S1", excluded=["Archive"])
    )

    assert [(container.id, container.name) for container in containers] == [
        ("b!d1", "Documents"),
        ("b!d3", "Reports"),
    ]
    # Z ustawionym `site_id` nie ma żądania getByPath (`/sites/<host>:/<path>`).
    assert factory.graph_urls() == [
        f"{GRAPH_ORIGIN}{DRIVES_PATH}",
        f"{GRAPH_ORIGIN}{DRIVES_PATH}?$skiptoken=P2",
    ]
    factory.assert_closed()


async def test_list_containers_resolves_site_when_site_id_missing() -> None:
    factory = RecordingFactory(ok_handler())

    containers = await SharePointConnector(factory).list_containers(
        make_config(excluded=["Archive"])
    )

    assert [container.name for container in containers] == ["Documents", "Reports"]
    assert factory.graph_urls()[0] == f"{GRAPH_ORIGIN}{SITE_CALL_PATH}"
    factory.assert_closed()


async def test_changes_streams_pages_and_cursor_on_last() -> None:
    factory = RecordingFactory(ok_handler())

    sets = [
        change_set
        async for change_set in SharePointConnector(factory).changes(make_config(), C1, None)
    ]

    assert len(sets) == TWO_PAGES
    assert sets[0].cursor is None
    assert sets[1].cursor == load_fixture("delta_page2.json")["@odata.deltaLink"]
    assert [item.item_id for item in sets[1].items] == ["i2", "i3", "i4"]
    assert sets[1].items[1].deleted is True
    assert sets[0].items[1] == RemoteItem(
        container_id=DRIVE_ID,
        item_id="i1",
        name="a.docx",
        path="/Docs/a.docx",
        size=1234,
        content_tag='"c-i1"',
        meta_tag='"e-i1"',
        modified_at=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
        web_url="https://contoso.sharepoint.com/sites/Docs/Shared%20Documents/Docs/a.docx",
        is_folder=False,
        deleted=False,
    )
    delta_request = factory.graph_requests()[0]
    assert delta_request.url.path == DELTA_PATH
    assert delta_request.url.params["$select"] == DELTA_SELECT
    factory.assert_closed()


async def test_changes_uses_cursor_url_without_select() -> None:
    cursor = load_fixture("delta_page2.json")["@odata.deltaLink"]
    factory = RecordingFactory(ok_handler())

    sets = [
        change_set
        async for change_set in SharePointConnector(factory).changes(make_config(), C1, cursor)
    ]

    assert factory.graph_urls() == [cursor]
    assert len(sets) == 1
    assert sets[0].cursor == cursor
    assert sets[0].reset_required is False
    assert [item.item_id for item in sets[0].items] == ["i2", "i3", "i4"]
    factory.assert_closed()


async def test_changes_410_returns_reset_required() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == TOKEN_HOST:
            return token_ok()
        return httpx.Response(httpx.codes.GONE, json=load_fixture("error_410_resync.json"))

    factory = RecordingFactory(handler)

    sets = [
        change_set
        async for change_set in SharePointConnector(factory).changes(make_config(), C1, "cur")
    ]

    assert sets == [ChangeSet(items=[], cursor=None, reset_required=True)]
    factory.assert_closed()


async def test_changes_break_closes_client() -> None:
    factory = RecordingFactory(ok_handler())
    connector = SharePointConnector(factory)

    async with contextlib.aclosing(connector.changes(make_config(), C1, None)) as stream:
        async for _ in stream:
            break

    factory.assert_closed()


async def test_download_writes_file_and_redirect_has_no_authorization(tmp_path: Path) -> None:
    factory = RecordingFactory(ok_handler())
    dest = tmp_path / "out.bin"

    size = await SharePointConnector(factory).download(
        make_config(), make_item(), dest, max_bytes=MAX_BYTES
    )

    assert size == len(HELLO)
    assert dest.read_bytes() == HELLO
    content_request = factory.graph_requests()[0]
    assert content_request.url.path == CONTENT_PATH
    assert content_request.headers["authorization"].startswith("Bearer ")
    download_request = factory.graph_requests()[1]
    assert download_request.url.host == DOWNLOAD_HOST
    assert "authorization" not in download_request.headers
    factory.assert_closed()


async def test_download_over_max_bytes_raises_without_file(tmp_path: Path) -> None:
    factory = RecordingFactory(ok_handler(content=TOO_BIG))
    dest = tmp_path / "big.bin"

    with pytest.raises(SizeLimitExceeded):
        await SharePointConnector(factory).download(
            make_config(), make_item(), dest, max_bytes=TOO_BIG_LIMIT
        )

    assert not dest.exists()
    factory.assert_closed()


async def test_web_link_decodes_remote_item() -> None:
    factory = RecordingFactory(ok_handler())

    item = await SharePointConnector(factory).web_link(make_config(), DRIVE_ID, ITEM_ID)

    assert item is not None
    assert item.item_id == ITEM_ID
    assert item.container_id == DRIVE_ID
    assert item.name == "report.pdf"
    assert item.path == "/Docs/report.pdf"
    assert item.web_url == "https://contoso.sharepoint.com/sites/Docs/report.pdf"
    assert factory.graph_urls() == [f"{GRAPH_ORIGIN}{ITEM_PATH}"]
    factory.assert_closed()


@pytest.mark.parametrize("status", [httpx.codes.NOT_FOUND, httpx.codes.GONE])
async def test_web_link_missing_returns_none(status: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == TOKEN_HOST:
            return token_ok()
        return httpx.Response(status, json={"error": {"code": "itemNotFound"}})

    factory = RecordingFactory(handler)

    assert await SharePointConnector(factory).web_link(make_config(), DRIVE_ID, ITEM_ID) is None
    factory.assert_closed()


async def test_connection_report_ok_with_site_and_libraries() -> None:
    factory = RecordingFactory(ok_handler())

    report = await SharePointConnector(factory).test_connection(
        make_config(excluded=["Archive"]), dataset_exists=True
    )

    assert report.ok is True
    assert [check["name"] for check in report.checks] == CHECK_NAMES
    assert all(check["status"] == "ok" for check in report.checks)
    assert report.resolved == {
        "site_id": load_fixture("site.json")["id"],
        "site_display_name": "Docs Team Site",
        "libraries_total": LIBS_TOTAL,
        "libraries_included": LIBS_INCLUDED,
    }
    factory.assert_closed()


async def test_connection_token_error_returns_early() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == TOKEN_HOST:
            return httpx.Response(httpx.codes.UNAUTHORIZED, json=load_fixture("token_error.json"))
        return httpx.Response(httpx.codes.INTERNAL_SERVER_ERROR, json={})

    factory = RecordingFactory(handler)

    report = await SharePointConnector(factory).test_connection(make_config(), dataset_exists=True)

    assert report.ok is False
    assert report.checks == [{"name": "graph_auth", "status": "failed", "detail": AUTH_ERROR}]
    assert report.resolved == {}
    # Wczesny powrót: żadne żądanie Graph nie poszło (także do /sites).
    assert factory.graph_urls() == []
    assert SECRET not in str(report.checks)
    factory.assert_closed()


async def test_connection_site_error_still_checks_dataset() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == TOKEN_HOST:
            return token_ok()
        if request.url.path == SITE_CALL_PATH:
            return httpx.Response(httpx.codes.NOT_FOUND, json={"error": {"code": "itemNotFound"}})
        raise AssertionError(f"nieoczekiwane żądanie testu: {request.url}")

    factory = RecordingFactory(handler)

    report = await SharePointConnector(factory).test_connection(make_config(), dataset_exists=True)

    assert report.ok is False
    assert [check["name"] for check in report.checks] == CHECK_NAMES
    assert report.checks[1]["status"] == "failed"
    assert report.checks[2] == {"name": "dataset_exists", "status": "ok", "detail": ""}
    assert report.resolved == {}
    factory.assert_closed()


async def test_connection_reports_missing_dataset() -> None:
    factory = RecordingFactory(ok_handler())

    report = await SharePointConnector(factory).test_connection(
        make_config(site_id="S1"), dataset_exists=False
    )

    assert report.ok is False
    assert report.checks[2] == {
        "name": "dataset_exists",
        "status": "failed",
        "detail": "dataset not found",
    }
    factory.assert_closed()


async def test_no_client_leak_across_all_methods(tmp_path: Path) -> None:
    factory = RecordingFactory(ok_handler())
    connector = SharePointConnector(factory)
    config = make_config(site_id="S1")

    await connector.resolve(config)
    await connector.list_containers(config)
    # `aclosing` = determinystyczne przerwanie strumienia (`break`) w połowie stron.
    async with contextlib.aclosing(connector.changes(config, C1, None)) as stream:
        async for _ in stream:
            break
    await connector.download(config, make_item(), tmp_path / "leak.bin", max_bytes=MAX_BYTES)
    await connector.web_link(config, DRIVE_ID, ITEM_ID)
    await connector.test_connection(config, dataset_exists=True)

    assert len(factory.clients) == CLIENT_CALLS
    factory.assert_closed()


async def test_repr_and_logs_do_not_leak_secret(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    factory = RecordingFactory(ok_handler())
    connector = SharePointConnector(factory)
    config = make_config(site_id="S1")

    assert SECRET not in repr(config)

    with caplog.at_level(logging.DEBUG):
        await connector.resolve(config)
        await connector.list_containers(config)
        async for _ in connector.changes(config, C1, None):
            pass
        await connector.download(config, make_item(), tmp_path / "log.bin", max_bytes=MAX_BYTES)
        await connector.test_connection(config, dataset_exists=True)

    assert SECRET not in caplog.text
    assert "tok-" not in caplog.text
    factory.assert_closed()


async def test_default_factory_uses_configured_urls() -> None:
    """Bez `http_factory` konektor buduje klienta pod `graph_base_url` (kontrakt C2)."""
    connector = SharePointConnector(
        login_base_url="http://fake-login:8095", graph_base_url=FAKE_GRAPH_BASE_URL
    )

    _, graph = connector._client(make_config())
    try:
        assert str(graph.http.base_url) == f"{FAKE_GRAPH_BASE_URL}/"
    finally:
        await graph.aclose()
