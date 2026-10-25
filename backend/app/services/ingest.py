"""Usługa ingestii dokumentów: upload, replace, zlecanie i anulowanie parsowania (C4, K5 §6.4).

Bez samego pipeline'u parsowania (``run_parse_task`` dojdzie w T8). Usługa nie sprawdza
uprawnień (polityka M3 — warstwa API); błędy tylko z K3/K5. ``Container`` jest importowany
wyłącznie pod ``TYPE_CHECKING`` — unika cyklu ``app.core.container`` ↔ ``app.services.ingest``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import xxhash
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import NotFound, OperationNotAllowed, ValidationFailed
from app.core.timeutil import from_ms
from app.db.repositories import datasets as datasets_repo
from app.db.repositories import documents as documents_repo
from app.db.repositories import documents_query, task_lookup
from app.db.repositories import tasks as tasks_repo
from app.db.repositories.documents import DocumentRow  # re-eksport (C4)
from app.db.uow import transaction
from app.parsing.registry import EXTENSION_ALIASES
from app.storage.keys import StorageKey, document_key, document_prefix, is_filemanager_key
from app.worker.queue import DbTaskQueue

if TYPE_CHECKING:
    from concurrent.futures import Executor

    from app.core.container import Container
    from app.worker.context import TaskContext
    from app.worker.queue import TaskRow


def document_parser_config(kb_config: dict[str, Any]) -> dict[str, Any]:
    """``parser_config`` dokumentu z konfiguracji datasetu — bez ``graphrag``/``raptor``.

    Upstream nie przenosi ``graphrag``/``raptor`` datasetu na dokument (złoto ``metadata_e6--58``:
    dokument w ``GET …/documents`` nie ma tych kluczy); jawne ustawienie ich aktualizacją
    dokumentu (``PATCH``/``PUT``) zostaje nietknięte.
    """
    return {key: value for key, value in kb_config.items() if key not in ("graphrag", "raptor")}


@dataclass(frozen=True)
class UploadSource:
    """Strumień pliku do zapisu; rozmiar nieznany z góry (K5 §6.4)."""

    stream: AsyncIterator[bytes]
    filename: str  # nazwa od użytkownika (tylko do documents.name/suffix; nigdy do ścieżki)


IMAGE_SUFFIXES = frozenset({"png", "jpg", "jpeg", "webp", "tif", "tiff", "bmp"})

# Kody ``run`` trasy /documents/ingest (upstream TaskStatus: RUNNING '1', CANCEL '2').
RUN_CANCEL = "2"


def document_type(suffix: str) -> str:
    """Typ dokumentu wg rozszerzenia: pdf → "pdf", obrazy → "visual", pozostałe → "doc" (C4)."""
    if suffix == "pdf":
        return "pdf"
    if suffix in IMAGE_SUFFIXES:
        return "visual"
    return "doc"


def file_suffix(filename: str) -> str:
    """Rozszerzenie nazwy małymi literami; nieobsługiwane → ValidationFailed (C4)."""
    suffix = Path(filename).suffix.lower().lstrip(".")
    if suffix not in EXTENSION_ALIASES:
        raise ValidationFailed(f"file type not supported: {filename}")
    return suffix


def parse_digest(doc: DocumentRow, embedding_model: str) -> str:
    """Odcisk konfiguracji parsowania (05 §5.4).

    xxh128(json(chunking_config) + content_hash + json(pages) + embedding_model).
    """
    return xxhash.xxh128_hexdigest(
        (
            json.dumps(
                {"chunk_method": doc.chunk_method, "parser_config": doc.parser_config},
                sort_keys=True,
                ensure_ascii=False,
            )
            + doc.content_hash
            + json.dumps(doc.parser_config.get("pages", [[1, 1000000]]))
            + embedding_model
        ).encode()
    )


class DocumentIngestService:
    """Zarządza plikami dokumentów i zleceniami parsowania (C4).

    Konstruktor bez I/O — ``sessionmaker`` brany leniwie, w chwili wywołania metody
    (``Container.ingest`` może powstać przed ``start()``).
    """

    def __init__(self, container: Container) -> None:
        self._container = container

    def _sm(self) -> async_sessionmaker[AsyncSession]:
        """Fabryka sesji z kontenera; brak (kontener nie wystartował) → RuntimeError (C4)."""
        sessionmaker = self._container.sessionmaker
        if sessionmaker is None:
            raise RuntimeError("container not started")
        return sessionmaker

    async def upload(  # noqa: PLR0913 — kształt kontraktu C4
        self,
        dataset_id: str,
        source: UploadSource,
        *,
        created_by: str,
        name: str | None = None,
        source_type: str = "local",
        source_ref: str | None = None,
        parse: bool = False,
    ) -> DocumentRow:
        """Zapisuje plik, wstawia dokument i przelicza licznik datasetu; parse → zadanie (C4)."""
        name = name or source.filename
        suffix = file_suffix(name)  # błąd przed jakimkolwiek zapisem (C4)
        async with transaction(self._sm()) as session:
            dataset = await datasets_repo.get(session, dataset_id)
        if dataset is None:
            raise NotFound(f"dataset not found: {dataset_id}")
        document_id = self._container.id_gen.new_id()
        key = document_key(dataset_id, document_id, suffix)
        # Limit z settings; przekroczenie → ValidationFailed ze storage (plik częściowy
        # usuwa sam storage z tmp/) — przepuszczamy bez zmian, dokument nie powstaje.
        stored = await self._container.storage.put(
            key,
            source.stream,
            max_bytes=self._container.settings.max_upload_mb * 1024 * 1024,
        )
        now = self._container.clock.now_ms()
        async with transaction(self._sm()) as session:
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
                    size=stored.size,
                    location=stored.key,
                    content_hash=stored.content_hash,
                    source_type=source_type,
                    source_ref=source_ref,
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
        if parse:
            await self.enqueue_parse([document_id])
        return await self._get(document_id)

    async def link_existing(
        self,
        dataset_id: str,
        *,
        name: str,
        location: str,
        size: int,
        created_by: str,
    ) -> DocumentRow:
        """Dokument datasetu na istniejącym klobie pliku, bez kopii bloba (K16 §D1.7, §D4).

        Ciało w ``services/ingest_link.py`` (limit 400 linii — DEC-041); import leniwy, żeby
        nie tworzyć cyklu (``ingest_link`` importuje stąd ``document_type``/``file_suffix``).
        """
        from app.services.ingest_link import link_existing  # noqa: PLC0415 — cykl modułów

        return await link_existing(
            self._container,
            dataset_id,
            name=name,
            location=location,
            size=size,
            created_by=created_by,
        )

    async def replace(
        self,
        document_id: str,
        source: UploadSource,
        *,
        name: str | None = None,
        parse: bool = True,
    ) -> DocumentRow:
        """Podmienia plik pod tym samym document_id; zmiana treści i parse → re-parse (C4)."""
        doc = await self._get(document_id)
        new_name = name or source.filename
        suffix = file_suffix(new_name)
        if parse:
            async with transaction(self._sm()) as session:
                await self._reject_active(session, [document_id])
        key = document_key(doc.dataset_id, document_id, suffix)
        stored = await self._container.storage.put(
            key,
            source.stream,
            max_bytes=self._container.settings.max_upload_mb * 1024 * 1024,
        )
        # Inny klucz → stary plik usunięty po zapisie, ale blob `filemanager/…` należy do
        # wiersza `files`, nie do dokumentu — zostaje (K16 §1 p. 5, CONTRACT E4-5a §D1.6).
        if key != doc.location and not is_filemanager_key(doc.location):
            await self._container.storage.delete(StorageKey(doc.location))
        now = self._container.clock.now_ms()
        async with transaction(self._sm()) as session:
            await documents_repo.update_file(
                session,
                document_id,
                name=new_name,
                suffix=suffix,
                type=document_type(suffix),
                size=stored.size,
                location=key,
                content_hash=stored.content_hash,
                now_ms=now,
            )
        if parse and stored.content_hash != doc.content_hash:
            await self.enqueue_parse([document_id], clear_existing=True)
        return await self._get(document_id)

    async def rename_document(
        self,
        document_id: str,
        name: str,
        *,
        wd_source: dict[str, object] | None = None,
    ) -> DocumentRow:
        """Zmienia nazwę dokumentu (i ``wd_source``) bez pliku, chunków, ``run`` i zadania (K12 §4).

        Zmiana rozszerzenia (walidacja przed jakimkolwiek zapisem) → ValidationFailed;
        brak dokumentu → NotFound. Zwraca świeży wiersz.
        """
        doc = await self._get(document_id)
        suffix = file_suffix(name)  # błąd przed jakimkolwiek zapisem (C4)
        if suffix != doc.suffix:
            raise ValidationFailed(f"cannot change file type: {doc.suffix} -> {suffix}")
        fields: dict[str, object] = {"name": name}
        if wd_source is not None:
            fields["meta_fields"] = {**doc.meta_fields, "wd_source": wd_source}
        now = self._container.clock.now_ms()
        async with transaction(self._sm()) as session:
            await documents_query.update_meta(session, document_id, fields, now_ms=now)
        return await self._get(document_id)

    async def set_source_meta(self, document_id: str, wd_source: dict[str, object]) -> None:
        """Ustawia ``meta_fields["wd_source"]``; resztę bez zmian, update_time też (K12 §4)."""
        doc = await self._get(document_id)
        meta_fields = {**doc.meta_fields, "wd_source": wd_source}
        async with transaction(self._sm()) as session:
            await documents_repo.set_meta_fields(session, document_id, meta_fields=meta_fields)

    async def enqueue_parse(
        self,
        document_ids: Sequence[str],
        *,
        clear_existing: bool = False,
        priority: int = 0,
    ) -> list[str]:
        """Wstawia zadania parse_document (jedna transakcja) i ustawia run='1' (C4)."""
        if not document_ids:
            return []
        now = self._container.clock.now_ms()
        async with transaction(self._sm()) as session:
            docs = await documents_repo.get_many(session, document_ids)
            by_id = {doc.id: doc for doc in docs}
            missing = next((doc_id for doc_id in document_ids if doc_id not in by_id), None)
            if missing is not None:
                raise NotFound(f"document not found: {missing}")
            await self._reject_active(session, document_ids)
            public_ids: list[str] = []
            for document_id in document_ids:
                doc = by_id[document_id]
                dataset = await datasets_repo.get(session, doc.dataset_id)
                if dataset is None:  # FK documents→datasets; nieosiągalne, mypy wymaga sprawdzenia
                    raise NotFound(f"dataset not found: {doc.dataset_id}")
                public_id = self._container.id_gen.new_id()
                await tasks_repo.insert(
                    session,
                    public_id=public_id,
                    task_type="parse_document",
                    payload_json=json.dumps({"clear_existing": clear_existing}),
                    document_id=doc.id,
                    dataset_id=doc.dataset_id,
                    priority=priority,
                    max_attempts=3,
                    digest=parse_digest(doc, dataset.embedding_model),
                    next_attempt_at=now,
                    now_ms=now,
                )
                public_ids.append(public_id)
            await documents_repo.start_parse(session, document_ids, now_ms=now)
        return public_ids

    async def cancel(self, document_ids: Sequence[str]) -> int:
        """Żąda anulowania: queued → cancelled, running → cancel_requested (§6.3); liczba zadań."""
        queue = DbTaskQueue(self._sm(), self._container.clock, self._container.id_gen)
        return await queue.request_cancel(document_ids=document_ids)

    async def ingest_documents(
        self, document_ids: Sequence[str], *, run: str, delete: bool
    ) -> None:
        """Trasa ``POST /api/v1/documents/ingest`` (DOC:1461): start (run='1') albo cancel ('2').

        Upstream ``_run_sync`` (DOC:1477-1545): ``delete=true`` kasuje zadania dokumentu
        (DOC:1508) przed ponownym parsowaniem; ``clear_existing`` usuwa chunki w pipeline.
        Anulowanie nie zwraca błędu dla dokumentu, który już nie jest RUNNING — złoto --21
        (``expect: any``) ma ``data: true``, a wynik zależy od wyścigu z workera.
        """
        unique_ids = list(dict.fromkeys(document_ids))
        if not unique_ids:
            return
        if run == RUN_CANCEL:
            await self.cancel(unique_ids)
            return
        if delete:
            async with transaction(self._sm()) as session:
                await task_lookup.delete_by_documents(session, unique_ids)
        await self.enqueue_parse(unique_ids, clear_existing=delete)

    async def delete_documents(self, document_ids: Sequence[str]) -> int:
        """Anuluje zadania, usuwa dokumenty (kaskada FK) i pliki; przelicza liczniki (C4)."""
        async with transaction(self._sm()) as session:
            docs = await documents_repo.get_many(session, document_ids)
        by_id = {doc.id: doc for doc in docs}
        missing = next((doc_id for doc_id in document_ids if doc_id not in by_id), None)
        if missing is not None:
            raise NotFound(f"document not found: {missing}")
        await self.cancel(document_ids)
        now = self._container.clock.now_ms()
        dataset_ids = sorted({doc.dataset_id for doc in docs})
        async with transaction(self._sm()) as session:
            # Blokady datasetów przed usunięciem (kolejność blokad; deadlock 1213 — DEC-088 p. 3).
            for dataset_id in dataset_ids:
                await datasets_repo.lock(session, dataset_id)
            deleted = await documents_repo.delete_many(session, list(document_ids))
            for dataset_id in dataset_ids:
                await datasets_repo.recount(session, dataset_id, now_ms=now)
        for doc in docs:
            await self._container.storage.delete_prefix(document_prefix(doc.dataset_id, doc.id))
        return deleted

    async def run_parse_task(
        self, task: TaskRow, ctx: TaskContext, *, executor: Executor | None = None
    ) -> None:
        """Obsługuje zadanie ``parse_document`` — deleguje do pipeline'u (kontrakt C4/C8).

        Import leniwy wewnątrz metody: moduł pipeline'u ciągnie ciężkie ``app.parsing``,
        a worker (``app.worker.main``) nie może go ładować przy starcie (brief T8).
        """
        from app.services.ingest_pipeline import run_parse  # noqa: PLC0415 — import leniwy (T8)

        await run_parse(self._container, task, ctx, executor=executor)

    async def _get(self, document_id: str) -> DocumentRow:
        """Świeży wiersz dokumentu; brak → NotFound (C4: brak dokumentu przed operacją)."""
        async with transaction(self._sm()) as session:
            row = await documents_repo.get(session, document_id)
        if row is None:
            raise NotFound(f"document not found: {document_id}")
        return row

    @staticmethod
    async def _reject_active(session: AsyncSession, document_ids: Sequence[str]) -> None:
        """OperationNotAllowed, gdy któryś dokument ma zadanie queued/running (C4)."""
        active = await task_lookup.active_parse_documents(session, document_ids)
        if active:
            raise OperationNotAllowed("Can't parse document that is currently being processed")
