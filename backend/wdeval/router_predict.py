"""Predykcja decyzji routera stron PDF bez parsowania dokumentu (kontrakt C9).

Odwzorowuje logikę per-strona z ``app.parsing.converters.pdf`` (``pdf_route_batch``):
``pdfplumber`` → ``PdfPageInfo`` → ``page_text_quality`` → ``route_page``. Nie woła
ani modeli, ani Tesseracta — liczy wyłącznie decyzje. Prywatna ``_image_cover`` jest
przepisana lokalnie (zakaz importowania prywatnych funkcji z ``app``).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

from app.parsing.pdf_router import PdfPageInfo, page_text_quality, route_page
from app.parsing.types import ConvertOptions, PdfStrategy

_CID_MARKER = "(cid:"


@dataclass(frozen=True)
class RouterCounts:
    """Liczba stron per tryb routingu (dla manifestu ramienia)."""

    pages_total: int
    pages_via_text: int
    pages_via_ocr: int
    pages_via_vision: int


ZERO_COUNTS: RouterCounts = RouterCounts(
    pages_total=0, pages_via_text=0, pages_via_ocr=0, pages_via_vision=0
)


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


def predict_router(
    pdf_path: Path,
    strategy: PdfStrategy,
    *,
    vision_available: bool,
    ocr_available: bool,
) -> RouterCounts:
    """Przewiduje routing każdej strony PDF dla danej strategii i dostępności OCR/VLM."""
    pages_via_text = 0
    pages_via_ocr = 0
    pages_via_vision = 0
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            info = PdfPageInfo(
                text=text,
                width_pt=page.width,
                height_pt=page.height,
                image_cover=_image_cover(page),
                cid_count=text.count(_CID_MARKER),
            )
            mode = route_page(
                page_text_quality(info),
                strategy,
                ConvertOptions(
                    pdf_strategy=strategy,
                    vision_available=vision_available,
                    ocr_available=ocr_available,
                ),
            )
            if mode == "text":
                pages_via_text += 1
            elif mode == "ocr":
                pages_via_ocr += 1
            elif mode == "vision":
                pages_via_vision += 1
            else:
                raise AssertionError(f"nieznany tryb strony: {mode}")
    return RouterCounts(
        pages_total=pages_via_text + pages_via_ocr + pages_via_vision,
        pages_via_text=pages_via_text,
        pages_via_ocr=pages_via_ocr,
        pages_via_vision=pages_via_vision,
    )


def sum_counts(counts: Iterable[RouterCounts]) -> RouterCounts:
    """Sumuje zliczenia routera (pole po polu); pusta sekwencja → ``ZERO_COUNTS``."""
    total = ZERO_COUNTS
    for count in counts:
        total = RouterCounts(
            pages_total=total.pages_total + count.pages_total,
            pages_via_text=total.pages_via_text + count.pages_via_text,
            pages_via_ocr=total.pages_via_ocr + count.pages_via_ocr,
            pages_via_vision=total.pages_via_vision + count.pages_via_vision,
        )
    return total
