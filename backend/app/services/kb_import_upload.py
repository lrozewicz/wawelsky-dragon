"""Przyjęcie porcji uploadu paczki ``.wdkb.zip`` (K19 §3 trasa 7, CONTRACT E7-1z §6).

Wydzielone z ``kb_import.KbImportService`` (plik ``kb_import.py`` < 400 linii): logika trasy 7
biegnie w **dwóch transakcjach** rozdzielonych walidacją paczki:

1. *Transakcja zapisu porcji* — ``SELECT … FOR UPDATE`` wiersza sesji, sprawdzenia (stan, offset,
   rozmiar porcji), dopisanie bajtów do pliku i ``add_received``; commit zwalnia blokadę **przed**
   walidacją.
2. *Walidacja paczki* (tylko porcja kończąca, ``received + written == size_bytes``) — poza
   transakcją i bez blokady wiersza (archiwum do 2 GB, K19 §5), więc równoległy ``get``/
   ``SELECT … FOR UPDATE`` na tym samym wierszu nie czeka na walidację.
3. *Transakcja domknięcia* — warunkowe ``UPDATE`` z ``state='uploading'`` i pełnym
   ``received_bytes`` (``imports_repo.set_final_state``); rowcount 0 ⇒ ``ImportNotReady`` (409).

Równoległy duplikat ostatniej porcji: druga porcja wchodzi po commicie pierwszej (transakcja 1)
i widzi już ``received_bytes == size_bytes``, więc jej ``start != received_bytes`` ⇒ 409
``offset_mismatch``; gdy domknięcie zmieniło stan — 409 ``import_not_ready``.

Warstwy (import-linter): moduł NIE importuje ``app.api`` — zwraca ``dict`` o kształcie
``DatasetImport``. Helpery wiersza (``locked_row``/``ensure_visible``/``required``/
``dataset_import``) i ``unlink`` są tu współdzielone z ``KbImportService``.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import (
    ImportNotReady,
    NotFound,
    OffsetMismatch,
    PackageTooLarge,
    ValidationFailed,
)
from app.db.repositories import dataset_imports as imports_repo
from app.db.uow import transaction
from app.domain.policy import Action, Principal, ResourceRef, can
from app.services.kb_import_summary import build_summary
from app.services.kb_package.validate import ValidatedPackage, validate_package

if TYPE_CHECKING:
    from app.core.container import Container

__all__ = [
    "IMPORTS_DIR",
    "IMPORT_SUFFIX",
    "NOT_FOUND_MESSAGE",
    "TTL_MS",
    "UPLOAD_CHUNK_SIZE",
    "dataset_import",
    "ensure_visible",
    "locked_row",
    "required",
    "unlink",
    "upload_chunk",
]

# Maksymalny rozmiar porcji uploadu (K19 §3, trasa 7) — DOSŁOWNIE ``kb_schemas.IMPORT_CHUNK_SIZE``.
# Usługa nie może zaimportować ``app.api`` (kontrakt warstw), więc wartość jest tu powtórzona,
# a zgodność pilnuje test ``test_upload_chunk_size_matches_the_wire_constant``.
UPLOAD_CHUNK_SIZE = 8_388_608

IMPORTS_DIR = "imports"  # jak ``app.worker.kb_cleanup.IMPORTS_DIR``
IMPORT_SUFFIX = ".wdkb.zip"
TTL_MS = 24 * 60 * 60 * 1000  # sesja (i każda porcja) żyje dobę (K19 §4)
NOT_FOUND_MESSAGE = "Import session not found"

# ``Content-Range: bytes <start>-<end>/<total>`` (RFC 7233); tylko forma bajtowa i liczby.
_CONTENT_RANGE_RE = re.compile(r"bytes (\d+)-(\d+)/(\d+)")

# Blokada wiersza sesji na czas zapisu porcji — serializacja porcji o tym samym ``start`` (DEC-327).
_LOCK_ROW_SQL = text(
    "SELECT id FROM dataset_imports WHERE id = CAST(:import_id AS BINARY) FOR UPDATE"
)


def _sessionmaker(container: Container) -> async_sessionmaker[AsyncSession]:
    """Fabryka sesji z kontenera; brak (kontener nie wystartował) → RuntimeError (C4)."""
    sessionmaker = container.sessionmaker
    if sessionmaker is None:
        raise RuntimeError("container not started")
    return sessionmaker


def ensure_visible(principal: Principal, row: dict[str, Any] | None) -> None:
    """Inicjator sesji albo superuser; brak wiersza i brak dostępu to to samo **404** (K19).

    Polityka nie zna rodzaju ``dataset_import``; ``dataset`` z właścicielem = ``user_id`` sesji
    daje w tabeli 07 §7.1 dokładnie „właściciel albo superuser” — obcy dostaje ``not_found``,
    nie zdradzamy istnienia cudzej sesji.
    """
    if row is None:
        raise NotFound(NOT_FOUND_MESSAGE)
    ref = ResourceRef(kind="dataset", owner_id=str(row["user_id"]))
    if not can(principal, Action.READ, ref):
        raise NotFound(NOT_FOUND_MESSAGE)


def required(row: dict[str, Any] | None) -> dict[str, Any]:
    """Wiersz po ``ensure_visible``/``locked_row``; ``None`` oznacza brak sesji → **404**."""
    if row is None:
        raise NotFound(NOT_FOUND_MESSAGE)
    return row


async def locked_row(session: AsyncSession, import_id: str) -> dict[str, Any] | None:
    """Wiersz sesji zablokowany ``FOR UPDATE`` (albo ``None``, gdy brak).

    Blokada trzyma się do końca transakcji zapisu porcji, więc druga równoległa porcja tej samej
    sesji czeka i widzi już zaktualizowane ``received_bytes`` (DEC-327). Zwolniona jest **przed**
    walidacją paczki (CONTRACT E7-1z §6).
    """
    locked = (await session.execute(_LOCK_ROW_SQL, {"import_id": import_id})).first()
    if locked is None:
        return None
    return await imports_repo.get(session, import_id)


def dataset_import(row: dict[str, Any]) -> dict[str, Any]:
    """Wiersz ``dataset_imports`` → ``dict`` o kształcie ``DatasetImport`` (K19 §3)."""
    return {
        "import_id": str(row["id"]),
        "file_name": row["file_name"],
        "size_bytes": int(row["size_bytes"]),
        "received_bytes": int(row["received_bytes"]),
        "chunk_size": UPLOAD_CHUNK_SIZE,
        "state": row["state"],
        "errors": row["errors"],
        "summary": row["summary"],
        "task_id": row["task_id"],
        "expires_at": int(row["expires_at"]),
    }


def parse_content_range(value: str | None, size_bytes: int) -> tuple[int, int]:
    """``(start, end)`` z nagłówka; brak/zły kształt/``total`` ≠ rozmiar/odwrotny zakres → 400.

    ``end >= size_bytes`` to zakres poza plikiem — nagłówek niepoprawny (RFC 7233: ostatni bajt
    jest mniejszy niż rozmiar całości), więc odrzucamy go tak samo jak ``end < start``.
    """
    if value is None:
        raise ValidationFailed("Brak nagłówka Content-Range")
    match = _CONTENT_RANGE_RE.fullmatch(value.strip())
    if match is None:
        raise ValidationFailed("Niepoprawny nagłówek Content-Range")
    start, end, total = (int(part) for part in match.groups())
    if total != size_bytes or end < start or end >= size_bytes:
        raise ValidationFailed("Nagłówek Content-Range niezgodny z rozmiarem paczki")
    return start, end


async def _copy_body(fp: BinaryIO, body: AsyncIterator[bytes], expected: int) -> int:
    """Przepisuje ciało porcji do pliku, licząc bajty w locie; zwraca liczbę zapisanych.

    Strumień dłuższy albo krótszy niż deklarowany zakres → 400 (K19 §3, CONTRACT §4).
    """
    written = 0
    async for chunk in body:
        if not chunk:
            continue
        written += len(chunk)
        if written > expected:
            raise ValidationFailed("Ciało żądania dłuższe niż deklarowany zakres")
        await asyncio.to_thread(fp.write, chunk)
    if written != expected:
        raise ValidationFailed("Ciało żądania krótsze niż deklarowany zakres")
    return written


async def write_chunk(path: Path, body: AsyncIterator[bytes], *, start: int, expected: int) -> int:
    """Dopisuje porcję na offsecie ``start``; przy błędzie obcina plik z powrotem do ``start``.

    Obcięcie usuwa ślad po przerwanej porcji (CONTRACT §4): ``received_bytes`` w bazie zostaje
    na ``start``, więc kolejna próba dopisze dokładnie od tego miejsca. Otwarcie i zamknięcie
    pliku to I/O blokujące — schodzi do wątku (ASYNC240), tak jak samo pisanie porcji.
    """
    fp = await asyncio.to_thread(_open_at, path, start)
    with fp:
        try:
            return await _copy_body(fp, body, expected)
        except ValidationFailed:
            await asyncio.to_thread(_rewind, fp, start)
            raise


def _open_at(path: Path, start: int) -> BinaryIO:
    """Otwiera plik paczki na offsecie ``start`` i obcina wszystko za nim (sync, w wątku)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fp: BinaryIO
    try:
        fp = path.open("r+b")
    except FileNotFoundError:
        fp = path.open("wb")
    fp.seek(start)
    fp.truncate()
    return fp


def _rewind(fp: BinaryIO, start: int) -> None:
    """Obcina plik z powrotem do ``start`` po nieudanej porcji (sync, w wątku)."""
    fp.seek(start)
    fp.truncate()


def unlink(path: Path) -> None:
    """Usuwa plik paczki; brak pliku to nie błąd (sync, w wątku — ASYNC240)."""
    path.unlink(missing_ok=True)


async def finalize_upload(
    container: Container, *, path: Path, row: dict[str, Any], now_ms: int
) -> dict[str, Any]:
    """Porcja kończąca: walidacja paczki → gotowe podsumowanie → warunkowe domknięcie sesji.

    Walidacja jest CPU (archiwum do 2 GB, K19 §5) — schodzi do wątku i biegnie **bez** blokady
    wiersza (transakcja zapisu porcji jest już zamknięta). Domknięcie (transakcja 2) przestawia
    stan warunkowo (``set_final_state``); rowcount 0 ⇒ ``ImportNotReady`` (409). Zwraca świeży
    wiersz sesji (``ready``/``invalid``). Odpowiedź w obu przypadkach to 200 (K19 §3) —
    ``invalid`` to nie błąd HTTP.
    """
    settings = container.settings
    outcome = await asyncio.to_thread(
        validate_package,
        path,
        max_bytes=settings.export_max_bytes,
        max_ratio=settings.max_archive_ratio,
    )
    import_id = str(row["id"])
    if isinstance(outcome, ValidatedPackage):
        state = "ready"
        errors: list[dict[str, Any]] = []
        summary = await build_summary(container, actor_id=str(row["user_id"]), pkg=outcome)
    else:
        state = "invalid"
        errors = [{"code": error.code, "message": error.message} for error in outcome]
        summary = None
    async with transaction(_sessionmaker(container)) as session:
        applied = await imports_repo.set_final_state(
            session,
            import_id=import_id,
            state=state,
            errors=errors,
            summary=summary,
            now_ms=now_ms,
        )
        if not applied:
            current = await imports_repo.get(session, import_id)
            details: dict[str, object] = (
                {"state": str(current["state"])} if current is not None else {}
            )
            raise ImportNotReady("Sesja nie przyjmuje porcji", details=details)
        updated = await imports_repo.get(session, import_id)
    if state == "invalid":
        await asyncio.to_thread(unlink, path)
    return required(updated)


async def upload_chunk(  # noqa: PLR0913 — kontekst trasy 7: kontener, plik, aktor, sesja, zakres, ciało
    container: Container,
    path: Path,
    principal: Principal,
    import_id: str,
    *,
    content_range: str | None,
    body: AsyncIterator[bytes],
) -> dict[str, Any]:
    """Przyjmuje porcję (trasa 7), a po porcji kończącej waliduje paczkę poza blokadą wiersza.

    Kolejność rozstrzygnięć: autoryzacja (404) → nagłówek (400) → stan (409) → offset (409)
    → rozmiar porcji (413) → dopiero potem czytanie ciała (K19 §3, CONTRACT §4). Transakcja
    zapisu obejmuje wyłącznie sprawdzenia, dopisanie porcji i ``add_received`` — walidacja
    i domknięcie stanu dzieją się po commicie (CONTRACT E7-1z §6).
    """
    now = container.clock.now_ms()
    async with transaction(_sessionmaker(container)) as session:
        row = await locked_row(session, import_id)
        ensure_visible(principal, row)
        row = required(row)
        size_bytes = int(row["size_bytes"])
        start, end = parse_content_range(content_range, size_bytes)
        state = str(row["state"])
        if state != "uploading":
            raise ImportNotReady("Sesja nie przyjmuje porcji", details={"state": state})
        received = int(row["received_bytes"])
        if start != received:
            raise OffsetMismatch(
                "Porcja nie zaczyna się na odebranym offsecie",
                details={"received_bytes": received},
            )
        expected = end - start + 1
        if expected > UPLOAD_CHUNK_SIZE:
            raise PackageTooLarge("Porcja przekracza maksymalny rozmiar")
        written = await write_chunk(path, body, start=start, expected=expected)
        await imports_repo.add_received(
            session,
            import_id=import_id,
            received_bytes=written,
            expires_at=now + TTL_MS,
            now_ms=now,
        )
        completes = received + written == size_bytes
    if completes:
        return dataset_import(
            await finalize_upload(container, path=path, row=row, now_ms=container.clock.now_ms())
        )
    async with transaction(_sessionmaker(container)) as session:
        updated = await imports_repo.get(session, import_id)
    return dataset_import(required(updated))
