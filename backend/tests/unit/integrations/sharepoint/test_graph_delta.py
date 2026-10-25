"""Testy delty Graph: `decode_item` i `iter_delta` (WP E4-2a) — MockTransport, bez sieci."""

from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest

from app.integrations.base import ChangeSet, RemoteItem
from app.integrations.sharepoint.errors import GraphError, GraphNotFound
from app.integrations.sharepoint.graph import DELTA_SELECT
from app.integrations.sharepoint.graph_delta import decode_item, iter_delta
from tests.unit.integrations.sharepoint.conftest import load_fixture, make_client

GRAPH_PREFIX = "https://graph.microsoft.com/v1.0"
DRIVE_ID = "b!d1"
DELTA_PATH = "/v1.0/drives/b!d1/root/delta"
CURSOR_URL = f"{GRAPH_PREFIX}/drives/b!d1/root/delta?token=OLD"
ONE_REQUEST = 1
TWO_REQUESTS = 2
TWO_PAGES = 2
ITEM_SIZE = 1234
PAGE1_ITEMS = 2
PAGE2_ITEMS = 3
DEFAULT_PAGE_LIMIT = 10

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


def ok_page(name: str) -> httpx.Response:
    return httpx.Response(200, json=load_fixture(name))


def item(raw: dict[str, object]) -> RemoteItem:
    return decode_item(raw, DRIVE_ID)


def test_decode_file_item() -> None:
    page = load_fixture("delta_page1.json")
    raw = next(entry for entry in page["value"] if entry["id"] == "i1")

    decoded = decode_item(raw, DRIVE_ID)

    assert decoded.container_id == DRIVE_ID
    assert decoded.item_id == "i1"
    assert decoded.name == "a.docx"
    assert decoded.path == "/Docs/a.docx"
    assert decoded.size == ITEM_SIZE
    assert decoded.content_tag == '"c-i1"'
    assert decoded.meta_tag == '"e-i1"'
    assert decoded.modified_at == datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
    assert decoded.web_url == (
        "https://contoso.sharepoint.com/sites/Docs/Shared%20Documents/Docs/a.docx"
    )
    assert decoded.is_folder is False
    assert decoded.deleted is False


def test_decode_item_without_parent_path_falls_back_to_name() -> None:
    page = load_fixture("delta_page2.json")
    raw = next(entry for entry in page["value"] if entry["id"] == "i2")

    decoded = decode_item(raw, DRIVE_ID)

    assert decoded.content_tag == decoded.meta_tag == '"e-i2"'
    assert decoded.path == "/b.txt"
    assert decoded.deleted is False
    assert decoded.is_folder is False


def test_decode_folder_item() -> None:
    page = load_fixture("delta_page1.json")
    raw = next(entry for entry in page["value"] if entry["id"] == "f1")

    decoded = decode_item(raw, DRIVE_ID)

    assert decoded.is_folder is True
    assert decoded.path == "/Docs"
    assert decoded.content_tag == decoded.meta_tag == '"e-f1"'


def test_decode_deleted_item_without_name() -> None:
    assert item({"id": "i3", "deleted": {}}) == RemoteItem(
        container_id=DRIVE_ID,
        item_id="i3",
        name="",
        path="",
        size=None,
        content_tag=None,
        meta_tag=None,
        modified_at=None,
        web_url=None,
        is_folder=False,
        deleted=True,
    )


def test_decode_deleted_item_keeps_name() -> None:
    page = load_fixture("delta_page2.json")
    raw = next(entry for entry in page["value"] if entry["id"] == "i4")

    decoded = decode_item(raw, DRIVE_ID)

    assert decoded.deleted is True
    assert decoded.path == "/old.txt"


def test_decode_item_with_invalid_date_has_no_modified_at() -> None:
    decoded = item({"id": "i9", "name": "x.txt", "lastModifiedDateTime": "not-a-date"})

    assert decoded.modified_at is None


async def test_iter_delta_start_selects_then_follows_next_link() -> None:
    next_link = load_fixture("delta_page1.json")["@odata.nextLink"]
    delta_link = load_fixture("delta_page2.json")["@odata.deltaLink"]
    handler, seen = queue_handler([ok_page("delta_page1.json"), ok_page("delta_page2.json")])
    client = make_client(handler)

    async with client.http:
        pages = [change_set async for change_set in iter_delta(client, DRIVE_ID, None, 10)]

    assert len(seen) == TWO_REQUESTS
    assert seen[0].url.path == DELTA_PATH
    assert dict(seen[0].url.params) == {"$select": DELTA_SELECT}
    assert str(seen[1].url) == next_link
    assert "$select" not in seen[1].url.params

    assert len(pages) == TWO_PAGES
    assert len(pages[0].items) == PAGE1_ITEMS
    assert pages[0].cursor is None
    assert pages[0].reset_required is False
    assert len(pages[1].items) == PAGE2_ITEMS
    assert pages[1].cursor == delta_link
    assert pages[1].reset_required is False


async def test_iter_delta_resumes_from_cursor_without_select() -> None:
    delta_link = load_fixture("delta_page2.json")["@odata.deltaLink"]
    handler, seen = queue_handler([ok_page("delta_page2.json")])
    client = make_client(handler)

    async with client.http:
        pages = [
            change_set
            async for change_set in iter_delta(client, DRIVE_ID, CURSOR_URL, DEFAULT_PAGE_LIMIT)
        ]

    assert len(seen) == ONE_REQUEST
    assert str(seen[0].url) == CURSOR_URL
    assert "$select" not in seen[0].url.params
    assert len(pages) == 1
    assert pages[0].cursor == delta_link


async def test_iter_delta_410_on_first_page_requires_reset() -> None:
    gone = httpx.Response(410, json=load_fixture("error_410_resync.json"))
    handler, seen = queue_handler([gone])
    client = make_client(handler)

    async with client.http:
        pages = [
            change_set
            async for change_set in iter_delta(client, DRIVE_ID, CURSOR_URL, DEFAULT_PAGE_LIMIT)
        ]

    assert len(seen) == ONE_REQUEST
    assert pages == [ChangeSet(items=[], cursor=None, reset_required=True)]


async def test_iter_delta_410_after_first_page_emits_page_then_reset() -> None:
    gone = httpx.Response(410, json=load_fixture("error_410_resync.json"))
    handler, seen = queue_handler([ok_page("delta_page1.json"), gone])
    client = make_client(handler)

    async with client.http:
        pages = [change_set async for change_set in iter_delta(client, DRIVE_ID, None, 10)]

    assert len(seen) == TWO_REQUESTS
    assert len(pages) == TWO_PAGES
    assert len(pages[0].items) == PAGE1_ITEMS
    assert pages[0].cursor is None
    assert pages[0].reset_required is False
    assert pages[1] == ChangeSet(items=[], cursor=None, reset_required=True)


async def test_iter_delta_404_propagates_not_found() -> None:
    body = {"error": {"code": "itemNotFound", "message": "no such drive"}}
    handler, seen = queue_handler([httpx.Response(404, json=body)])
    client = make_client(handler)

    async with client.http:
        with pytest.raises(GraphNotFound) as excinfo:
            async for _ in iter_delta(client, DRIVE_ID, CURSOR_URL, DEFAULT_PAGE_LIMIT):
                pass

    assert excinfo.value.status == httpx.codes.NOT_FOUND
    assert len(seen) == ONE_REQUEST


async def test_iter_delta_page_without_links_is_malformed() -> None:
    body = {"value": [{"id": "i1", "name": "a.docx", "eTag": '"e-i1"'}]}
    handler, _ = queue_handler([httpx.Response(200, json=body)])
    client = make_client(handler)

    async with client.http:
        with pytest.raises(GraphError) as excinfo:
            async for _ in iter_delta(client, DRIVE_ID, None, 10):
                pass

    assert excinfo.value.status == 0
    assert excinfo.value.code == "deltaMalformed"


async def test_iter_delta_max_pages_one_emits_page_then_raises() -> None:
    handler, seen = queue_handler([ok_page("delta_page1.json"), ok_page("delta_page2.json")])
    client = make_client(handler)
    collected: list[ChangeSet] = []

    async with client.http:
        with pytest.raises(GraphError) as excinfo:
            async for change_set in iter_delta(client, DRIVE_ID, None, 1):
                collected.append(change_set)

    assert excinfo.value.status == 0
    assert excinfo.value.code == "deltaPageLimitExceeded"
    assert len(collected) == 1
    assert len(seen) == ONE_REQUEST


async def test_iter_delta_max_pages_two_is_enough() -> None:
    handler, seen = queue_handler([ok_page("delta_page1.json"), ok_page("delta_page2.json")])
    client = make_client(handler)

    async with client.http:
        pages = [change_set async for change_set in iter_delta(client, DRIVE_ID, None, 2)]

    assert len(seen) == TWO_REQUESTS
    assert len(pages) == TWO_PAGES


async def test_iter_delta_is_lazy() -> None:
    handler, seen = queue_handler([ok_page("delta_page1.json"), ok_page("delta_page2.json")])
    client = make_client(handler)

    async with client.http:
        generator = iter_delta(client, DRIVE_ID, None, DEFAULT_PAGE_LIMIT)
        first = await anext(generator)
        await generator.aclose()

    assert len(seen) == ONE_REQUEST
    assert first.cursor is None
    assert len(first.items) == PAGE1_ITEMS


async def test_client_delta_method_end_to_end() -> None:
    delta_link = load_fixture("delta_page2.json")["@odata.deltaLink"]
    handler, seen = queue_handler([ok_page("delta_page1.json"), ok_page("delta_page2.json")])
    client = make_client(handler)

    async with client.http:
        pages = [change_set async for change_set in client.delta(DRIVE_ID, None)]

    assert len(seen) == TWO_REQUESTS
    assert len(pages) == TWO_PAGES
    assert pages[0].cursor is None
    assert pages[1].cursor == delta_link
    assert all(page.reset_required is False for page in pages)
