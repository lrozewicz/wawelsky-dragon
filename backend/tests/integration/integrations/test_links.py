"""Testy linku do dokumentu źródłowego (brief T3, kontrakt WP E4-3a §3).

Cache LRU z TTL pamięta też wyniki negatywne — testy (a) i (d) dowodzą tego przez zmianę
stanu bazy po pierwszym ``resolve``; testy (f) i (g) przez usunięcie mapowania: trafienie
w cache zwraca link, a brak wpisu sięga do bazy.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.container import Container
from app.core.errors import UpstreamError
from app.db.repositories.integrations import (
    MappingRow,
    delete_mapping,
    find_mapping_by_document,
    upsert_container,
    upsert_mapping,
)
from app.db.uow import transaction
from app.integrations import registry
from app.integrations.base import RemoteItem
from app.services.integration_links import DocumentLink, DocumentLinkResolver, LinkNotFound
from tests.fakes.clock import FrozenClock
from tests.fakes.integrations import FakeConnector, fake_load_config, make_item
from tests.integration.integrations.conftest import TIME_MS, make_integration

pytestmark = pytest.mark.db

SM = async_sessionmaker[AsyncSession]
CONTAINER_ID = "c1"
ITEM_ID = "i1"
DRIVE_NAME = "Dokumenty"
DOC_A = "doc-a"
DOC_B = "doc-b"
DOC_C = "doc-c"
NAME_A = "a.docx"
FRESH_PATH = "/Dok/a.docx"
FRESH_URL = "https://sp/a"
LINK_NAME = "b.docx"
LINK_PATH = "/Dok/b.docx"
LINK_URL = "https://sp/b"
STALE_PATH = "/Dok/stary.docx"
STALE_URL = "https://sp/stary"
STALE_MS = TIME_MS - 25 * 60 * 60 * 1000  # ponad 24 h przed zegarem testów
TTL_S = 60
TTL_MS = TTL_S * 1000
LRU_ENTRIES = 2
CALLS_AFTER_ERROR = 2


class LinkFake(FakeConnector):
    """``FakeConnector`` ze skryptowanym ``web_link`` (brief T3 wym. 6)."""

    def __init__(self) -> None:
        super().__init__()
        self.links: dict[tuple[str, str], RemoteItem | None] = {}
        self.error: Exception | None = None

    async def web_link(self, cfg: Any, container_id: str, item_id: str) -> RemoteItem | None:
        self.calls.append(("web_link", container_id, item_id))
        if self.error is not None:
            raise self.error
        return self.links.get((container_id, item_id))


def link_calls(fake: LinkFake) -> int:
    """Liczba wywołań ``web_link`` (C8 liczy wywołania w ``fake.calls``)."""
    return sum(1 for call in fake.calls if call[0] == "web_link")


@pytest.fixture
def link_fake() -> Iterator[LinkFake]:
    """Rejestruje ``LinkFake`` pod typem ``fake`` (taki typ ma integracja z conftest)."""
    fake = LinkFake()
    registry.register("fake", fake, fake_load_config)
    yield fake
    registry.clear()


def resolver(
    container: Container, *, ttl_seconds: int = TTL_S, max_entries: int = 10_000
) -> DocumentLinkResolver:
    """Resolver na kontenerze testowym z domyślnym TTL i pełnym LRU (kontrakt §3)."""
    return DocumentLinkResolver(container, ttl_seconds, max_entries=max_entries)


async def seed(  # noqa: PLR0913 — skrót testowy z domyślnymi polami mapowania
    sm: SM,
    *,
    document_id: str,
    path: str | None = None,
    web_url: str | None = None,
    updated_at: int = TIME_MS,
    item_id: str = ITEM_ID,
) -> int:
    """Integracja ``fake`` + kontener + mapowanie dokumentu; zwraca ``integration_id``."""
    integration_id = await make_integration(sm)
    async with transaction(sm) as session:
        await upsert_container(
            session, integration_id, CONTAINER_ID, name=DRIVE_NAME, now_ms=TIME_MS
        )
        await upsert_mapping(
            session,
            MappingRow(
                integration_id=integration_id,
                container_id=CONTAINER_ID,
                item_id=item_id,
                document_id=document_id,
                content_tag="ct",
                meta_tag="mt",
                name=NAME_A,
                path=path,
                web_url=web_url,
                last_status="ok",
                last_error=None,
                updated_at=updated_at,
            ),
        )
    return integration_id


async def mapping_of(sm: SM, document_id: str) -> MappingRow | None:
    """Wiersz mapowania z bazy (sprawdzenie odświeżenia linku)."""
    async with transaction(sm) as session:
        return await find_mapping_by_document(session, document_id)


async def drop_mapping(sm: SM, integration_id: int) -> None:
    """Kasuje mapowanie, żeby odróżnić trafienie w cache od ponownego czytania bazy."""
    async with transaction(sm) as session:
        await delete_mapping(session, integration_id, CONTAINER_ID, ITEM_ID)


async def test_no_mapping_is_negative_cached(
    container: Container, sm: SM, link_fake: LinkFake
) -> None:
    """Brak mapowania → ``no_mapping``; kolejne wywołanie nie sięga do bazy (wym. 6a)."""
    links = resolver(container)
    with pytest.raises(LinkNotFound) as excinfo:
        await links.resolve(DOC_A)
    assert excinfo.value.reason == "no_mapping"
    assert str(excinfo.value) == "No SharePoint mapping for this document"
    await seed(sm, document_id=DOC_A, path=FRESH_PATH, web_url=FRESH_URL)
    with pytest.raises(LinkNotFound) as again:
        await links.resolve(DOC_A)
    assert again.value.reason == "no_mapping"


async def test_fresh_mapping_skips_connector(
    container: Container, sm: SM, link_fake: LinkFake
) -> None:
    """Świeży mapping z web_url i path → link z bazy, bez konektora (wym. 6b)."""
    await seed(sm, document_id=DOC_A, path=FRESH_PATH, web_url=FRESH_URL)
    link = await resolver(container).resolve(DOC_A)
    assert link == DocumentLink(FRESH_URL, NAME_A, FRESH_PATH, DRIVE_NAME)
    assert link_calls(link_fake) == 0


async def test_stale_mapping_refreshed_from_connector(
    container: Container, sm: SM, link_fake: LinkFake
) -> None:
    """Stary mapping → ``web_link``, odświeżenie wiersza i cache (wym. 6c)."""
    await seed(sm, document_id=DOC_A, path=STALE_PATH, web_url=STALE_URL, updated_at=STALE_MS)
    link_fake.links[(CONTAINER_ID, ITEM_ID)] = make_item(
        web_url=LINK_URL, name=LINK_NAME, path=LINK_PATH
    )
    links = resolver(container)
    link = await links.resolve(DOC_A)
    assert link == DocumentLink(LINK_URL, LINK_NAME, LINK_PATH, DRIVE_NAME)
    refreshed = await mapping_of(sm, DOC_A)
    assert refreshed is not None
    assert (refreshed.web_url, refreshed.path, refreshed.name) == (LINK_URL, LINK_PATH, LINK_NAME)
    assert await links.resolve(DOC_A) == link
    assert link_calls(link_fake) == 1


async def test_missing_item_negative_cached(
    container: Container, sm: SM, link_fake: LinkFake
) -> None:
    """``web_link`` → ``None`` → ``item_not_found`` i wynik negatywny w cache (wym. 6d)."""
    await seed(sm, document_id=DOC_A, path=STALE_PATH, web_url=STALE_URL, updated_at=STALE_MS)
    links = resolver(container)
    with pytest.raises(LinkNotFound) as excinfo:
        await links.resolve(DOC_A)
    assert excinfo.value.reason == "item_not_found"
    assert str(excinfo.value) == "Item no longer exists in SharePoint"
    link_fake.links[(CONTAINER_ID, ITEM_ID)] = make_item(web_url=LINK_URL)
    with pytest.raises(LinkNotFound) as again:
        await links.resolve(DOC_A)
    assert again.value.reason == "item_not_found"
    assert link_calls(link_fake) == 1


async def test_connector_error_is_upstream_without_cache(
    container: Container, sm: SM, link_fake: LinkFake
) -> None:
    """Wyjątek konektora → ``UpstreamError`` i brak wpisu w cache (wym. 6e)."""
    await seed(sm, document_id=DOC_A, path=STALE_PATH, web_url=STALE_URL, updated_at=STALE_MS)
    link_fake.error = RuntimeError("boom")
    links = resolver(container)
    with pytest.raises(UpstreamError) as excinfo:
        await links.resolve(DOC_A)
    assert str(excinfo.value) == "boom"
    with pytest.raises(UpstreamError):
        await links.resolve(DOC_A)
    assert link_calls(link_fake) == CALLS_AFTER_ERROR


async def test_lru_evicts_oldest_entry(container: Container, sm: SM, link_fake: LinkFake) -> None:
    """``max_entries=2``: trzeci dokument wypycha pierwszy, ten znów czyta bazę (wym. 6f)."""
    ids = {
        doc: await seed(sm, document_id=doc, path=FRESH_PATH, web_url=FRESH_URL)
        for doc in (DOC_A, DOC_B, DOC_C)
    }
    links = resolver(container, max_entries=LRU_ENTRIES)
    for doc in (DOC_A, DOC_B, DOC_C):
        await links.resolve(doc)
    for integration_id in ids.values():
        await drop_mapping(sm, integration_id)
    assert (await links.resolve(DOC_B)).web_url == FRESH_URL
    assert (await links.resolve(DOC_C)).web_url == FRESH_URL
    with pytest.raises(LinkNotFound) as excinfo:
        await links.resolve(DOC_A)
    assert excinfo.value.reason == "no_mapping"


async def test_ttl_expiry_drops_entry(
    container: Container, sm: SM, link_fake: LinkFake, clock: FrozenClock
) -> None:
    """Po TTL wpis wygasa: resolve znów czyta bazę (wym. 6g)."""
    integration_id = await seed(sm, document_id=DOC_A, path=FRESH_PATH, web_url=FRESH_URL)
    links = resolver(container)
    first = await links.resolve(DOC_A)
    await drop_mapping(sm, integration_id)
    assert await links.resolve(DOC_A) == first  # wpis jeszcze żyje — bez bazy
    clock.advance(TTL_MS + 1)
    with pytest.raises(LinkNotFound) as excinfo:
        await links.resolve(DOC_A)
    assert excinfo.value.reason == "no_mapping"
