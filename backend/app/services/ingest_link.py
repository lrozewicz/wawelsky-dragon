"""Wstawienie dokumentu na istniejącym klobie pliku — ciało ``IngestService.link_existing``.

CONTRACT E4-5a §D4. Wydzielone z ``services/ingest.py`` (limit 400 linii, DEC-041): ``ingest``
importuje ten moduł leniwie, więc zależność idzie ``services/ingest`` → ``services/ingest_link``.
Moduł nie dotyka ``services/files*`` — kontener wstrzykuje wywołujący.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import xxhash
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import NotFound
from app.core.timeutil import from_ms
from app.db.repositories import datasets as datasets_repo
from app.db.repositories import documents as documents_repo
from app.db.repositories.documents import DocumentRow
from app.db.uow import transaction
from app.services.ingest import document_parser_config, document_type, file_suffix
from app.storage.keys import StorageKey

if TYPE_CHECKING:
    from app.core.container import Container

__all__ = ["link_existing"]


def _sessionmaker(container: Container) -> async_sessionmaker[AsyncSession]:
    """Fabryka sesji z kontenera; brak (kontener nie wystartował) → RuntimeError (C4)."""
    sessionmaker = container.sessionmaker
    if sessionmaker is None:
        raise RuntimeError("container not started")
    return sessionmaker


async def _get(sessionmaker: async_sessionmaker[AsyncSession], document_id: str) -> DocumentRow:
    """Świeży wiersz dokumentu; brak → NotFound (C4: brak dokumentu przed operacją)."""
    async with transaction(sessionmaker) as session:
        row = await documents_repo.get(session, document_id)
    if row is None:
        raise NotFound(f"document not found: {document_id}")
    return row


async def link_existing(  # noqa: PLR0913 — kształt kontraktu §D4 (kontener + 5 pól)
    container: Container,
    dataset_id: str,
    *,
    name: str,
    location: str,
    size: int,
    created_by: str,
) -> DocumentRow:
    """Wstawia dokument na istniejącym kluczu bloba — bez ``storage.put`` (K16 / §D4).

    Wypełnienie wiersza jak ``upload`` (``chunk_method``/``parser_config`` z datasetu,
    blokada datasetu, ``recount``), ale ``location`` jest podane, ``content_hash`` liczymy
    ze strumienia istniejącego bloba (xxh128 jak ``storage.put``), a parsowania nie
    zlecamy — ``run='0'``. Brak bloba → ``NotFound`` (ze ``storage.open``).

    Wstawianie celowo zduplikowane z ``upload`` (brief T4 p. 3: refaktor wspólnego fragmentu
    zmieniłby ``upload`` o więcej niż 10 linii).
    """
    suffix = file_suffix(name)
    sessionmaker = _sessionmaker(container)
    async with transaction(sessionmaker) as session:
        dataset = await datasets_repo.get(session, dataset_id)
    if dataset is None:
        raise NotFound(f"dataset not found: {dataset_id}")
    digest = xxhash.xxh128()
    async for chunk in container.storage.open(StorageKey(location)):
        digest.update(chunk)
    document_id = container.id_gen.new_id()
    now = container.clock.now_ms()
    async with transaction(sessionmaker) as session:
        # Blokada datasetu przed zapisem (kolejność blokad; deadlock 1213 — DEC-088 p. 3).
        await datasets_repo.lock(session, dataset_id)
        await documents_repo.insert(
            session,
            DocumentRow(
                id=document_id,
                dataset_id=dataset_id,
                created_by=created_by,
                name=name,
                suffix=suffix,
                type=document_type(suffix),
                size=size,
                location=location,
                content_hash=digest.hexdigest(),
                source_type="local",
                source_ref=None,
                chunk_method=dataset.chunk_method,
                parser_config=document_parser_config(dataset.parser_config),
                run="0",
                progress=0.0,
                progress_msg="",
                error=None,
                process_begin_at=None,
                process_duration=0.0,
                chunk_count=0,
                token_count=0,
                enabled=True,
                meta_fields={},
                thumbnail=None,
                create_time=now,
                create_date=from_ms(now),
                update_time=now,
                update_date=from_ms(now),
            ),
        )
        await datasets_repo.recount(session, dataset_id, now_ms=now)
    return await _get(sessionmaker, document_id)
