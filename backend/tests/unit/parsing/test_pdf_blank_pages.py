"""Puste strony PDF nie idą do modelu wizji (zmyślony tekst + cache wspólny dla pustych stron)."""

from pathlib import Path

from PIL import Image, ImageDraw

from app.parsing.converters.pdf import _blank, convert_pdf
from app.parsing.types import ConvertOptions
from tests.unit.parsing.factories import PdfPage, PdfText, body_text, make_pdf


def test_white_page_is_blank() -> None:
    assert _blank(Image.new("RGB", (595, 842), "white"))


def test_page_with_text_is_not_blank() -> None:
    image = Image.new("RGB", (595, 842), "white")
    ImageDraw.Draw(image).text((50, 50), "Raport 2022", fill="black")
    assert not _blank(image)


def test_light_gray_mark_is_not_blank() -> None:
    image = Image.new("RGB", (595, 842), "white")
    ImageDraw.Draw(image).rectangle((10, 10, 20, 20), fill=(200, 200, 200))
    assert not _blank(image)


def test_white_page_without_text_is_not_pending(tmp_path: Path) -> None:
    path = tmp_path / "blank.pdf"
    text = PdfPage(texts=[PdfText(72, 100 + i * 14, 11, body_text(12, f"w{i}")) for i in range(30)])
    path.write_bytes(make_pdf([text, PdfPage()]))
    doc = convert_pdf(path, ConvertOptions(ocr_available=True, vision_available=True))
    assert [page.number for page in doc.pending_pages] == []
