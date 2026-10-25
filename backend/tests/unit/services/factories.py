"""Fabryki małych PDF-ów dla testów konwersji E5-H8a (brief T2).

Bazują na ręcznym generatorze z ``tests.unit.parsing.factories`` (bez nowych zależności);
strony są małe (300x300 pt), żeby render partii w testach był szybki.
"""

from __future__ import annotations

from tests.unit.parsing.factories import PdfPage, PdfText, body_text, make_pdf

PAGE_SIZE = 300.0  # pt — mała strona, szybki render partii
TEXT_LINE = "Zdanie kontrolne bez diakrytykow. " * 8  # > 150 znaków (bramka routera)


def text_page(number: int) -> PdfPage:
    """Strona z warstwą tekstową (tryb 'text'), z numerem strony."""
    return PdfPage(
        texts=[PdfText(20, 20, 10, f"Page {number}"), PdfText(20, 60, 10, TEXT_LINE)],
        width=PAGE_SIZE,
        height=PAGE_SIZE,
    )


def scan_page() -> PdfPage:
    """Strona bez warstwy tekstowej (obraz na całej stronie) → tryb OCR/VLM."""
    return PdfPage(image=(0, 0, PAGE_SIZE, PAGE_SIZE), width=PAGE_SIZE, height=PAGE_SIZE)


def text_pdf(pages: int) -> bytes:
    """PDF z `pages` stronami tekstowymi."""
    return make_pdf([text_page(number) for number in range(1, pages + 1)])


def scan_pdf(pages: int) -> bytes:
    """PDF-skan z `pages` stronami bez warstwy tekstowej (obraz rastrowy)."""
    return make_pdf([scan_page() for _ in range(pages)])


def document_pdf(pages: int) -> bytes:
    """PDF z powtarzanym nagłówkiem/stopką i tabelą przechodzącą granicę partii (25/26)."""
    return make_pdf(
        [
            PdfPage(
                texts=[
                    PdfText(20, 15, 10, "Naglowek powtarzany"),
                    PdfText(20, 60, 10, f"Tresc strony {number} " + body_text(30)),
                    PdfText(20, 280, 10, "Stopka powtarzana"),
                ],
                grid=(20, 200, 280, 260, 2, 3) if number in (25, 26) else None,
                width=PAGE_SIZE,
                height=PAGE_SIZE,
            )
            for number in range(1, pages + 1)
        ]
    )
