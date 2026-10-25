"""Handler zadania ``build_outline`` — profil spisu dla dokumentów sprzed v1.3 (K21 §2 p. 4).

Uzupełnia profil istniejących dokumentów (instalacje sprzed v1.3, import K19) **bez**
ponownego parsowania: czyta oryginał ze storage i wyznacza spis tymi samymi funkcjami,
co ``parse_document`` (``app.parsing.outline``). PDF → zakładki; PDF bez zakładek i inne
formaty → ponowna konwersja wyłącznie konwerterami bez modeli (bez OCR/wizji) → nagłówki
bloków (K21 §2 p. 2b); gdyby konwersja wymagała modelu (strony ``pending``) albo się
nie udała → ``none``. Zapis profilu to ``upsert`` po ``document_id``, a do ``progress_msg``
dokumentu dopisujemy tylko linię logu (``run``/``progress`` bez zmian). Dokument usunięty
w międzyczasie kończy zadanie bez błędu, a profil znika kaskadowo (FK). Kolejkowanie —
``app.worker.outline_sweep``.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import document_profiles
from app.db.repositories import documents as documents_repo
from app.db.repositories.documents import clock_hms
from app.db.uow import transaction
from app.parsing.blocks import html_to_blocks
from app.parsing.outline import (
    SOURCE_HEADINGS,
    SOURCE_NONE,
    SOURCE_PDF,
    OutlineItem,
    outline_from_blocks,
    outline_from_pdf,
    outline_log_line,
)
from app.parsing.registry import convert, detect_format
from app.parsing.types import ConvertedDocument, ConvertOptions
from app.storage.keys import validate_key
from app.worker.errors import PermanentError

if TYPE_CHECKING:
    from pathlib import Path

    from app.core.config import Settings
    from app.core.container import Container
    from app.db.repositories.documents import DocumentRow
    from app.worker.context import TaskContext
    from app.worker.queue import TaskRow

__all__ = ["build_outline"]


def _document_id(task: TaskRow) -> str:
    """Identyfikator dokumentu z payloadu; brak → błąd trwały (zadanie od razu ``failed``)."""
    document_id = task.payload.get("document_id")
    if not document_id:
        raise PermanentError("Zadanie build_outline bez pola document_id")
    return str(document_id)


def _convert_options(settings: Settings) -> ConvertOptions:
    """Opcje konwersji bez modeli: brak OCR/wizji (K21 §2 p. 4)."""
    return ConvertOptions(
        ocr_available=False,
        vision_available=False,
        ocr_langs=settings.ocr_langs,
        max_uncompressed_bytes=settings.max_uncompressed_mb * 1024 * 1024,
        max_archive_ratio=settings.max_archive_ratio,
    )


def _headings_from_file(path: Path, suffix: str, settings: Settings) -> list[OutlineItem]:
    """Nagłówki z ponownej konwersji pliku konwerterami bez modeli (K21 §2 p. 2b/4).

    Strona wymagająca rozpoznania OCR/wizji (``pending_pages``) bez modelu nie da nagłówków
    → pusta lista (spis ``none``).
    """
    fmt = detect_format(path, suffix)
    converted: ConvertedDocument = convert(path, fmt, _convert_options(settings))
    if converted.pending_pages:
        return []
    return outline_from_blocks(html_to_blocks(converted.html))


def _determine(container: Container, doc: DocumentRow) -> tuple[list[OutlineItem], str]:
    """Wyznacza spis i źródło dla dokumentu ze storage (K21 §2 p. 2/4).

    Pierwsze niepuste źródło wygrywa, jak w ``parse_document``: PDF → zakładki
    (``pdf_bookmarks``); PDF bez zakładek i inne formaty → nagłówki konwersji bez modeli
    (``headings``, K21 §2 p. 2b); konwersja wymagająca modelu (strony ``pending``) albo
    brak pozycji po obu drogach → ``none``. Synchroniczne — wołane w wątku.
    """
    path = container.storage.local_path(validate_key(doc.location))
    if doc.suffix.lower() == "pdf":
        bookmarks = outline_from_pdf(path)
        if bookmarks:
            return bookmarks, SOURCE_PDF
    headings = _headings_from_file(path, doc.suffix, container.settings)
    return (headings, SOURCE_HEADINGS) if headings else ([], SOURCE_NONE)


def _sessionmaker(container: Container) -> async_sessionmaker[AsyncSession]:
    """Fabryka sesji z kontenera; brak (kontener nie wystartował) → ``RuntimeError`` (C4)."""
    sessionmaker = container.sessionmaker
    if sessionmaker is None:
        raise RuntimeError("container not started")
    return sessionmaker


async def build_outline(task: TaskRow, ctx: TaskContext) -> None:
    """Uzupełnia profil spisu dokumentu z payloadu (K21 §2 p. 4); błąd → ``none`` + log."""
    document_id = _document_id(task)
    container = ctx.container
    sm = _sessionmaker(container)
    async with transaction(sm) as session:
        doc = await documents_repo.get(session, document_id)
    if doc is None:  # dokument usunięty w międzyczasie — zadanie kończy się bez błędu
        return
    try:
        outline, source = await asyncio.to_thread(_determine, container, doc)
        warning: str | None = None
    except Exception as exc:  # noqa: BLE001  # granica: błąd spisu nie zatrzymuje prób (K21 §2 p. 4)
        outline, source = [], SOURCE_NONE
        warning = f"[WARNING] Outline detection failed: {exc}"
    now_ms = container.clock.now_ms()
    async with transaction(sm) as session:
        await document_profiles.upsert(
            session,
            document_id=document_id,
            dataset_id=doc.dataset_id,
            outline=[dict(item) for item in outline],
            outline_source=source,
            now_ms=now_ms,
        )
        lines = [f"{clock_hms(now_ms)} {outline_log_line(source, len(outline))}"]
        if warning is not None:
            lines.insert(0, f"{clock_hms(now_ms)} {warning}")
        # ``progress=None`` nie zmienia ``progress``; ``run`` pozostaje bez zmian (K21 §2 p. 4).
        await documents_repo.append_progress(
            session, document_id, progress=None, lines="\n".join(lines), now_ms=now_ms
        )
