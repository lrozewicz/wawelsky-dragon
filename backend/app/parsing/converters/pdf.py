"""Konwerter PDF (kontrakt C3/C7; 05 §8.2-8.4).

pdfplumber w trybie text, pypdfium2 do renderu stron pending i fallbacku (cid:).
Duże dokumenty idą partiami stron (PAGE_BATCH): plan → faza A (routing + PNG stron pending)
→ faza B (linie powtarzane) → faza C (sekcje HTML) → złożenie wyniku. Każda funkcja fazy A/C
otwiera i zamyka własny dokument, żeby nie trzymać w pamięci chars/objects wszystkich stron naraz.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import pdfplumber
import pypdfium2
import pypdfium2.raw as pdfium_raw

from app.parsing.converters.common import finish, png_bytes
from app.parsing.converters.pdf_layout import (
    TextLine,
    page_lines,
    render_text_page,
    repeated_lines,
)
from app.parsing.errors import corrupted_file, empty_document, encrypted_file, limit_exceeded
from app.parsing.html import paragraphs_html, section_html
from app.parsing.pdf_router import (
    PageQuality,
    PdfPageInfo,
    page_text_quality,
    route_page,
    route_reason,
)
from app.parsing.types import (
    OCR_DPI,
    VISION_DPI,
    ConvertedDocument,
    ConvertOptions,
    PageMode,
    PendingPage,
)

_CID_MARKER = "(cid:"
_DIAGNOSIS = "PDF has no text layer and OCR/VLM is not available"
PAGE_BATCH = 25  # stron na partię; po partii obiekty stron pdfplumber są zamykane


@dataclass(frozen=True)
class _RoutedPage:
    """Routing strony bez obiektu pdfplumber: tekst + lekkie linie na potrzeby renderu."""

    number: int
    mode: PageMode
    quality: PageQuality
    text: str
    height: float
    lines: tuple[TextLine, ...]  # puste dla stron pending (tryb inny niż text)


@dataclass(frozen=True)
class PdfPlan:
    """Plan konwersji: liczba stron, partie wybranych numerów (1-based) i metadane."""

    total: int
    batches: tuple[tuple[int, ...], ...]
    metadata: dict[str, str]


@dataclass(frozen=True)
class RoutedBatch:
    """Wynik fazy A partii: routing stron + PNG stron pending, w kolejności stron."""

    routed: tuple[_RoutedPage, ...]
    pending: tuple[PendingPage, ...]


@dataclass(frozen=True)
class RenderedBatch:
    """Wynik fazy C partii: sekcje (numer, HTML) wszystkich stron, ostrzeżenia i statystyki."""

    sections: tuple[tuple[int, str], ...]  # pusta treść dla stron pending
    warnings: tuple[str, ...]
    stats: dict[str, int]  # pages_text / pages_ocr / pages_vision dla partii


def _batches[T](items: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    """Dzieli sekwencję na partie po `size` elementów (zachowuje kolejność)."""
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _open_pdfium(path: Path) -> pypdfium2.PdfDocument:
    """Otwiera PDF w pypdfium2; błąd hasła → EncryptedFile, inny → CorruptedFile."""
    try:
        return pypdfium2.PdfDocument(path)
    except pypdfium2.PdfiumError as exc:
        if getattr(exc, "err_code", None) == pdfium_raw.FPDF_ERR_PASSWORD:
            raise encrypted_file("pdf") from None
        raise corrupted_file("pdf", str(exc)) from None


def _image_cover(page: pdfplumber.page.Page) -> float:
    """Suma pól bbox obrazów przyciętych do strony, podzielona przez pole strony (0..1)."""
    area = page.width * page.height
    if area <= 0:
        return 0.0
    covered = 0.0
    for image in page.images:
        x0 = max(0.0, float(image["x0"]))
        top = max(0.0, float(image["top"]))
        x1 = min(page.width, float(image["x1"]))
        bottom = min(page.height, float(image["bottom"]))
        if x1 > x0 and bottom > top:
            covered += (x1 - x0) * (bottom - top)
    return min(1.0, covered / area)


def _pdfium_text(pdf: pypdfium2.PdfDocument, index: int) -> str:
    """Tekst strony z pypdfium2 (fallback, gdy pdfplumber zwraca znaczniki (cid:)."""
    page = pdf[index]
    try:
        textpage = page.get_textpage()
        try:
            return str(textpage.get_text_range())
        finally:
            textpage.close()
    finally:
        page.close()


def _pending_reason(quality: PageQuality, opts: ConvertOptions) -> str:
    """Powód odesłania strony do OCR/VLM: z routera albo ze strategii."""
    if opts.pdf_strategy == "vision":
        return "strategy=vision"
    if opts.pdf_strategy == "fast":
        return "empty page"
    return route_reason(quality, opts)


def _metadata(pdf: pypdfium2.PdfDocument) -> dict[str, str]:
    """Tytuł i autor z metadanych PDF, gdy niepuste."""
    raw = pdf.get_metadata_dict()
    metadata: dict[str, str] = {}
    for key, source in (("title", "Title"), ("author", "Author")):
        value = raw.get(source)
        if value:
            metadata[key] = str(value)
    return metadata


def pdf_plan(path: Path, opts: ConvertOptions) -> PdfPlan:
    """Waliduje PDF jak convert_pdf (pusta, hasło, limit, 0 stron) i zwraca plan partii."""
    if path.stat().st_size == 0:
        raise empty_document("file is empty")
    pdf = _open_pdfium(path)
    try:
        total = len(pdf)
        if total > opts.max_pages:
            raise limit_exceeded("pages", total, opts.max_pages)
        if total == 0:
            raise empty_document("PDF has no pages")
        selected = [
            number
            for number in range(1, total + 1)
            if any(lo <= number <= hi for lo, hi in opts.pages)
        ]
        batches = tuple(tuple(batch) for batch in _batches(selected, PAGE_BATCH))
        return PdfPlan(total, batches, _metadata(pdf))
    finally:
        pdf.close()


def _render_pending(
    path: Path, routed: Sequence[_RoutedPage], opts: ConvertOptions
) -> tuple[PendingPage, ...]:
    """Faza A: render PNG stron trybu ocr/vision partii (pypdfium2), w kolejności stron."""
    if not any(page.mode != "text" for page in routed):
        return ()
    pending: list[PendingPage] = []
    pdf = _open_pdfium(path)
    try:
        for page in routed:
            mode = page.mode
            if mode == "text":
                continue
            dpi = VISION_DPI if mode == "vision" else OCR_DPI
            pdfium_page = pdf[page.number - 1]
            try:
                image = pdfium_page.render(scale=dpi / 72).to_pil()
            finally:
                pdfium_page.close()
            # Warstwa trafia do korekty tylko, gdy przeszła bramkę routera (DEC-248 P1);
            # dla strategii vision _pending_reason zwraca "strategy=vision", więc
            # bramkę liczymy wprost przez route_reason.
            text_layer = page.text if route_reason(page.quality, opts) == "" else ""
            pending.append(
                PendingPage(
                    page.number,
                    mode,
                    png_bytes(image),
                    _pending_reason(page.quality, opts),
                    text_layer,
                )
            )
    finally:
        pdf.close()
    return tuple(pending)


def pdf_route_batch(path: Path, pages: tuple[int, ...], opts: ConvertOptions) -> RoutedBatch:
    """Faza A partii: routing stron (pdfplumber) i render PNG stron pending (pypdfium2)."""
    routed: list[_RoutedPage] = []
    with pdfplumber.open(path, pages=list(pages)) as document:
        for number, page in zip(pages, document.pages, strict=True):
            text = page.extract_text() or ""
            info = PdfPageInfo(
                text=text,
                width_pt=page.width,
                height_pt=page.height,
                image_cover=_image_cover(page),
                cid_count=text.count(_CID_MARKER),
            )
            quality = page_text_quality(info)
            mode = route_page(quality, opts.pdf_strategy, opts)
            lines = tuple(page_lines(page)) if mode == "text" else ()
            routed.append(_RoutedPage(number, mode, quality, text, page.height, lines))
    return RoutedBatch(tuple(routed), _render_pending(path, routed, opts))


def pdf_repeated(routed: Sequence[_RoutedPage]) -> frozenset[str]:
    """Faza B: klucze linii powtarzających się (nagłówki/stopki) ze stron trybu text."""
    return repeated_lines([(page.height, page.lines) for page in routed if page.mode == "text"])


def pdf_render_batch(
    path: Path, routed: tuple[_RoutedPage, ...], drop: frozenset[str], opts: ConvertOptions
) -> RenderedBatch:
    """Faza C partii: sekcje HTML stron text (puste dla pending), ostrzeżenia i statystyki."""
    sections: list[tuple[int, str]] = []
    warnings: list[str] = []
    stats = {"pages_text": 0, "pages_ocr": 0, "pages_vision": 0}
    text_pages = [page for page in routed if page.mode == "text"]
    document = (
        pdfplumber.open(path, pages=[page.number for page in text_pages]) if text_pages else None
    )
    text_iterator: Iterator[pdfplumber.page.Page] = (
        iter(document.pages) if document is not None else iter(())
    )
    # pypdfium2 otwieramy tylko wtedy, gdy partia ma stronę z fallbackiem (cid:).
    cid_text: dict[int, str] = {}
    cid_pages = [page for page in text_pages if _CID_MARKER in page.text]
    if cid_pages:
        pdfium = _open_pdfium(path)
        try:
            cid_text = {page.number: _pdfium_text(pdfium, page.number - 1) for page in cid_pages}
        finally:
            pdfium.close()
    try:
        for page in routed:
            if page.mode == "text":
                plumber_page = next(text_iterator)
                if _CID_MARKER in page.text:
                    inner = paragraphs_html(cid_text[page.number])
                else:
                    inner = render_text_page(plumber_page, page.lines, drop)
                stats["pages_text"] += 1
                reason = route_reason(page.quality, opts)
                if reason and not (opts.vision_available or opts.ocr_available):
                    warnings.append(
                        f"page {page.number}: low text quality ({reason}), no OCR/VLM available"
                    )
            else:
                stats["pages_ocr" if page.mode == "ocr" else "pages_vision"] += 1
                inner = ""
            sections.append((page.number, section_html("page", page.number, inner)))
    finally:
        if document is not None:
            document.close()
    return RenderedBatch(tuple(sections), tuple(warnings), stats)


def pdf_assemble(
    plan: PdfPlan, pending: Sequence[PendingPage], rendered: Sequence[RenderedBatch]
) -> ConvertedDocument:
    """Składa partie w kolejności stron (niezależnie od kolejności ukończenia) i woła finish."""
    ordered = sorted(rendered, key=lambda batch: batch.sections[0][0] if batch.sections else 0)
    html = "".join(section for batch in ordered for _, section in batch.sections)
    warnings = [warning for batch in ordered for warning in batch.warnings]
    stats = {"pages_text": 0, "pages_ocr": 0, "pages_vision": 0}
    for batch in ordered:
        for key in stats:
            stats[key] += batch.stats.get(key, 0)
    return finish(
        html,
        diagnosis=_DIAGNOSIS,
        pages=plan.total,
        pending=sorted(pending, key=lambda page: page.page),
        metadata=plan.metadata,
        warnings=warnings,
        stats=stats,
    )


def convert_pdf(path: Path, opts: ConvertOptions) -> ConvertedDocument:
    """Zamienia PDF w HTML 05 §7: strony dobre → sekcje text, słabe → PendingPage z renderem PNG.

    Sekwencyjnie: plan → faza A dla wszystkich partii → faza B → faza C → złożenie wyniku.
    """
    plan = pdf_plan(path, opts)
    routed = [pdf_route_batch(path, pages, opts) for pages in plan.batches]
    drop = pdf_repeated([page for batch in routed for page in batch.routed])
    rendered = [pdf_render_batch(path, batch.routed, drop, opts) for batch in routed]
    pending = [page for batch in routed for page in batch.pending]
    return pdf_assemble(plan, pending, rendered)
