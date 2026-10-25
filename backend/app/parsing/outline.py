"""Wyznaczanie spisu treści dokumentu (K21 §2 p. 2): zakładki PDF → nagłówki → brak.

Czyste funkcje (import-linter „Parsowanie bez DB/API/workera”): jedyne I/O to odczyt PDF-a
z podanej ścieżki albo bajtów. Wołane przez ``app.services.ingest_outline`` na końcu
``parse_document`` (K21 §2 p. 1) oraz przez zadanie ``build_outline`` (§2 p. 4).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

from pypdfium2 import PdfDocument

if TYPE_CHECKING:
    from app.domain.chunking.types import Block

MAX_TITLE = 300  # długość tytułu pozycji spisu (K21 §1)
MAX_ITEMS = 2000  # liczba pozycji spisu (K21 §1)

SOURCE_PDF = "pdf_bookmarks"
SOURCE_HEADINGS = "headings"
SOURCE_NONE = "none"

_NONE_LINE = "Outline: none (no bookmarks or headings)"
_WS = re.compile(r"\s+")


class OutlineItem(TypedDict):
    """Pozycja spisu treści (K21 §1): ``level`` 0 = najwyższy, ``page`` od 1 albo None."""

    level: int
    title: str
    page: int | None


def _title(raw: str) -> str:
    """Tytuł pozycji: białe znaki zwinięte, przycięty do ``MAX_TITLE``."""
    return _WS.sub(" ", raw).strip()[:MAX_TITLE]


def normalize_outline(items: Iterable[tuple[int, str, int | None]]) -> list[OutlineItem]:
    """Kanonizuje pozycje spisu (K21 §1): puste tytuły pomijane, nadmiar odrzucany od końca."""
    out: list[OutlineItem] = []
    for level, title, page in items:
        text = _title(title)
        if not text:
            continue
        out.append(OutlineItem(level=level, title=text, page=page))
        if len(out) >= MAX_ITEMS:
            break
    return out


def _bookmark_page(bookmark: Any) -> int | None:
    """Strona zakładki od 1 (``dest.page_index + 1``); brak celu → None (K21 §2 p. 2a)."""
    dest = bookmark.get_dest()
    if dest is None:
        return None
    index = dest.get_index()
    return None if index is None else int(index) + 1


def outline_from_pdf(source: str | Path | bytes) -> list[OutlineItem]:
    """Zakładki PDF (`pypdfium2` ``get_toc()``, K21 §2 p. 2a); brak zakładek → ``[]``."""
    with PdfDocument(source) as pdf:
        items = [
            (bookmark.level, bookmark.get_title(), _bookmark_page(bookmark))
            for bookmark in pdf.get_toc()
        ]
    return normalize_outline(items)


def _heading_page(block: Block) -> int | None:
    """Strona nagłówka z pierwszej pozycji bloku (``data-page`` konwersji); brak → None."""
    return block.positions[0][0] if block.positions else None


def outline_from_blocks(blocks: Iterable[Block]) -> list[OutlineItem]:
    """Nagłówki bloków konwersji (K21 §2 p. 2b); poziom względem najwyższego nagłówka."""
    headings: list[tuple[int, str, int | None]] = []
    for block in blocks:
        if block.kind == "heading" and block.level is not None:
            headings.append((block.level, block.text, _heading_page(block)))
    if not headings:
        return []
    top = min(level for level, _, _ in headings)
    return normalize_outline((level - top, title, page) for level, title, page in headings)


def outline_log_line(source: str, n: int) -> str:
    """Linia logu ingestii po wyznaczeniu spisu — dosłownie wg K21 §2 p. 3 (po angielsku)."""
    if source == SOURCE_PDF:
        return f"Outline: {n} entries (PDF bookmarks)"
    if source == SOURCE_HEADINGS:
        return f"Outline: {n} entries (headings)"
    return _NONE_LINE
