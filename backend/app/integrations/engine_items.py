"""Logika elementu przebiegu — tabela decyzji 09 §6 (kontrakt E4-1 C5).

Jeden ``RemoteItem`` przechodzi wiersze tabeli w kolejności z 09 §6; obsłużony przypadek
kończy przetwarzanie elementu. Pobranie idzie do pliku tymczasowego
``<storage_root>/tmp/<uuid4 hex>``, usuwanego zawsze (także przy wyjątku). ``UploadSource``
wchodzi importem leniwym — moduł nie ciągnie ``app.parsing``, żeby ``import app.worker.main``
pozostał lekki (brief T8, wymaganie 4).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import ValidationFailed
from app.db.repositories import integrations as repo
from app.db.repositories.integrations import MappingRow
from app.db.uow import transaction
from app.integrations.base import RemoteItem

if TYPE_CHECKING:
    from app.core.container import Container
    from app.db.repositories.documents import DocumentRow
    from app.db.repositories.integrations import IntegrationRow
    from app.integrations.audit import RunRecorder
    from app.integrations.base import Connector
    from app.services.ingest import UploadSource

CHUNK_BYTES = 1024 * 1024
MAPPING_OK = "ok"
MAPPING_FAILED = "failed"
ERROR_LIMIT = 2000
SOURCE_TYPE = "sharepoint"


def file_extension(name: str) -> str:
    """Rozszerzenie nazwy (po ostatniej kropce) małymi literami, bez kropki (wiersz 4)."""
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def wd_source(integration: IntegrationRow, item: RemoteItem) -> dict[str, object]:
    """``meta_fields.wd_source`` elementu (kontrakt C5)."""
    return {
        "integration_id": integration.id,
        "type": integration.type,
        "container_id": item.container_id,
        "item_id": item.item_id,
        "path": item.path,
        "web_url": item.web_url,
    }


def source_ref(integration_id: int, item: RemoteItem) -> str:
    """``source_ref`` dokumentu z elementu (kontrakt C5)."""
    return f"{integration_id}:{item.container_id}:{item.item_id}"


def deleted_item(mapping: MappingRow) -> RemoteItem:
    """Element ``deleted`` z mapowania — rekonsyliacja po resecie delty idzie ścieżką wiersza 2.

    Tylko ``container_id``/``item_id`` mają znaczenie; reszta pól bierze się z mapowania.
    """
    return RemoteItem(
        container_id=mapping.container_id,
        item_id=mapping.item_id,
        name=mapping.name or "",
        path=mapping.path or "",
        size=None,
        content_tag=mapping.content_tag,
        meta_tag=mapping.meta_tag,
        modified_at=None,
        web_url=mapping.web_url,
        is_folder=False,
        deleted=True,
    )


async def read_blocks(path: Path) -> AsyncIterator[bytes]:
    """Strumień pliku tymczasowego blokami ``CHUNK_BYTES``; plik zamykany po wyczerpaniu."""
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            yield chunk


class ItemProcessor:
    """Wykonuje decyzję tabeli 09 §6 dla jednego elementu (kontrakt C5).

    Stan obiektu jest stały dla przebiegu (integracja, konektor, rekorder); liczniki
    i zdarzenia idą przez ``recorder``.
    """

    def __init__(
        self,
        container: Container,
        *,
        integration: IntegrationRow,
        connector: Connector,
        cfg: object,
        recorder: RunRecorder,
    ) -> None:
        self._container = container
        self._integration = integration
        self._connector = connector
        self._cfg = cfg
        self._recorder = recorder

    async def process(self, item: RemoteItem) -> None:
        """Decyduje o elemencie; wyjątek → mapping ``failed`` + ``error``, przebieg leci dalej."""
        mapping = await self._get_mapping(item)
        try:
            await self._decide(item, mapping)
        except Exception as exc:  # noqa: BLE001 — wiersz 10: błąd elementu nie przerywa przebiegu
            await self._record_failure(item, mapping, exc)

    async def reconcile_deleted(self, mapping: MappingRow) -> None:
        """Rekonsyliacja po resecie: wiersz 2 dla elementu nieobecnego w pełnym stanie (T8)."""
        await self.process(deleted_item(mapping))

    async def _decide(self, item: RemoteItem, mapping: MappingRow | None) -> None:
        """Wiersze tabeli decyzji w kolejności z 09 §6."""
        if item.is_folder:  # 1
            return
        if item.deleted:  # 2 (z mappingiem) / 3 (bez)
            if mapping is not None:
                await self._delete_item(item, mapping)
            return
        if file_extension(item.name) in self._integration.ignored_extensions:  # 4
            self._recorder.counts.skipped += 1
            return
        if item.size is not None and item.size > self._integration.max_file_size_bytes:  # 5
            self._too_large(item)
            return
        if (
            mapping is None
            or mapping.last_status != MAPPING_OK
            or mapping.content_tag != item.content_tag
        ):  # 9
            await self._reupload(item, mapping)
            return
        if mapping.name != item.name or mapping.path != item.path:  # 7 (ValidationFailed → 9)
            await self._rename(item, mapping)
            return
        if mapping.meta_tag != item.meta_tag:  # 8
            await self._write_mapping(self._mapping_of(item, mapping.document_id, item.content_tag))
        # 6 — brak akcji

    async def _delete_item(self, item: RemoteItem, mapping: MappingRow) -> None:
        """Wiersz 2: propagacja usunięcia do dokumentu plus zdjęcie mapowania."""
        if self._integration.delete_propagation and mapping.document_id is not None:
            try:
                await self._container.ingest.delete_documents([mapping.document_id])
            except Exception as exc:  # noqa: BLE001 — błąd usuwania to tylko warn (wiersz 2)
                self._recorder.event("warn", f"delete failed: {exc}", file_path=mapping.path)
                return
        await self._delete_mapping(item)
        self._recorder.counts.deleted += 1
        self._recorder.event("info", "deleted")

    def _too_large(self, item: RemoteItem) -> None:
        """Wiersz 5: plik ponad limit — ``warn``, dokument i mapowanie bez zmian."""
        self._recorder.counts.skipped += 1
        self._recorder.event(
            "warn",
            f"file too large ({item.size} B > {self._integration.max_file_size_bytes} B)",
            file_path=item.path,
        )

    async def _rename(self, item: RemoteItem, mapping: MappingRow) -> None:
        """Wiersz 7: nowa nazwa bez re-parsowania; zmiana rozszerzenia leci do wiersza 9."""
        try:
            await self._container.ingest.rename_document(
                cast("str", mapping.document_id),
                item.name,
                wd_source=wd_source(self._integration, item),
            )
        except ValidationFailed:
            await self._reupload(item, mapping)
            return
        await self._write_mapping(self._mapping_of(item, mapping.document_id, item.content_tag))
        self._recorder.counts.renamed += 1
        self._recorder.event("info", "renamed")

    async def _reupload(self, item: RemoteItem, mapping: MappingRow | None) -> None:
        """Wiersz 9: pobranie do pliku tymczasowego i ``upload`` (nowy) albo ``replace``.

        ``replace`` zachowuje ``document_id`` poprzedniego dokumentu (09 §6).
        """
        from app.services.ingest import UploadSource  # noqa: PLC0415 — import leniwy (app.parsing)

        tmp_path = self._tmp_path()
        tmp_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            await self._connector.download(
                self._cfg, item, tmp_path, max_bytes=self._integration.max_file_size_bytes
            )
            source = UploadSource(stream=read_blocks(tmp_path), filename=item.name)
            document, created = await self._store(item, source, mapping)
            await self._container.ingest.set_source_meta(
                document.id, wd_source(self._integration, item)
            )
            await self._write_mapping(self._mapping_of(item, document.id, item.content_tag))
        finally:
            tmp_path.unlink(missing_ok=True)
        if created:
            self._recorder.counts.added += 1
            self._recorder.event("info", "added")
        else:
            self._recorder.counts.updated += 1
            self._recorder.event("info", "updated")

    async def _store(
        self, item: RemoteItem, source: UploadSource, mapping: MappingRow | None
    ) -> tuple[DocumentRow, bool]:
        """Zapis treści wiersza 9: ``upload`` nowego dokumentu albo ``replace`` istniejącego.

        Zwraca dokument i informację, czy powstał nowy (``True``) — od tego zależy licznik.
        """
        if mapping is None or mapping.document_id is None:
            document = await self._container.ingest.upload(
                self._integration.dataset_id,
                source,
                created_by=self._integration.owner_id,
                name=item.name,
                source_type=SOURCE_TYPE,
                source_ref=source_ref(self._integration.id, item),
                parse=True,
            )
            return document, True
        replaced = await self._container.ingest.replace(
            mapping.document_id, source, name=item.name, parse=True
        )
        return replaced, False

    async def _record_failure(
        self, item: RemoteItem, mapping: MappingRow | None, exc: Exception
    ) -> None:
        """Wiersz 10: mapping ``failed``, ``error`` z ``file_path`` i kontynuacja przebiegu."""
        self._recorder.counts.failed += 1
        self._recorder.event("error", f"item failed: {exc}", file_path=item.path)
        error = str(exc)[:ERROR_LIMIT]
        if mapping is None:
            await self._write_mapping(
                self._mapping_of(item, None, None, last_status=MAPPING_FAILED, last_error=error)
            )
            return
        await self._write_mapping(
            replace(
                mapping, last_status=MAPPING_FAILED, last_error=error, updated_at=self._now_ms()
            )
        )

    def _mapping_of(
        self,
        item: RemoteItem,
        document_id: str | None,
        content_tag: str | None,
        *,
        last_status: str = MAPPING_OK,
        last_error: str | None = None,
    ) -> MappingRow:
        """Wiersz mapowania z pól elementu (kontrakt C1)."""
        return MappingRow(
            integration_id=self._integration.id,
            container_id=item.container_id,
            item_id=item.item_id,
            document_id=document_id,
            content_tag=content_tag,
            meta_tag=item.meta_tag,
            name=item.name,
            path=item.path,
            web_url=item.web_url,
            last_status=last_status,
            last_error=last_error,
            updated_at=self._now_ms(),
        )

    async def _get_mapping(self, item: RemoteItem) -> MappingRow | None:
        """Mapowanie elementu z bazy (kontrakt C2)."""
        async with transaction(self._sessionmaker()) as session:
            return await repo.get_mapping(
                session, self._integration.id, item.container_id, item.item_id
            )

    async def _write_mapping(self, row: MappingRow) -> None:
        """Zapis mapowania w krótkiej transakcji (kontrakt C2)."""
        async with transaction(self._sessionmaker()) as session:
            await repo.upsert_mapping(session, row)

    async def _delete_mapping(self, item: RemoteItem) -> None:
        """Usunięcie mapowania elementu (kontrakt C2)."""
        async with transaction(self._sessionmaker()) as session:
            await repo.delete_mapping(
                session, self._integration.id, item.container_id, item.item_id
            )

    def _tmp_path(self) -> Path:
        """Ścieżka pliku tymczasowego: ``<storage_root>/tmp/<uuid4 hex>`` (kontrakt C5)."""
        return Path(self._container.settings.storage_root) / "tmp" / uuid.uuid4().hex

    def _now_ms(self) -> int:
        """Czas z zegara kontenera (kontrakt C5)."""
        return self._container.clock.now_ms()

    def _sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        """Fabryka sesji z kontenera (wzorzec ``RunRecorder._sessionmaker``)."""
        return cast("async_sessionmaker[AsyncSession]", self._container.sessionmaker)
