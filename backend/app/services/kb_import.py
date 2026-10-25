"""Sesja importu paczki ``.wdkb.zip``: ``KbImportService`` (K19 §3 trasy 6-10).

Kontrakt: CONTRACT E7-1b §2/§4 (+ E7-1z §6 dla uploadu). Usługa prowadzi sesję uploadu porcjami:
zakłada wiersz ``dataset_imports``, przyjmuje porcje ``PUT .../content`` (``Content-Range``,
dopisywanie do ``<storage_root>/imports/<id>.wdkb.zip``), a po porcji kończącej uruchamia
walidację paczki (E7-1f) i — gdy paczka jest poprawna — podsumowanie importu
(``build_summary``). Logika trasy 7 (dwie transakcje rozdzielone walidacją) żyje w
``kb_import_upload``; tutaj zostaje `create`/`get`/`delete`/`start` i delegacja `upload`.

Warstwy (import-linter): moduł NIE importuje ``app.api`` — zwraca ``dict`` o kształcie
``DatasetImport``, a walidację schematem robi trasa. Wyjątki pochodzą z ``app.core.errors``.
Helpery wiersza sesji współdzieli z ``kb_import_upload``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import ImportNotReady, PackageTooLarge, ValidationFailed
from app.db.repositories import dataset_imports as imports_repo
from app.db.uow import transaction
from app.domain.policy import Principal
from app.services.kb_import_start import start_import
from app.services.kb_import_upload import (
    IMPORT_SUFFIX,
    IMPORTS_DIR,
    TTL_MS,
    UPLOAD_CHUNK_SIZE,  # noqa: F401 — re-eksport (test zgodności z ``kb_schemas``)
    dataset_import,
    ensure_visible,
    locked_row,
    required,
    unlink,
    upload_chunk,
)
from app.worker.queue import DbTaskQueue

if TYPE_CHECKING:
    from app.core.container import Container

__all__ = ["KbImportService"]

MAX_FILE_NAME_LEN = 255
# Statusy zadania, w których sesja ``started`` jeszcze pracuje (sprzątanie 24 h dokłada plik).
RUNNING_STATES = ("queued", "running")


def _sessionmaker(container: Container) -> async_sessionmaker[AsyncSession]:
    """Fabryka sesji z kontenera; brak (kontener nie wystartował) → RuntimeError (C4)."""
    sessionmaker = container.sessionmaker
    if sessionmaker is None:
        raise RuntimeError("container not started")
    return sessionmaker


def _queue(container: Container) -> DbTaskQueue:
    """Kolejka zadań na usługach kontenera — do sprawdzenia stanu zadania importu (trasa 10)."""
    return DbTaskQueue(_sessionmaker(container), container.clock, container.id_gen)


class KbImportService:
    """Sesja importu: założenie, upload porcjami, start, odczyt i kasowanie (K19 §3 trasy 6-10)."""

    def __init__(self, container: Container) -> None:
        self._container = container

    def _path(self, import_id: str) -> Path:
        """Ścieżka pliku paczki: ``<storage_root>/imports/<id>.wdkb.zip`` (CONTRACT §4)."""
        root = Path(self._container.settings.storage_root)
        return root / IMPORTS_DIR / f"{import_id}{IMPORT_SUFFIX}"

    async def create(
        self, principal: Principal, *, file_name: str, size_bytes: int
    ) -> dict[str, Any]:
        """Zakłada sesję uploadu (trasa 6): waliduje nazwę i rozmiar, zwraca stan ``uploading``."""
        if not 1 <= len(file_name) <= MAX_FILE_NAME_LEN:
            raise ValidationFailed("Nazwa pliku musi mieć od 1 do 255 znaków")
        if size_bytes <= 0:
            raise ValidationFailed("Rozmiar paczki musi być dodatni")
        if size_bytes > self._container.settings.export_max_bytes:
            raise PackageTooLarge("Paczka przekracza limit rozmiaru importu")
        now = self._container.clock.now_ms()
        import_id = self._container.id_gen.new_id()
        async with transaction(_sessionmaker(self._container)) as session:
            await imports_repo.insert(
                session,
                id=import_id,
                user_id=principal.user_id,
                file_name=file_name,
                size_bytes=size_bytes,
                expires_at=now + TTL_MS,
                now_ms=now,
            )
            row = await imports_repo.get(session, import_id)
        return dataset_import(required(row))

    async def get(self, principal: Principal, import_id: str) -> dict[str, Any]:
        """Stan sesji (trasa 8); wygasła sesja ma stan z bazy (``expired`` po sprzątaniu)."""
        async with transaction(_sessionmaker(self._container)) as session:
            row = await imports_repo.get(session, import_id)
        ensure_visible(principal, row)
        return dataset_import(required(row))

    async def delete(self, principal: Principal, import_id: str) -> None:
        """Usuwa sesję i plik paczki (trasa 10); sesja w trakcie zadania → 409.

        Wiersz czytamy z blokadą ``SELECT … FOR UPDATE`` (jak transakcja uploadu/startu):
        równoległe ``start`` i ``delete`` serializują się na wierszu, więc drugi widzi
        już ``started`` i dostaje 409 zamiast kasować sesję, której zadanie rusza. Nie usuwa
        datasetu utworzonego przez ``start`` — kasujemy wiersz sesji i plik (K19 §3, trasa 10).
        """
        async with transaction(_sessionmaker(self._container)) as session:
            row = await locked_row(session, import_id)
            ensure_visible(principal, row)
            row = required(row)
            if row["state"] == "started" and await self._task_running(row["task_id"]):
                raise ImportNotReady("Import jest w toku", details={"state": "started"})
            deleted = await imports_repo.delete(session, import_id)
        if deleted:
            await asyncio.to_thread(unlink, self._path(import_id))

    async def upload(
        self,
        principal: Principal,
        import_id: str,
        *,
        content_range: str | None,
        body: AsyncIterator[bytes],
    ) -> dict[str, Any]:
        """Przyjmuje porcję (trasa 7) — logika i podział transakcji w ``kb_import_upload``."""
        return await upload_chunk(
            self._container,
            self._path(import_id),
            principal,
            import_id,
            content_range=content_range,
            body=body,
        )

    async def start(
        self, principal: Principal, import_id: str, *, name: str, embedding_model: str | None
    ) -> dict[str, Any]:
        """Start importu (trasa 9) — logika w ``kb_import_start.start_import`` (K19 §3).

        Metoda otwiera transakcję z blokadą wiersza (``SELECT … FOR UPDATE``) obejmującą
        ``enqueue`` i ``set_state`` w delegacie, więc dwa równoległe ``start`` dają jedno 202,
        a drugi widzi ``started`` (409); wyjątek przewraca transakcję do ``ready`` (CONTRACT §3).
        """
        async with transaction(_sessionmaker(self._container)) as session:
            row = await locked_row(session, import_id)
            ensure_visible(principal, row)
            return await start_import(
                self._container,
                session,
                required(row),
                name=name,
                embedding_model=embedding_model,
            )

    async def _task_running(self, task_id: str | None) -> bool:
        """Czy zadanie importu tej sesji jest jeszcze ``queued``/``running`` (trasa 10)."""
        if not task_id:
            return False
        snapshot = await _queue(self._container).snapshot(task_id)
        return snapshot is not None and snapshot.status in RUNNING_STATES
