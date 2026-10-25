"""Usługa tras plikowych dokumentów (E2-1 DOC2, kroki 19-33 złota ``documents_extras``).

``POST /documents/ingest`` (start/anulowanie parsowania), ``POST /documents/upload`` (plik
bez datasetu), ``GET /documents/{id}`` i ``/documents/{id}/preview`` (strumień pliku),
``GET /thumbnails`` (mapa doc_id → thumbnail) oraz ``GET /documents/images/{id}``.

Trasy nie mają datasetu w ścieżce, więc uprawnienia sprawdzane są przez ``dataset_id``
dokumentu i wyłącznie przez ``DatasetService.load`` (jedyne miejsce sprawdzania datasetu —
C1.2). ``Container`` pod ``TYPE_CHECKING`` (wzór: ``app/services/documents.py``).
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import NotFound, WDError
from app.db.repositories import documents as documents_repo
from app.db.repositories import documents_query
from app.db.repositories.documents import DocumentRow
from app.db.uow import transaction
from app.domain.policy import Action, Principal, visibility_filter
from app.services.datasets import DatasetService
from app.storage.keys import StorageKey, filemanager_key, image_key

if TYPE_CHECKING:
    from app.core.container import Container

__all__ = [
    "MSG_DOC_NOT_FOUND",
    "MSG_IMAGE_NOT_FOUND",
    "DocumentFilesService",
    "UploadedFile",
]

MSG_DOC_NOT_FOUND = "document not found"  # DOC:2103, DOC:2233 (trasy /documents/{id})
MSG_IMAGE_NOT_FOUND = "Image not found."  # DOC:1858, DOC:1862 (/documents/images/{id})


@dataclass(frozen=True)
class UploadedFile:
    """Plik wgrany bez datasetu — odpowiedź ``POST /documents/upload`` (złoto --25)."""

    id: str
    name: str
    size: int
    extension: str
    mime_type: str
    created_by: str
    created_at: float


class DocumentFilesService:
    """Ingest, upload bez datasetu, pobranie/preview pliku, thumbnails i obrazy dokumentów."""

    def __init__(self, container: Container) -> None:
        self._container = container

    def _sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        """Fabryka sesji z kontenera (C0 p. 2)."""
        return cast(async_sessionmaker[AsyncSession], self._container.sessionmaker)

    async def ingest(
        self, principal: Principal, document_ids: Sequence[str], *, run: str, delete: bool
    ) -> None:
        """Start (``run='1'``) albo anulowanie (``run='2'``) parsowania wg id dokumentów.

        Upstream ``DocumentService.accessible`` (DOC:1480) — odpowiednik WD to uprawnienie
        UPDATE do datasetu dokumentu (trasa mutuje dokument); cudzy dokument → 108 (K11 §10c
        p. 9: trasa bez złota błędu zachowuje 108).
        """
        unique_ids = list(dict.fromkeys(document_ids))
        for document_id in unique_ids:
            await self._load(principal, document_id, Action.UPDATE)
        await self._container.ingest.ingest_documents(unique_ids, run=run, delete=delete)

    async def upload(
        self, principal: Principal, name: str, content_type: str, content: bytes
    ) -> UploadedFile:
        """Zapisuje plik poza datasetem i zwraca jego opis (upstream DOC:811-829).

        ``size`` liczone ``sys.getsizeof(blob)`` — dosłownie upstream (DOC:823); dla 1319 B
        daje 1352, czego wymaga złoto --25 (``size`` jest kluczem porównywanym dokładnie).
        """
        suffix = Path(name).suffix.lower().lstrip(".")
        location = self._container.id_gen.new_id()
        await self._container.storage.put(
            filemanager_key(location, suffix),
            content,
            max_bytes=self._container.settings.max_upload_mb * 1024 * 1024,
        )
        return UploadedFile(
            id=location,
            name=name,
            size=sys.getsizeof(content),
            extension=suffix,
            mime_type=content_type,
            created_by=principal.user_id,
            created_at=self._container.clock.now_ms() / 1000.0,
        )

    async def open(
        self, principal: Principal, document_id: str
    ) -> tuple[DocumentRow, AsyncIterator[bytes]]:
        """(wiersz, iterator treści pliku) dla ``GET /documents/{id}`` i ``/preview``."""
        row = await self._load(principal, document_id, Action.READ)
        return row, self._container.storage.open(StorageKey(row.location))

    async def thumbnails(self, principal: Principal, document_ids: Sequence[str]) -> dict[str, str]:
        """Mapa doc_id → thumbnail dokumentów widocznych dla podmiotu (złoto --31)."""
        async with transaction(self._sessionmaker()) as session:
            return await documents_query.thumbnails(
                session, document_ids, visibility=visibility_filter(principal, "document")
            )

    async def legacy_thumbnails(
        self, principal: Principal, document_ids: Sequence[str]
    ) -> dict[str, str]:
        """Mapa doc_id → thumbnail trasy legacy ``GET /v1/document/thumbnails`` (złoto --32).

        Upstream ``DocumentService.get_thumbnails`` (DOC:687) nie sprawdza właściciela
        (``doc_ids`` filtruje wyłącznie po id), a ``/v1/document/thumbnails`` nie ma nawet
        ``@login_required`` (DOC:482 — zakomentowany). WD sprawdza każdy dokument przez
        ``_load`` (CONTRACT C0 p. 9: nigdy sukces na cudzym dokumencie) i oddaje pusty napis,
        bo miniatur nie generuje — złoto --32: ``{"<doc_id>": ""}``.
        """
        unique_ids = list(dict.fromkeys(document_ids))
        for document_id in unique_ids:
            await self._load(principal, document_id, Action.READ)
        return dict.fromkeys(unique_ids, "")

    async def image(self, principal: Principal, image_id: str) -> bytes | None:
        """Treść obrazu dokumentu; brak obiektu, obcy dataset albo złe id → None (--33).

        Upstream ``GET /documents/images/<image_id>`` (DOC:1831) dzieli id po pierwszym
        myślniku na dataset (bucket) i klucz obiektu; WD trzyma obrazy chunków pod
        ``images/{dataset_id}/{object_key}`` (``storage.keys.image_key``).
        """
        dataset_id, _, object_key = image_id.partition("-")
        if not dataset_id or not object_key:
            return None
        try:
            await DatasetService(self._container).load(principal, dataset_id, Action.READ)
            key = image_key(dataset_id, object_key)
        except WDError:  # cudzy/nieistniejący dataset albo klucz spoza [A-Za-z0-9._-]
            return None
        if not await self._container.storage.exists(key):
            return None
        return b"".join([chunk async for chunk in self._container.storage.open(key)])

    async def _load(self, principal: Principal, document_id: str, action: Action) -> DocumentRow:
        """Wiersz dokumentu + uprawnienie do jego datasetu; brak dokumentu → NotFound (--27)."""
        async with transaction(self._sessionmaker()) as session:
            row = await documents_repo.get(session, document_id)
        if row is None:
            raise NotFound(MSG_DOC_NOT_FOUND)
        await DatasetService(self._container).load(principal, row.dataset_id, action)
        return row
