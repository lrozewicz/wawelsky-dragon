"""Pobieranie treści driveItem z Graph: redirect bez Authorization, strumień, limit (WP E4-2a)."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from app.integrations.sharepoint.errors import GraphError, GraphNotFound, SizeLimitExceeded

if TYPE_CHECKING:
    from app.integrations.sharepoint.graph import GraphClient

NOT_FOUND_STATUSES = frozenset({httpx.codes.NOT_FOUND, httpx.codes.GONE})


async def download_item(
    client: GraphClient, drive_id: str, item_id: str, dest: Path, max_bytes: int
) -> tuple[int, str]:
    """Pobiera `/content` do `dest`; zwraca `(size, sha256_hex)`.

    Krok 1 (`request_redirect`) dokłada `Authorization` i zwraca 3xx bez follow;
    krok 2 to strumień z `Location` **bez** nagłówka autoryzacyjnego.
    """
    response = await client.request_redirect(f"/drives/{drive_id}/items/{item_id}/content")
    if not response.is_redirect:
        # Rzadki przypadek: Graph oddaje treść od razu (bez pre-signed URL) — ciało już w RAM.
        content = response.content
        if len(content) > max_bytes:
            raise SizeLimitExceeded(max_bytes)
        # DEC-058: blokujący zapis do `to_thread` (ta sama operacja co w kontrakcie).
        await asyncio.to_thread(dest.write_bytes, content)
        return len(content), hashlib.sha256(content).hexdigest()

    location = response.headers.get("Location")
    if location is None:
        raise GraphError(response.status_code, "redirect", "missing Location")
    async with client.http.stream("GET", location) as stream_response:
        return await _save_stream(stream_response, dest, max_bytes)


async def _save_stream(response: httpx.Response, dest: Path, max_bytes: int) -> tuple[int, str]:
    """Zapisuje strumień odpowiedzi do `dest` z kontrolą `max_bytes` i SHA-256."""
    status = response.status_code
    if status in NOT_FOUND_STATUSES:
        raise GraphNotFound(status, "", response.reason_phrase)
    if not httpx.codes.OK <= status < httpx.codes.MULTIPLE_CHOICES:
        raise GraphError(status, "", response.reason_phrase)

    declared = response.headers.get("Content-Length")
    # `isdecimal` (nie `isdigit`): gwarantuje, że `int()` przyjmie nagłówek (np. "²" już nie).
    if declared is not None and declared.isdecimal() and int(declared) > max_bytes:
        raise SizeLimitExceeded(max_bytes)

    digest = hashlib.sha256()
    total = 0
    try:
        with dest.open("wb") as handle:
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise SizeLimitExceeded(max_bytes)
                digest.update(chunk)
                handle.write(chunk)
    except BaseException:
        # Częściowy plik nie może zostać na dysku (błąd sieci, przerwanie, limit).
        # DEC-058: blokujące `pathlib` w `async def` przez `to_thread`.
        await asyncio.to_thread(dest.unlink, missing_ok=True)
        raise
    return total, digest.hexdigest()
