"""Testy graph_download: redirect bez Authorization, strumień, limit, SHA-256 (WP E4-2a)."""

import hashlib
import logging
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import httpx
import pytest

from app.integrations.sharepoint.errors import GraphError, GraphNotFound, SizeLimitExceeded
from app.integrations.sharepoint.graph import GraphClient
from app.integrations.sharepoint.graph_download import download_item
from tests.unit.integrations.sharepoint.conftest import make_client

DOWNLOAD_HOST = "download.example.net"
DOWNLOAD_URL = f"https://{DOWNLOAD_HOST}/blob?sig=XYZ"
CONTENT_URL = "/drives/b!d1/items/i1/content"
HELLO = b"hello"
HELLO_SHA256 = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
CONTENT = b"aaabbbccc"
CONTENT_SHA256 = hashlib.sha256(CONTENT).hexdigest()
CHUNKS = [b"aaa", b"bbb", b"ccc"]
GENEROUS_LIMIT = 1024
SMALL_LIMIT = 5
EXACT_LIMIT = 9
DECLARED_LENGTH = 100
CONTENT_LENGTH_LIMIT = 50
HELLO_LIMIT = 10
TIGHT_LIMIT = 4
ONE_REQUEST = 1
TWO_REQUESTS = 2
ONE_READ = 1
NO_READS = 0

Handler = Callable[[httpx.Request], httpx.Response]


class CountingStream(httpx.AsyncByteStream):
    """Strumień w podanych kawałkach; liczy próby odczytu (dowód braku odczytu)."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.reads = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self.reads += 1
        for chunk in self._chunks:
            yield chunk


class FailingStream(httpx.AsyncByteStream):
    """Strumień, który po pierwszym kawałku zgłasza `httpx.ReadError`."""

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b"aaa"
        raise httpx.ReadError("stream broken")


def redirect_response() -> httpx.Response:
    """302 z pre-signed URL hosta docelowego (jak Graph przy `/content`)."""
    return httpx.Response(302, headers={"Location": DOWNLOAD_URL})


def open_client(
    graph_response: httpx.Response, download_response: httpx.Response
) -> tuple[GraphClient, list[httpx.Request]]:
    """Klient obsługujący dwa hosty (Graph i docelowy) oraz lista odebranych żądań."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == DOWNLOAD_HOST:
            return download_response
        return graph_response

    return make_client(handler), seen


async def test_redirect_second_request_has_no_authorization(tmp_path: Path) -> None:
    """Krok 2 idzie na host docelowy bez nagłówka `Authorization`; krok 1 ma Bearer."""
    stream = CountingStream(CHUNKS)
    client, seen = open_client(redirect_response(), httpx.Response(200, stream=stream))
    dest = tmp_path / "file.bin"
    async with client.http:
        result = await client.download("b!d1", "i1", dest, GENEROUS_LIMIT)

    assert result == (len(CONTENT), CONTENT_SHA256)
    assert dest.read_bytes() == CONTENT
    assert stream.reads == ONE_READ
    assert len(seen) == TWO_REQUESTS
    assert str(seen[0].url).endswith(CONTENT_URL)
    assert seen[0].headers["Authorization"] == "Bearer tok-1"
    assert seen[1].url.host == DOWNLOAD_HOST
    assert "authorization" not in seen[1].headers


async def test_module_function_downloads_stream(tmp_path: Path) -> None:
    """`download_item` (poziom modułu) zapisuje strumień i liczy SHA-256."""
    client, _ = open_client(redirect_response(), httpx.Response(200, stream=CountingStream(CHUNKS)))
    dest = tmp_path / "file.bin"
    async with client.http:
        result = await download_item(client, "b!d1", "i1", dest, GENEROUS_LIMIT)

    assert result == (len(CONTENT), CONTENT_SHA256)
    assert dest.read_bytes() == CONTENT


async def test_size_limit_exceeded_removes_dest(tmp_path: Path) -> None:
    """Przekroczenie `max_bytes` w trakcie strumienia usuwa plik i zgłasza wyjątek."""
    client, _ = open_client(redirect_response(), httpx.Response(200, stream=CountingStream(CHUNKS)))
    dest = tmp_path / "file.bin"
    async with client.http:
        with pytest.raises(SizeLimitExceeded) as excinfo:
            await client.download("b!d1", "i1", dest, SMALL_LIMIT)

    assert excinfo.value.max_bytes == SMALL_LIMIT
    assert dest.exists() is False


async def test_exact_size_limit_is_allowed(tmp_path: Path) -> None:
    """Dokładnie `max_bytes` bajtów nie jest przekroczeniem limitu."""
    client, _ = open_client(redirect_response(), httpx.Response(200, stream=CountingStream(CHUNKS)))
    dest = tmp_path / "file.bin"
    async with client.http:
        result = await client.download("b!d1", "i1", dest, EXACT_LIMIT)

    assert result == (len(CONTENT), CONTENT_SHA256)
    assert dest.read_bytes() == CONTENT


async def test_content_length_over_limit_is_not_read(tmp_path: Path) -> None:
    """`Content-Length` > limit przerywa przed zapisem i przed odczytem treści."""
    stream = CountingStream(CHUNKS)
    response = httpx.Response(200, headers={"Content-Length": str(DECLARED_LENGTH)}, stream=stream)
    client, _ = open_client(redirect_response(), response)
    dest = tmp_path / "file.bin"
    async with client.http:
        with pytest.raises(SizeLimitExceeded) as excinfo:
            await client.download("b!d1", "i1", dest, CONTENT_LENGTH_LIMIT)

    assert excinfo.value.max_bytes == CONTENT_LENGTH_LIMIT
    assert dest.exists() is False
    assert stream.reads == NO_READS


async def test_non_numeric_content_length_falls_back_to_byte_count(tmp_path: Path) -> None:
    """Nieparsowalny `Content-Length` jest ignorowany; limit pilnuje licznik bajtów."""
    stream = CountingStream([HELLO])
    response = httpx.Response(200, headers={"Content-Length": "abc"}, stream=stream)
    client, _ = open_client(redirect_response(), response)
    dest = tmp_path / "file.bin"
    async with client.http:
        result = await client.download("b!d1", "i1", dest, HELLO_LIMIT)

    assert result == (len(HELLO), HELLO_SHA256)
    assert dest.read_bytes() == HELLO


async def test_unicode_digit_content_length_is_ignored(tmp_path: Path) -> None:
    """Nagłówek `Content-Length` z cyfrą Unicode nie wywraca zapisu — decyduje licznik bajtów."""
    stream = CountingStream([HELLO])
    # Bajt 0xB2 to w latin-1 „²": `isdigit()` prawdziwe, ale `int()` rzuca ValueError —
    # dlatego filtr nagłówka to `isdecimal()` (gwarantuje przyjęcie przez `int()`).
    headers = httpx.Headers([(b"content-length", b"\xb2")])
    response = httpx.Response(200, headers=headers, stream=stream)
    client, _ = open_client(redirect_response(), response)
    dest = tmp_path / "file.bin"
    async with client.http:
        result = await client.download("b!d1", "i1", dest, HELLO_LIMIT)

    assert result == (len(HELLO), HELLO_SHA256)
    assert dest.read_bytes() == HELLO


async def test_missing_content_length_enforces_byte_count(tmp_path: Path) -> None:
    """Brak `Content-Length` nie omija limitu — decyduje licznik zapisanych bajtów."""
    client, _ = open_client(redirect_response(), httpx.Response(200, stream=CountingStream(CHUNKS)))
    dest = tmp_path / "file.bin"
    async with client.http:
        with pytest.raises(SizeLimitExceeded):
            await client.download("b!d1", "i1", dest, SMALL_LIMIT)

    assert dest.exists() is False


async def test_target_host_404_raises_not_found(tmp_path: Path) -> None:
    """404 z hosta docelowego → `GraphNotFound`, bez pliku."""
    client, _ = open_client(redirect_response(), httpx.Response(httpx.codes.NOT_FOUND))
    dest = tmp_path / "file.bin"
    async with client.http:
        with pytest.raises(GraphNotFound) as excinfo:
            await client.download("b!d1", "i1", dest, GENEROUS_LIMIT)

    assert excinfo.value.status == httpx.codes.NOT_FOUND
    assert dest.exists() is False


async def test_target_host_error_raises_graph_error(tmp_path: Path) -> None:
    """500 z hosta docelowego → `GraphError` (nie `GraphNotFound`), bez pliku."""
    client, _ = open_client(redirect_response(), httpx.Response(httpx.codes.INTERNAL_SERVER_ERROR))
    dest = tmp_path / "file.bin"
    async with client.http:
        with pytest.raises(GraphError) as excinfo:
            await client.download("b!d1", "i1", dest, GENEROUS_LIMIT)

    assert not isinstance(excinfo.value, GraphNotFound)
    assert excinfo.value.status == httpx.codes.INTERNAL_SERVER_ERROR
    assert excinfo.value.code == ""
    assert dest.exists() is False


async def test_stream_error_removes_partial_file(tmp_path: Path) -> None:
    """Błąd w trakcie strumienia propaguje i usuwa częściowy plik."""
    client, _ = open_client(redirect_response(), httpx.Response(200, stream=FailingStream()))
    dest = tmp_path / "file.bin"
    async with client.http:
        with pytest.raises(httpx.ReadError):
            await client.download("b!d1", "i1", dest, GENEROUS_LIMIT)

    assert dest.exists() is False


async def test_direct_content_response_writes_body_without_second_request(tmp_path: Path) -> None:
    """200 bez redirectu: treść z kroku 1 trafia do pliku bez dodatkowego żądania."""
    client, seen = open_client(httpx.Response(200, content=HELLO), httpx.Response(500))
    dest = tmp_path / "file.bin"
    async with client.http:
        result = await client.download("b!d1", "i1", dest, HELLO_LIMIT)

    assert result == (len(HELLO), HELLO_SHA256)
    assert dest.read_bytes() == HELLO
    assert len(seen) == ONE_REQUEST


async def test_direct_content_response_over_limit_writes_nothing(tmp_path: Path) -> None:
    """200 bez redirectu i treść ponad limit → `SizeLimitExceeded`, plik nie powstaje."""
    client, _ = open_client(httpx.Response(200, content=HELLO), httpx.Response(500))
    dest = tmp_path / "file.bin"
    async with client.http:
        with pytest.raises(SizeLimitExceeded) as excinfo:
            await client.download("b!d1", "i1", dest, TIGHT_LIMIT)

    assert excinfo.value.max_bytes == TIGHT_LIMIT
    assert dest.exists() is False


async def test_graph_404_at_first_step_raises_not_found(tmp_path: Path) -> None:
    """404 z Graph na kroku 1 → `GraphNotFound` (bez strumienia na host docelowy)."""
    client, seen = open_client(httpx.Response(httpx.codes.NOT_FOUND), httpx.Response(200))
    dest = tmp_path / "file.bin"
    async with client.http:
        with pytest.raises(GraphNotFound):
            await client.download("b!d1", "i1", dest, GENEROUS_LIMIT)

    assert len(seen) == ONE_REQUEST
    assert dest.exists() is False


async def test_redirect_without_location_raises_graph_error(tmp_path: Path) -> None:
    """3xx bez `Location` → `GraphError(status, "redirect", "missing Location")`."""
    client, seen = open_client(httpx.Response(httpx.codes.FOUND), httpx.Response(200))
    dest = tmp_path / "file.bin"
    async with client.http:
        with pytest.raises(GraphError) as excinfo:
            await client.download("b!d1", "i1", dest, GENEROUS_LIMIT)

    assert excinfo.value.status == httpx.codes.FOUND
    assert excinfo.value.code == "redirect"
    assert excinfo.value.message == "missing Location"
    assert len(seen) == ONE_REQUEST
    assert dest.exists() is False


async def test_logs_never_contain_token_or_signature(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Retry i pobranie nie zostawiają w logach tokenu, nagłówka ani pre-signed URL."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == DOWNLOAD_HOST:
            return httpx.Response(200, stream=CountingStream([HELLO]))
        calls.append(1)
        if len(calls) == ONE_REQUEST:
            return httpx.Response(httpx.codes.TOO_MANY_REQUESTS)
        return redirect_response()

    client = make_client(handler)
    dest = tmp_path / "file.bin"
    # Poziom tylko dla naszego loggera: httpx na INFO sam loguje pełne URL-e (poza zakresem WP).
    caplog.set_level(logging.DEBUG, logger="app.integrations.sharepoint")
    async with client.http:
        result = await client.download("b!d1", "i1", dest, GENEROUS_LIMIT)

    assert result == (len(HELLO), HELLO_SHA256)
    assert "graph retry" in caplog.text
    for fragment in ("Bearer", "tok-", "sig=XYZ"):
        assert fragment not in caplog.text
