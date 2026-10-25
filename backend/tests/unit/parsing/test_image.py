"""Testy konwertera obrazów (T7, kontrakt C8)."""

import dataclasses
import io
from pathlib import Path

import pytest
from PIL import Image

from app.parsing.converters.image import convert_image
from app.parsing.errors import BinaryMissing, CorruptedFile, LimitExceeded
from app.parsing.types import ConvertOptions


def _png(tmp_path: Path, size: tuple[int, int] = (20, 20)) -> Path:
    path = tmp_path / "img.png"
    Image.new("RGB", size, "red").save(path)
    return path


def _tiff(tmp_path: Path, pages: int) -> Path:
    path = tmp_path / "multi.tiff"
    first = Image.new("RGB", (10, 10), "red")
    rest = [Image.new("RGB", (10, 10), "green") for _ in range(pages - 1)]
    first.save(path, save_all=True, append_images=rest)
    return path


def test_png_vision_pending(tmp_path: Path) -> None:
    doc = convert_image(_png(tmp_path), ConvertOptions(vision_available=True))
    (page,) = doc.pending_pages
    assert page.mode == "vision"
    assert page.page == 1
    assert page.reason == "image"
    assert page.image_png.startswith(b"\x89PNG")
    assert '<section data-page="1"></section>' in doc.html
    assert doc.pages == 1
    assert doc.stats["pages_ocr"] == 0
    assert doc.stats["pages_vision"] == 0


def test_png_ocr_mode(tmp_path: Path) -> None:
    doc = convert_image(_png(tmp_path), ConvertOptions(ocr_available=True))
    (page,) = doc.pending_pages
    assert page.mode == "ocr"
    assert page.reason == "image"


def test_png_without_recognizers_raises(tmp_path: Path) -> None:
    with pytest.raises(BinaryMissing) as excinfo:
        convert_image(_png(tmp_path), ConvertOptions())
    assert excinfo.value.details["binary"] == "tesseract"


def test_tiff_three_pages(tmp_path: Path) -> None:
    doc = convert_image(_tiff(tmp_path, 3), ConvertOptions(ocr_available=True))
    assert doc.pages == 3  # noqa: PLR2004 — liczba stron z kontraktu
    assert [p.page for p in doc.pending_pages] == [1, 2, 3]
    assert [p.mode for p in doc.pending_pages] == ["ocr", "ocr", "ocr"]
    for n in (1, 2, 3):
        assert f'<section data-page="{n}"></section>' in doc.html


def test_tiff_max_pages_exceeded(tmp_path: Path) -> None:
    opts = dataclasses.replace(ConvertOptions(), max_pages=2, ocr_available=True)
    with pytest.raises(LimitExceeded) as excinfo:
        convert_image(_tiff(tmp_path, 3), opts)
    assert "pages 3 > 2" in str(excinfo.value)


def test_jpeg_cmyk_becomes_valid_png(tmp_path: Path) -> None:
    path = tmp_path / "img.jpg"
    Image.new("CMYK", (10, 10)).save(path)
    doc = convert_image(path, ConvertOptions(vision_available=True))
    image = Image.open(io.BytesIO(doc.pending_pages[0].image_png))
    assert image.format == "PNG"
    assert image.mode == "RGB"


def test_garbage_png_corrupted(tmp_path: Path) -> None:
    path = tmp_path / "junk.png"
    path.write_bytes(b"to nie jest obraz")
    with pytest.raises(CorruptedFile) as excinfo:
        convert_image(path, ConvertOptions(ocr_available=True))
    assert excinfo.value.details["format"] == "png"
    assert excinfo.value.details["reason"] == "not a valid image"


def test_decompression_bomb_raises_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args: object, **kwargs: object) -> Image.Image:
        raise Image.DecompressionBombError("bomb")

    monkeypatch.setattr(Image, "open", _boom)
    with pytest.raises(LimitExceeded) as excinfo:
        convert_image(_png(tmp_path), ConvertOptions(ocr_available=True))
    assert excinfo.value.details["what"] == "image pixels"
