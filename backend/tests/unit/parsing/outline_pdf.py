"""PDF z zakładkami do testów spisu treści (reportlab → pypdfium2 ``get_toc()``)."""

from __future__ import annotations

import io
from collections.abc import Sequence

from reportlab.pdfgen.canvas import Canvas

# Tekst strony ≥ 150 znaków — strona uchodzi za tekstową przy strategii ``auto`` (05 §8.2).
PAGE_TEXT = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 6


def make_outlined_pdf(entries: Sequence[tuple[str, int]]) -> bytes:
    """PDF z zakładkami: jedna strona na wpis (tytuł, poziom zakładki wg reportlab)."""
    buffer = io.BytesIO()
    canvas = Canvas(buffer)
    for number, (title, level) in enumerate(entries):
        key = f"sec-{number}"
        canvas.drawString(50, 700, PAGE_TEXT)
        canvas.bookmarkPage(key)
        canvas.addOutlineEntry(title, key, level=level)
        canvas.showPage()
    canvas.save()
    return buffer.getvalue()
