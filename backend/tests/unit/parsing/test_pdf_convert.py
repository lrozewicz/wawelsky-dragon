"""Testy convert_pdf (C7): routing stron, pending_pages, błędy, fallback (cid:)."""

import io
import pickle
from collections.abc import Sequence
from pathlib import Path

import pytest
from PIL import Image

from app.parsing.converters.pdf import convert_pdf
from app.parsing.errors import (
    CorruptedFile,
    EmptyDocument,
    EncryptedFile,
    LimitExceeded,
)
from app.parsing.types import ConvertedDocument, ConvertOptions
from tests.unit.parsing.factories import PdfPage, PdfText, body_text, make_pdf

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "parsing"


def _write(tmp_path: Path, pages: Sequence[PdfPage], *, title: str | None = None) -> Path:
    path = tmp_path / "doc.pdf"
    path.write_bytes(make_pdf(pages, title=title))
    return path


def test_two_good_pages(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        [
            PdfPage(texts=[PdfText(72, 100, 11, body_text(30))]),
            PdfPage(texts=[PdfText(72, 100, 11, body_text(30))]),
        ],
    )
    doc = convert_pdf(path, ConvertOptions())
    assert isinstance(doc, ConvertedDocument)
    assert doc.pages == 2  # noqa: PLR2004 — wartość konstruowana w teście
    assert '<section data-page="1">' in doc.html
    assert '<section data-page="2">' in doc.html
    assert doc.pending_pages == []
    assert doc.stats["pages_text"] == 2  # noqa: PLR2004 — wartość konstruowana w teście
    assert doc.stats["chars"] > 0


def test_header_and_footer_dropped(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        [
            PdfPage(
                texts=[
                    PdfText(72, 20, 11, "Raport roczny"),
                    PdfText(72, 100, 11, body_text(30)),
                    PdfText(72, 820, 11, f"Strona {number}"),
                ]
            )
            for number in (1, 2, 3)
        ],
    )
    doc = convert_pdf(path, ConvertOptions())
    assert "Raport roczny" not in doc.html
    assert "Strona" not in doc.html
    assert "lorem0" in doc.html  # treść zostaje
    assert doc.stats["pages_text"] == 3  # noqa: PLR2004 — wartość konstruowana w teście


def test_low_quality_page_pending_ocr(tmp_path: Path) -> None:
    path = _write(tmp_path, [PdfPage(texts=[PdfText(72, 100, 11, body_text(6))])])
    doc = convert_pdf(path, ConvertOptions(ocr_available=True))
    assert doc.stats["pages_text"] == 0
    assert doc.stats["pages_ocr"] == 1
    (pending,) = doc.pending_pages
    assert (pending.page, pending.mode, pending.reason) == (1, "ocr", "chars<150")
    assert pending.image_png.startswith(b"\x89PNG")
    assert '<section data-page="1"></section>' in doc.html


def test_low_quality_page_pending_vision_render_width(tmp_path: Path) -> None:
    path = _write(tmp_path, [PdfPage(texts=[PdfText(72, 100, 11, body_text(6))])])
    doc = convert_pdf(path, ConvertOptions(vision_available=True))
    (pending,) = doc.pending_pages
    assert pending.mode == "vision"
    image = Image.open(io.BytesIO(pending.image_png))
    assert abs(image.size[0] - 595.0 * 200 / 72) <= 2  # noqa: PLR2004 — tolerancja renderu (VISION_DPI = 200)


def test_image_page_routes_to_vision(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        [
            PdfPage(
                texts=[PdfText(72, 100, 11, body_text(5))],
                image=(10.0, 10.0, 585.0, 832.0),  # ~94% pola strony
            )
        ],
    )
    doc = convert_pdf(path, ConvertOptions(vision_available=True))
    (pending,) = doc.pending_pages
    assert pending.mode == "vision"
    assert pending.reason == "chars<150"  # route_reason: liczba znaków przed image_cover


def test_strategy_vision_all_pages_pending(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        [
            PdfPage(texts=[PdfText(72, 100, 11, body_text(30))]),
            PdfPage(texts=[PdfText(72, 100, 11, body_text(30))]),
        ],
    )
    doc = convert_pdf(path, ConvertOptions(pdf_strategy="vision", vision_available=True))
    assert [pending.mode for pending in doc.pending_pages] == ["vision", "vision"]
    assert {pending.reason for pending in doc.pending_pages} == {"strategy=vision"}
    assert doc.stats["pages_vision"] == 2  # noqa: PLR2004 — wartość konstruowana w teście
    assert '<section data-page="2"></section>' in doc.html


def test_strategy_fast_empty_page_pending_ocr(tmp_path: Path) -> None:
    path = _write(tmp_path, [PdfPage()])
    doc = convert_pdf(path, ConvertOptions(pdf_strategy="fast", ocr_available=True))
    (pending,) = doc.pending_pages
    assert (pending.mode, pending.reason) == ("ocr", "empty page")


def test_low_quality_warning_without_ocr(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        [
            PdfPage(texts=[PdfText(72, 100, 11, body_text(5))]),
            PdfPage(texts=[PdfText(72, 100, 11, body_text(30))]),
        ],
    )
    doc = convert_pdf(path, ConvertOptions())
    assert doc.warnings == ["page 1: low text quality (chars<150), no OCR/VLM available"]
    assert doc.stats["pages_text"] == 2  # noqa: PLR2004 — wartość konstruowana w teście


def test_empty_document_without_ocr(tmp_path: Path) -> None:
    path = _write(tmp_path, [PdfPage()])
    with pytest.raises(EmptyDocument):
        convert_pdf(path, ConvertOptions())


def test_page_selection(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        [PdfPage(texts=[PdfText(72, 100, 11, body_text(30))]) for _ in range(3)],
    )
    doc = convert_pdf(path, ConvertOptions(pages=((2, 2),)))
    assert doc.pages == 3  # noqa: PLR2004 — wartość konstruowana w teście
    assert doc.html.count("<section ") == 1
    assert '<section data-page="2">' in doc.html


def test_max_pages_limit(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        [
            PdfPage(texts=[PdfText(72, 100, 11, body_text(30))]),
            PdfPage(texts=[PdfText(72, 100, 11, body_text(30))]),
        ],
    )
    with pytest.raises(LimitExceeded):
        convert_pdf(path, ConvertOptions(max_pages=1))


def test_encrypted_file() -> None:
    with pytest.raises(EncryptedFile):
        convert_pdf(FIXTURES / "encrypted.pdf", ConvertOptions())


def test_corrupted_file(tmp_path: Path) -> None:
    path = tmp_path / "corrupted.pdf"
    path.write_bytes(b"%PDF-1.4 garbage")
    with pytest.raises(CorruptedFile):
        convert_pdf(path, ConvertOptions())


def test_zero_bytes_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.pdf"
    path.write_bytes(b"")
    with pytest.raises(EmptyDocument):
        convert_pdf(path, ConvertOptions())


def test_cid_markers_fallback_to_pdfium(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        [
            PdfPage(
                texts=[
                    PdfText(72, 100, 11, body_text(30)),
                    PdfText(72, 400, 11, "(cid:1)"),
                ]
            )
        ],
    )
    doc = convert_pdf(path, ConvertOptions(cid_max=1.0))  # router zostawia tryb text
    assert doc.pending_pages == []
    assert doc.stats["pages_text"] == 1
    assert "<p data-bbox" not in doc.html  # fallback: akapity bez bbox
    assert "<p>" in doc.html


def test_metadata_title(tmp_path: Path) -> None:
    path = _write(tmp_path, [PdfPage(texts=[PdfText(72, 100, 11, body_text(30))])], title="Report")
    doc = convert_pdf(path, ConvertOptions())
    assert doc.metadata["title"] == "Report"


def test_pending_page_carries_text_layer_for_good_page(tmp_path: Path) -> None:
    path = _write(tmp_path, [PdfPage(texts=[PdfText(72, 100, 11, body_text(30))])])
    doc = convert_pdf(path, ConvertOptions(pdf_strategy="vision", vision_available=True))
    (pending,) = doc.pending_pages
    assert pending.text_layer != ""
    assert "lorem0" in pending.text_layer


def test_pending_page_text_layer_empty_for_scan(tmp_path: Path) -> None:
    path = _write(tmp_path, [PdfPage()])
    doc = convert_pdf(path, ConvertOptions(ocr_available=True))
    (pending,) = doc.pending_pages
    assert pending.text_layer == ""


def test_pending_page_text_layer_empty_for_mojibake(tmp_path: Path) -> None:
    path = tmp_path / "mojibake.pdf"
    # 20 linii po 8 glifów mojibake (0xAC → "¬"): >= 150 znaków i mojibake_ratio ~1.0,
    # więc router odrzuca stronę i warstwa nie trafia do PendingPage (DEC-248 P1).
    pages = [PdfPage(texts=[PdfText(72, 100 + i * 20, 11, "MOJIBAKE")]) for i in range(20)]
    path.write_bytes(make_pdf(pages).replace(b"(MOJIBAKE)", b"(\xac\xac\xac\xac\xac\xac\xac\xac)"))
    doc = convert_pdf(path, ConvertOptions(pdf_strategy="vision", vision_available=True))
    assert doc.pending_pages
    assert {pending.text_layer for pending in doc.pending_pages} == {""}


def test_convert_pdf_is_picklable() -> None:
    data = pickle.dumps(convert_pdf)
    assert callable(pickle.loads(data))  # noqa: S301 — round-trip własnej funkcji
