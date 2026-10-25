"""Testy binaries OCR: prawdziwy tesseract na obrazie i PDF (kontrakt C12, obraz test-ocr)."""

from __future__ import annotations

import shutil
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from app.parsing.converters.image import convert_image
from app.parsing.converters.pdf import convert_pdf
from app.parsing.recognizers import TesseractRecognizer, complete_pages, self_check
from app.parsing.types import ConvertedDocument, ConvertOptions, PendingPage
from tests.unit.parsing.factories import PdfPage, PdfText, make_pdf

pytestmark = [
    pytest.mark.binaries,
    pytest.mark.skipif(shutil.which("tesseract") is None, reason="brak tesseract"),
]


def hello_png() -> bytes:
    """PNG 800x200, białe tło, czarny tekst „Hello World 2026”."""
    image = Image.new("RGB", (800, 200), "white")
    draw = ImageDraw.Draw(image)
    draw.text((20, 70), "Hello World 2026", fill="black", font=ImageFont.load_default(size=48))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


async def test_tesseract_recognizes_hello() -> None:
    fragment = await TesseractRecognizer().recognize(hello_png(), page=1)
    assert "Hello" in fragment


async def test_convert_image_then_complete_pages(tmp_path: Path) -> None:
    path = tmp_path / "hello.png"
    path.write_bytes(hello_png())
    doc = convert_image(path, ConvertOptions(ocr_available=True))
    assert [pending.mode for pending in doc.pending_pages] == ["ocr"]
    result = await complete_pages(doc, ocr=TesseractRecognizer(), vision=None)
    assert "Hello" in result.html
    assert result.stats["pages_ocr"] == 1
    assert result.pending_pages == []


async def test_pdf_vision_strategy_goes_through_ocr(tmp_path: Path) -> None:
    pdf = make_pdf([PdfPage(texts=[PdfText(x=72, top=100, size=36, text="HELLO OCR 2026")])])
    path = tmp_path / "hello.pdf"
    path.write_bytes(pdf)
    doc = convert_pdf(path, ConvertOptions(pdf_strategy="vision", ocr_available=True))
    pending: list[PendingPage] = doc.pending_pages
    assert [page.mode for page in pending] == ["ocr"]
    result: ConvertedDocument = await complete_pages(doc, ocr=TesseractRecognizer(), vision=None)
    assert "HELLO" in result.html.upper()


def test_self_check_sees_tesseract() -> None:
    assert self_check()["tesseract"] is True
