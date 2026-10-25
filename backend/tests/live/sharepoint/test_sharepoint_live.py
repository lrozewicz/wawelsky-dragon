"""Testy live konektora SharePoint na prawdziwym tenancie (marker ``sharepoint_live``).

Uruchamia je TL: ``tools/dev/live.sh sharepoint-live``. Bez ``WD_SP_TEST_*`` testy są pomijane.
Wartości tenanta nie pojawiają się w asercjach ani w komunikatach — porównujemy wyłącznie
identyfikatory i nazwy plików utworzonych przez test (``wd-live-<uuid>.txt``).

Cykl zapisu idzie własnym klientem ``httpx`` z tokenem z ``TokenProvider``: ``GraphClient.request``
przyjmuje wyłącznie ``params``, więc ``PUT``/``PATCH``/``DELETE`` z ciałem nie mają tam drogi.
"""

from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from app.integrations.base import Container, RemoteItem
from app.integrations.sharepoint.auth import TokenProvider
from app.integrations.sharepoint.config import SharePointConfig
from app.integrations.sharepoint.connector import SharePointConnector

pytestmark = [pytest.mark.sharepoint_live, pytest.mark.live]

CONTENT = b"wawelsky dragon live\n"
CONTENT_TYPE = "text/plain"
LIVE_PREFIX = "wd-live-"
MISSING_STATUSES = frozenset({httpx.codes.NOT_FOUND, httpx.codes.GONE})


class MutatingGraph:
    """Zapis do Graph (``PUT``/``PATCH``/``DELETE``) na gołym kliencie ``httpx``."""

    def __init__(self, http: httpx.AsyncClient, tokens: TokenProvider) -> None:
        self._http = http
        self._tokens = tokens

    async def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {await self._tokens.get_token()}"}

    async def create_file(self, drive_id: str, name: str, content: bytes) -> str:
        """``PUT /drives/{id}/root:/<name>:/content``; zwraca ``id`` utworzonego elementu."""
        response = await self._http.put(
            f"/drives/{drive_id}/root:/{name}:/content",
            content=content,
            headers={**await self._headers(), "Content-Type": CONTENT_TYPE},
        )
        response.raise_for_status()
        body = response.json()
        return str(body["id"])

    async def rename(self, drive_id: str, item_id: str, name: str) -> None:
        """``PATCH /drives/{id}/items/{item}`` z nową nazwą."""
        response = await self._http.patch(
            f"/drives/{drive_id}/items/{item_id}",
            json={"name": name},
            headers=await self._headers(),
        )
        response.raise_for_status()

    async def delete(self, drive_id: str, item_id: str) -> None:
        """``DELETE`` elementu; brak elementu (404/410) nie jest błędem sprzątania."""
        response = await self._http.delete(
            f"/drives/{drive_id}/items/{item_id}", headers=await self._headers()
        )
        if response.status_code not in MISSING_STATUSES:
            response.raise_for_status()


@pytest.fixture
def mutator(sp_http: httpx.AsyncClient, sp_tokens: TokenProvider) -> MutatingGraph:
    """Operacje zapisu Graph na kliencie live (sprzątanie w ``finally`` testu)."""
    return MutatingGraph(sp_http, sp_tokens)


async def read_delta(
    connector: SharePointConnector,
    cfg: SharePointConfig,
    container: Container,
    cursor: str | None,
) -> tuple[list[RemoteItem], str]:
    """Zbiera deltę od ``cursor``; zwraca ``(elementy, nowy deltaLink)``."""
    sets = [change_set async for change_set in connector.changes(cfg, container, cursor)]
    items = [item for change_set in sets for item in change_set.items]
    delta_link = sets[-1].cursor
    assert delta_link, "delta nie zwróciła deltaLink (kursor do zapisania)"
    return items, delta_link


async def library(connector: SharePointConnector, cfg: SharePointConfig) -> Container:
    """Pierwsza biblioteka dokumentów tenanta testowego."""
    containers = await connector.list_containers(cfg)
    assert containers, "tenant nie ma żadnej biblioteki dokumentów"
    return containers[0]


async def test_connection_reports_ok(
    connector: SharePointConnector, sp_config: SharePointConfig
) -> None:
    """Test połączenia na prawdziwym tenancie: token, witryna i biblioteki są ok."""
    report = await connector.test_connection(sp_config, dataset_exists=True)

    assert report.ok is True
    statuses = {str(check["name"]): check["status"] for check in report.checks}
    assert statuses["graph_auth"] == "ok"
    assert statuses["site_resolution"] == "ok"
    assert report.resolved["site_id"]


async def test_resolve_containers_and_delta(
    connector: SharePointConnector, sp_config: SharePointConfig
) -> None:
    """Rozwiązanie witryny, biblioteki i pierwsza strona delty z kursorem."""
    resolved = await connector.resolve(sp_config)
    assert resolved["site_id"]

    first = await library(connector, sp_config)
    assert first.id

    sets = [change_set async for change_set in connector.changes(sp_config, first, None)]
    assert sets, "delta nie zwróciła żadnej strony"
    assert sets[-1].cursor


async def test_file_lifecycle_visible_in_delta(
    connector: SharePointConnector,
    sp_config: SharePointConfig,
    mutator: MutatingGraph,
    tmp_path: Path,
) -> None:
    """Cykl utworzenie → pobranie → zmiana nazwy → usunięcie widoczny w delcie."""
    target = await library(connector, sp_config)
    _, cursor = await read_delta(connector, sp_config, target, None)

    name = f"{LIVE_PREFIX}{uuid4().hex}.txt"
    renamed = f"{LIVE_PREFIX}{uuid4().hex}.txt"
    item_id = ""
    try:
        item_id = await mutator.create_file(target.id, name, CONTENT)

        items, cursor = await read_delta(connector, sp_config, target, cursor)
        created = [item for item in items if item.name == name]
        assert created, "delta nie widzi utworzonego pliku"
        assert created[0].item_id == item_id

        dest = tmp_path / name
        size = await connector.download(
            sp_config, created[0], dest, max_bytes=sp_config.max_file_size_bytes
        )
        assert size == len(CONTENT)
        assert dest.read_bytes() == CONTENT

        await mutator.rename(target.id, item_id, renamed)
        items, cursor = await read_delta(connector, sp_config, target, cursor)
        assert [item.item_id for item in items if item.name == renamed] == [item_id]

        remote = await connector.web_link(sp_config, target.id, item_id)
        assert remote is not None
        assert remote.item_id == item_id
        assert remote.name == renamed

        await mutator.delete(target.id, item_id)
        items, _ = await read_delta(connector, sp_config, target, cursor)
        deleted = [item for item in items if item.item_id == item_id]
        assert deleted and deleted[-1].deleted
    finally:
        if item_id:
            await mutator.delete(target.id, item_id)


async def test_web_link_unknown_item_returns_none(
    connector: SharePointConnector,
    sp_config: SharePointConfig,
    mutator: MutatingGraph,
) -> None:
    """Usunięty element o POPRAWNYM identyfikatorze → ``None`` (Graph oddaje 404/410).

    Losowo sklecony napis nie jest poprawnym id driveItem — Graph odpowiada nań
    400 ``invalidRequest``, a nie 404, więc identyfikator bierzemy z realnego pliku.
    """
    target = await library(connector, sp_config)
    name = f"{LIVE_PREFIX}{uuid4().hex}.txt"
    item_id = await mutator.create_file(target.id, name, CONTENT)
    try:
        await mutator.delete(target.id, item_id)
        assert await connector.web_link(sp_config, target.id, item_id) is None
    finally:
        await mutator.delete(target.id, item_id)
