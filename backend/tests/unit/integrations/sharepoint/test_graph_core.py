"""Testy GraphClient: retry/401, site, drives, get_item (WP E4-2a) — MockTransport, bez sieci."""

import logging
from collections.abc import Callable

import httpx
import pytest

from app.integrations.base import Container
from app.integrations.sharepoint.errors import GraphError, GraphNotFound
from app.integrations.sharepoint.graph import MAX_ATTEMPTS, make_http_client
from tests.unit.integrations.sharepoint.conftest import load_fixture, make_client

GRAPH_PREFIX = "https://graph.microsoft.com/v1.0"
SITE_URL = "https://contoso.sharepoint.com/sites/Docs"
SITE_ID = "contoso.sharepoint.com,11111111-aaaa,22222222-bbbb"
ONE_REQUEST = 1
TWO_REQUESTS = 2
THREE_REQUESTS = 3
SITE_TIMEOUT = 30.0
READ_TIMEOUT = 120.0
THREE_DRIVES = 3

Handler = Callable[[httpx.Request], httpx.Response]


def queue_handler(
    responses: list[httpx.Response | Exception],
) -> tuple[Handler, list[httpx.Request]]:
    """Zwraca kolejne odpowiedzi (lub zgłasza wyjątek) i nagrywa odebrane żądania."""
    seen: list[httpx.Request] = []
    pending = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        item = pending.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return handler, seen


def ok_site() -> httpx.Response:
    return httpx.Response(200, json=load_fixture("site.json"))


async def test_request_returns_2xx_with_bearer_token() -> None:
    handler, seen = queue_handler([ok_site()])
    client = make_client(handler)
    async with client.http:
        response = await client.request("GET", "/sites/contoso.sharepoint.com")

    assert response.status_code == httpx.codes.OK
    assert response.json()["id"] == SITE_ID
    assert str(seen[0].url) == f"{GRAPH_PREFIX}/sites/contoso.sharepoint.com"
    assert seen[0].headers["Authorization"] == "Bearer tok-1"
    assert len(seen) == ONE_REQUEST


async def test_429_retry_after_header_is_honoured() -> None:
    sleeps: list[float] = []
    throttled = httpx.Response(
        429, json=load_fixture("error_429.json"), headers={"Retry-After": "7"}
    )
    handler, seen = queue_handler([throttled, ok_site()])
    client = make_client(handler, sleeps=sleeps)
    async with client.http:
        response = await client.request("GET", "/sites/contoso.sharepoint.com")

    assert response.status_code == httpx.codes.OK
    assert sleeps == [7.0]
    assert len(seen) == TWO_REQUESTS


async def test_429_without_retry_after_uses_backoff() -> None:
    sleeps: list[float] = []
    throttled = httpx.Response(429, json=load_fixture("error_429.json"))
    handler, seen = queue_handler([throttled, throttled, ok_site()])
    client = make_client(handler, sleeps=sleeps)
    async with client.http:
        await client.request("GET", "/sites/contoso.sharepoint.com")

    assert sleeps == [1.0, 2.0]
    assert len(seen) == THREE_REQUESTS


async def test_429_with_non_numeric_retry_after_uses_backoff() -> None:
    sleeps: list[float] = []
    throttled = httpx.Response(429, headers={"Retry-After": "soon"})
    handler, _ = queue_handler([throttled, ok_site()])
    client = make_client(handler, sleeps=sleeps)
    async with client.http:
        await client.request("GET", "/sites/contoso.sharepoint.com")

    assert sleeps == [1.0]


async def test_503_exhausts_attempts() -> None:
    sleeps: list[float] = []
    handler, seen = queue_handler([httpx.Response(503)] * MAX_ATTEMPTS)
    client = make_client(handler, sleeps=sleeps)
    async with client.http:
        with pytest.raises(GraphError) as excinfo:
            await client.request("GET", "/sites/contoso.sharepoint.com")

    assert excinfo.value.status == httpx.codes.SERVICE_UNAVAILABLE
    assert len(seen) == MAX_ATTEMPTS
    assert len(sleeps) == MAX_ATTEMPTS - 1


async def test_transport_error_is_retried_then_succeeds() -> None:
    sleeps: list[float] = []
    handler, seen = queue_handler([httpx.ConnectError("boom"), ok_site()])
    client = make_client(handler, sleeps=sleeps)
    async with client.http:
        response = await client.request("GET", "/sites/contoso.sharepoint.com")

    assert response.status_code == httpx.codes.OK
    assert len(seen) == TWO_REQUESTS
    assert len(sleeps) == 1


async def test_transport_errors_exhaust_attempts() -> None:
    sleeps: list[float] = []
    handler, seen = queue_handler([httpx.ConnectError("boom")] * MAX_ATTEMPTS)
    client = make_client(handler, sleeps=sleeps)
    async with client.http:
        with pytest.raises(GraphError) as excinfo:
            await client.request("GET", "/sites/contoso.sharepoint.com")

    assert (excinfo.value.status, excinfo.value.code, excinfo.value.message) == (
        0,
        "transport",
        "ConnectError",
    )
    assert len(seen) == MAX_ATTEMPTS
    assert len(sleeps) == MAX_ATTEMPTS - 1


async def test_single_401_refreshes_token_and_retries() -> None:
    handler, seen = queue_handler([httpx.Response(401), ok_site()])
    client = make_client(handler)
    async with client.http:
        response = await client.request("GET", "/sites/contoso.sharepoint.com")

    assert response.status_code == httpx.codes.OK
    assert len(seen) == TWO_REQUESTS
    assert seen[0].headers["Authorization"] == "Bearer tok-1"
    assert seen[1].headers["Authorization"] == "Bearer tok-2"


async def test_second_401_raises_graph_error() -> None:
    handler, seen = queue_handler([httpx.Response(401), httpx.Response(401)])
    client = make_client(handler)
    async with client.http:
        with pytest.raises(GraphError) as excinfo:
            await client.request("GET", "/sites/contoso.sharepoint.com")

    assert excinfo.value.status == httpx.codes.UNAUTHORIZED
    assert len(seen) == TWO_REQUESTS


async def test_404_raises_not_found_without_retry() -> None:
    body = {"error": {"code": "itemNotFound", "message": "no such item"}}
    handler, seen = queue_handler([httpx.Response(404, json=body)])
    client = make_client(handler)
    async with client.http:
        with pytest.raises(GraphNotFound) as excinfo:
            await client.request("GET", "/sites/contoso.sharepoint.com")

    assert excinfo.value.status == httpx.codes.NOT_FOUND
    assert excinfo.value.code == "itemNotFound"
    assert excinfo.value.message == "no such item"
    assert len(seen) == ONE_REQUEST


async def test_410_raises_not_found_with_status() -> None:
    handler, seen = queue_handler([httpx.Response(410, json=load_fixture("error_429.json"))])
    client = make_client(handler)
    async with client.http:
        with pytest.raises(GraphNotFound) as excinfo:
            await client.request("GET", "/sites/contoso.sharepoint.com")

    assert excinfo.value.status == httpx.codes.GONE
    assert len(seen) == ONE_REQUEST


async def test_500_raises_graph_error_not_not_found() -> None:
    handler, seen = queue_handler([httpx.Response(500, text="boom")])
    client = make_client(handler)
    async with client.http:
        with pytest.raises(GraphError) as excinfo:
            await client.request("GET", "/sites/contoso.sharepoint.com")

    assert not isinstance(excinfo.value, GraphNotFound)
    assert excinfo.value.status == httpx.codes.INTERNAL_SERVER_ERROR
    assert excinfo.value.code == ""
    assert excinfo.value.message == httpx.Response(500).reason_phrase
    assert len(seen) == ONE_REQUEST


async def test_non_json_error_body_has_empty_code() -> None:
    handler, _ = queue_handler([httpx.Response(400, text="<html>down</html>")])
    client = make_client(handler)
    async with client.http:
        with pytest.raises(GraphError) as excinfo:
            await client.request("GET", "/sites/contoso.sharepoint.com")

    assert excinfo.value.code == ""
    assert excinfo.value.message == httpx.Response(400).reason_phrase


async def test_retry_logs_do_not_leak_token(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    throttled = httpx.Response(429, json=load_fixture("error_429.json"))
    handler, _ = queue_handler([throttled, ok_site()])
    client = make_client(handler)
    async with client.http:
        await client.request("GET", "/sites/contoso.sharepoint.com")

    assert caplog.text
    assert "tok-" not in caplog.text
    assert "Bearer" not in caplog.text


async def test_request_redirect_returns_redirect_response() -> None:
    redirect = httpx.Response(302, headers={"Location": "https://cdn.example/file.bin"})
    handler, seen = queue_handler([redirect])
    client = make_client(handler)
    async with client.http:
        response = await client.request_redirect(f"{GRAPH_PREFIX}/drives/b!d1/items/i1/content")

    assert response.status_code == httpx.codes.FOUND
    assert response.headers["Location"] == "https://cdn.example/file.bin"
    assert len(seen) == ONE_REQUEST


async def test_request_on_redirect_raises_graph_error() -> None:
    redirect = httpx.Response(302, headers={"Location": "https://cdn.example/file.bin"})
    handler, seen = queue_handler([redirect])
    client = make_client(handler)
    async with client.http:
        with pytest.raises(GraphError) as excinfo:
            await client.request("GET", "/drives/b!d1/items/i1/content")

    assert excinfo.value.status == httpx.codes.FOUND
    assert len(seen) == ONE_REQUEST


async def test_resolve_site_by_path() -> None:
    handler, seen = queue_handler([ok_site()])
    client = make_client(handler)
    async with client.http:
        site_id, name = await client.resolve_site(SITE_URL)

    assert (site_id, name) == (SITE_ID, "Docs Team Site")
    assert str(seen[0].url) == f"{GRAPH_PREFIX}/sites/contoso.sharepoint.com:/sites/Docs"


async def test_resolve_site_root_with_trailing_slash() -> None:
    handler, seen = queue_handler([ok_site()])
    client = make_client(handler)
    async with client.http:
        await client.resolve_site("https://contoso.sharepoint.com/")

    assert str(seen[0].url) == f"{GRAPH_PREFIX}/sites/contoso.sharepoint.com"


async def test_resolve_site_root_without_trailing_slash() -> None:
    handler, seen = queue_handler([ok_site()])
    client = make_client(handler)
    async with client.http:
        await client.resolve_site("https://contoso.sharepoint.com")

    assert str(seen[0].url) == f"{GRAPH_PREFIX}/sites/contoso.sharepoint.com"


async def test_resolve_site_path_with_trailing_slash() -> None:
    handler, seen = queue_handler([ok_site()])
    client = make_client(handler)
    async with client.http:
        await client.resolve_site("https://contoso.sharepoint.com/sites/Docs/")

    assert str(seen[0].url) == f"{GRAPH_PREFIX}/sites/contoso.sharepoint.com:/sites/Docs"


async def test_resolve_site_not_found() -> None:
    handler, _ = queue_handler([httpx.Response(404, json={"error": {"code": "itemNotFound"}})])
    client = make_client(handler)
    async with client.http:
        with pytest.raises(GraphNotFound):
            await client.resolve_site(SITE_URL)


async def test_resolve_site_invalid_url() -> None:
    handler, seen = queue_handler([ok_site()])
    client = make_client(handler)
    async with client.http:
        with pytest.raises(ValueError, match="invalid site_url"):
            await client.resolve_site("not a url")

    assert seen == []


async def test_list_drives_paginates_and_excludes() -> None:
    next_link = load_fixture("drives_page1.json")["@odata.nextLink"]
    handler, seen = queue_handler(
        [
            httpx.Response(200, json=load_fixture("drives_page1.json")),
            httpx.Response(200, json=load_fixture("drives_page2.json")),
        ]
    )
    client = make_client(handler)
    async with client.http:
        containers, total = await client.list_drives("S1", ["Archive"])

    assert containers == [Container("b!d1", "Documents"), Container("b!d3", "Reports")]
    assert total == THREE_DRIVES
    assert str(seen[0].url) == f"{GRAPH_PREFIX}/sites/S1/drives"
    assert str(seen[1].url) == next_link
    assert len(seen) == TWO_REQUESTS


async def test_list_drives_without_exclusions() -> None:
    handler, _ = queue_handler(
        [
            httpx.Response(200, json=load_fixture("drives_page1.json")),
            httpx.Response(200, json=load_fixture("drives_page2.json")),
        ]
    )
    client = make_client(handler)
    async with client.http:
        containers, total = await client.list_drives("S1", [])

    assert containers == [
        Container("b!d1", "Documents"),
        Container("b!d2", "Archive"),
        Container("b!d3", "Reports"),
    ]
    assert total == THREE_DRIVES


async def test_list_drives_exclusion_is_exact() -> None:
    handler, _ = queue_handler(
        [
            httpx.Response(200, json=load_fixture("drives_page1.json")),
            httpx.Response(200, json=load_fixture("drives_page2.json")),
        ]
    )
    client = make_client(handler)
    async with client.http:
        containers, _ = await client.list_drives("S1", ["archive"])

    assert Container("b!d2", "Archive") in containers
    assert len(containers) == THREE_DRIVES


async def test_get_item_returns_raw_dict() -> None:
    handler, seen = queue_handler([httpx.Response(200, json=load_fixture("drive_item.json"))])
    client = make_client(handler)
    async with client.http:
        item = await client.get_item("b!d1", "i1")

    assert item["id"] == "i1"
    assert item["name"] == "report.pdf"
    assert str(seen[0].url) == f"{GRAPH_PREFIX}/drives/b!d1/items/i1"
    assert len(seen) == ONE_REQUEST


async def test_get_item_not_found() -> None:
    handler, seen = queue_handler([httpx.Response(404, json={"error": {"code": "itemNotFound"}})])
    client = make_client(handler)
    async with client.http:
        with pytest.raises(GraphNotFound):
            await client.get_item("b!d1", "missing")

    assert len(seen) == ONE_REQUEST


async def test_aclose_closes_http() -> None:
    handler, _ = queue_handler([ok_site()])
    client = make_client(handler)
    await client.aclose()

    assert client.http.is_closed


async def test_make_http_client_configuration() -> None:
    http = make_http_client()
    assert str(http.base_url).startswith(GRAPH_PREFIX)
    assert http.timeout.read == READ_TIMEOUT
    assert http.timeout.connect == SITE_TIMEOUT
    assert http.follow_redirects is False
    await http.aclose()


async def test_make_http_client_uses_given_base_url() -> None:
    """`make_http_client(url)` ustawia `base_url` na podany adres (kontrakt C2, brief T1)."""
    http = make_http_client("http://fake-graph:8095/v1.0")

    assert str(http.base_url) == "http://fake-graph:8095/v1.0/"
    await http.aclose()
