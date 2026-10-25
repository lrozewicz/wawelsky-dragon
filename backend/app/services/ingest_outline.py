"""Spis treści na końcu udanego ``parse_document`` (krok 11c; K21 §2 p. 1-3).

Wydzielone z ``ingest_pipeline`` (DEC-099: limit 400 linii). Wołane wyłącznie przez
``run_parse`` po zapisie chunków: wyznacza spis (zakładki PDF → nagłówki bloków → brak),
zapisuje profil w ``document_profiles`` (upsert — reparsowanie nadpisuje, K21 §1) i dopisuje
linię do ``progress_msg`` dokumentu. Błąd wyznaczania spisu **nie** psuje parsowania:
zapis idzie z ``outline_source='none'``, a linia ostrzeżenia trafia do logu (K21 §2 p. 1).
Ścieżka wznowienia z digestu (``Reused previous chunks.``) kroku nie wykonuje — profil
powstał przy pierwszym parsowaniu, a instalacje sprzed v1.3 uzupełnia sweep (K21 §2 p. 4).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.db.repositories import document_profiles
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
from app.storage.keys import validate_key

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.core.container import Container
    from app.db.repositories.documents import DocumentRow
    from app.services.ingest_progress import ProgressReporter


def _determine(container: Container, doc: DocumentRow, html: str) -> tuple[list[OutlineItem], str]:
    """Krok 11c: pierwsze niepuste źródło spisu wygrywa (K21 §2 p. 2)."""
    if doc.suffix.lower() == "pdf":
        path = container.storage.local_path(validate_key(doc.location))
        bookmarks = outline_from_pdf(path)
        if bookmarks:
            return bookmarks, SOURCE_PDF
    headings = outline_from_blocks(html_to_blocks(html))
    return (headings, SOURCE_HEADINGS) if headings else ([], SOURCE_NONE)


async def finish_outline(
    container: Container,
    sm: async_sessionmaker[AsyncSession],
    rep: ProgressReporter,
    doc: DocumentRow,
    html: str,
) -> None:
    """Wyznacza spis, zapisuje profil dokumentu i loguje wynik (K21 §2 p. 1-3)."""
    try:
        outline, source = _determine(container, doc, html)
    except Exception as exc:  # noqa: BLE001  # granica: spis nie psuje parsowania (K21 §2 p. 1)
        outline, source = [], SOURCE_NONE
        await rep.report(1.0, f"[WARNING] Outline detection failed: {exc}")
    async with transaction(sm) as session:
        await document_profiles.upsert(
            session,
            document_id=doc.id,
            dataset_id=doc.dataset_id,
            outline=[dict(item) for item in outline],
            outline_source=source,
            now_ms=container.clock.now_ms(),
        )
    await rep.report(1.0, outline_log_line(source, len(outline)))
