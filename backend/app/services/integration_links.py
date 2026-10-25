"""Link do dokumentu źródłowego integracji (09 §9, ``documents.ts:82-145``) — kontrakt E4-3a §3.

``document_id`` → mapowanie z bazy (świeże wystarcza), inaczej konektor z rejestru.
Cache LRU z TTL pamięta też wyniki negatywne, żeby kliknięcie nie odpytywało ni bazy, ni Grapha.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import NotFound, UpstreamError
from app.db.repositories import integrations as integrations_repo
from app.db.uow import transaction
from app.integrations import registry

if TYPE_CHECKING:
    from app.core.container import Container

MAPPING_FRESH_MS = 24 * 60 * 60 * 1000
NO_MAPPING_MESSAGE = "No SharePoint mapping for this document"
ITEM_GONE_MESSAGE = "Item no longer exists in SharePoint"


@dataclass(frozen=True)
class DocumentLink:
    """Link do elementu źródłowego (kontrakt E4-3a §3)."""

    web_url: str
    name: str | None
    path: str | None
    drive_name: str | None


class LinkNotFound(NotFound):
    """Brak linku; ``reason`` jedzie do koperty trasy (``no_mapping``/``item_not_found``)."""

    reason: str

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


class DocumentLinkResolver:
    """Mapping → link, z cache LRU/TTL i odświeżaniem przez konektor (kontrakt E4-3a §3)."""

    def __init__(
        self, container: Container, ttl_seconds: int, *, max_entries: int = 10_000
    ) -> None:
        self._container = container
        self._ttl_ms = ttl_seconds * 1000  # 0 = cache wyłączony
        self._max_entries = max_entries
        self._cache: OrderedDict[str, tuple[int, DocumentLink | tuple[str, str]]] = OrderedDict()

    async def resolve(self, document_id: str) -> DocumentLink:
        """Zwraca link dokumentu; wyniki negatywne trafiają do cache tak samo (kontrakt §3 p. 1)."""
        now_ms = self._container.clock.now_ms()
        cached = self._cache_get(document_id, now_ms)
        if cached is not None:
            if isinstance(cached, DocumentLink):
                return cached
            raise LinkNotFound(cached[1], cached[0])
        try:
            link = await self._fetch(document_id, now_ms)
        except LinkNotFound as exc:
            self._cache_put(document_id, (exc.reason, exc.message), now_ms)
            raise
        self._cache_put(document_id, link, now_ms)
        return link

    async def _fetch(self, document_id: str, now_ms: int) -> DocumentLink:
        """Mapowanie z bazy; świeże bez sieci, w przeciwnym razie konektor (kontrakt §3 p. 2-4)."""
        async with transaction(self._sessionmaker()) as session:
            mapping = await integrations_repo.find_mapping_by_document(session, document_id)
            if mapping is None:
                raise LinkNotFound(NO_MAPPING_MESSAGE, "no_mapping")
            target = await integrations_repo.get_container(
                session, mapping.integration_id, mapping.container_id
            )
            drive_name = None if target is None else target.name
            if mapping.web_url and mapping.path and now_ms - mapping.updated_at < MAPPING_FRESH_MS:
                return DocumentLink(
                    web_url=mapping.web_url,
                    name=mapping.name,
                    path=mapping.path,
                    drive_name=drive_name,
                )
            row = await integrations_repo.get_integration(session, mapping.integration_id)
            if row is None:  # pragma: no cover — mapowania znikają razem z integracją (§1)
                raise LinkNotFound(NO_MAPPING_MESSAGE, "no_mapping")
            connector, load_config = registry.get(row.type)
            cfg = await load_config(row)
            try:
                item = await connector.web_link(cfg, mapping.container_id, mapping.item_id)
            except LinkNotFound:
                raise
            except Exception as exc:  # błąd konektora ⇒ 502 (kontrakt §3 p. 5)
                raise UpstreamError(str(exc)) from exc
            if item is None or item.web_url is None:
                raise LinkNotFound(ITEM_GONE_MESSAGE, "item_not_found")
            await integrations_repo.update_mapping_link(
                session,
                mapping.integration_id,
                mapping.container_id,
                mapping.item_id,
                name=item.name,
                path=item.path,
                web_url=item.web_url,
                now_ms=now_ms,
            )
            return DocumentLink(
                web_url=item.web_url,
                name=item.name,
                path=item.path,
                drive_name=drive_name,
            )

    def _sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        """Fabryka sesji z kontenera; brak (kontener nie wystartował) → RuntimeError (C7)."""
        sessionmaker = self._container.sessionmaker
        if sessionmaker is None:
            raise RuntimeError("container not started")
        return sessionmaker

    def _cache_get(self, document_id: str, now_ms: int) -> DocumentLink | tuple[str, str] | None:
        """Trafienie LRU; wygasły wpis kasuje i zwraca ``None`` (kontrakt §3 p. 1)."""
        if self._ttl_ms == 0:
            return None
        entry = self._cache.get(document_id)
        if entry is None:
            return None
        expires_ms, value = entry
        if expires_ms <= now_ms:
            del self._cache[document_id]
            return None
        self._cache.move_to_end(document_id)
        return value

    def _cache_put(
        self, document_id: str, value: DocumentLink | tuple[str, str], now_ms: int
    ) -> None:
        """Wpis z TTL i wyrzuceniem najstarszego ponad ``max_entries`` (kontrakt §3 p. 1)."""
        if self._ttl_ms == 0:
            return
        self._cache[document_id] = (now_ms + self._ttl_ms, value)
        self._cache.move_to_end(document_id)
        while len(self._cache) > self._max_entries:
            self._cache.popitem(last=False)
