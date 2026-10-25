"""Testy app.services.ingest_convert — opcje z parser_config i konwersja w puli (brief T6)."""

import io
from concurrent.futures import ProcessPoolExecutor

import pytest
from PIL import Image

from app.core.config import Settings
from app.llm.tokens import count_tokens
from app.parsing.errors import UnsupportedFormat
from app.parsing.types import ConvertedDocument, ConvertOptions, PendingPage
from app.services.ingest_convert import (
    chunk_config,
    convert_document,
    convert_options,
    tesseract_available,
)

_TXT = "Ala ma kota.\n"  # treść testowa pliku .txt


def test_convert_options_defaults():
    opts = convert_options(
        {}, Settings(env="test"), layout_vision=False, vision_available=False, ocr_available=False
    )
    assert opts.pdf_strategy == "auto"
    assert opts.pages == ((1, 1000000),)
    assert opts.ocr_langs == "pol+eng"
    assert opts.max_uncompressed_bytes == 2048 * 1024 * 1024


def test_convert_options_plain_text_is_fast():
    opts = convert_options(
        {"layout_recognize": "Plain Text"},
        Settings(env="test"),
        layout_vision=False,
        vision_available=False,
        ocr_available=False,
    )
    assert opts.pdf_strategy == "fast"


@pytest.mark.parametrize("layout_recognize", ["DeepDOC", "fake-vision"])
def test_convert_options_unknown_is_auto(layout_recognize):
    opts = convert_options(
        {"layout_recognize": layout_recognize},
        Settings(env="test"),
        layout_vision=False,
        vision_available=False,
        ocr_available=False,
    )
    assert opts.pdf_strategy == "auto"


def test_convert_options_layout_vision_wins():
    opts = convert_options(
        {"layout_recognize": "fake-vision"},
        Settings(env="test"),
        layout_vision=True,
        vision_available=False,
        ocr_available=False,
    )
    assert opts.pdf_strategy == "vision"


def test_convert_options_pages():
    opts = convert_options(
        {"pages": [[2, 5], [7, 7]]},
        Settings(env="test"),
        layout_vision=False,
        vision_available=False,
        ocr_available=False,
    )
    assert opts.pages == ((2, 5), (7, 7))


def test_convert_options_recognizer_flags():
    opts = convert_options(
        {}, Settings(env="test"), layout_vision=False, vision_available=True, ocr_available=True
    )
    assert opts.vision_available is True
    assert opts.ocr_available is True
    assert opts.max_archive_ratio == 100  # noqa: PLR2004 — wartość domyślna z C6/ustawień


def test_chunk_config_fields():
    cfg = chunk_config(
        {"chunk_token_num": 128, "delimiter": "\n!?", "overlapped_percent": 10, "html4excel": True}
    )
    assert cfg.chunk_token_num == 128  # noqa: PLR2004 — wartości dosłownie z briefu T6
    assert cfg.delimiter == "\n!?"
    assert cfg.overlapped_percent == 10  # noqa: PLR2004 — wartości dosłownie z briefu T6
    assert cfg.html4excel is True
    assert cfg.count_tokens is count_tokens
    assert cfg.table_column_mode == "auto"


def test_chunk_config_none_as_missing():
    cfg = chunk_config(
        {"chunk_token_num": None, "table_column_roles": None, "table_column_mode": None}
    )
    assert cfg.chunk_token_num == 512  # noqa: PLR2004 — domyślny token_num z kontraktu
    assert cfg.table_column_roles == {}
    assert cfg.table_column_mode == "auto"


def test_chunk_config_table_roles():
    cfg = chunk_config({"table_column_roles": {"a": "indexing"}, "table_column_mode": "manual"})
    assert cfg.table_column_roles == {"a": "indexing"}
    assert cfg.table_column_mode == "manual"


async def test_convert_document_txt(tmp_path):
    path = tmp_path / "a.txt"
    path.write_bytes(_TXT.encode("utf-8"))
    doc = await convert_document(
        path, "txt", ConvertOptions(), executor=None, ocr=None, vision=None
    )
    assert "Ala ma kota." in doc.html


async def test_convert_document_process_pool(tmp_path):
    path = tmp_path / "a.txt"
    path.write_bytes(_TXT.encode("utf-8"))
    with ProcessPoolExecutor(max_workers=1) as pool:
        doc = await convert_document(
            path, "txt", ConvertOptions(), executor=pool, ocr=None, vision=None
        )
    assert "Ala ma kota." in doc.html


async def test_convert_document_unsupported_format(tmp_path):
    path = tmp_path / "x.bin"
    path.write_bytes(b"\x00\x01\x02")
    with pytest.raises(UnsupportedFormat):
        await convert_document(path, "bin", ConvertOptions(), executor=None, ocr=None, vision=None)


def _small_png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buffer, format="PNG")
    return buffer.getvalue()


class FakeRecognizer:
    """Atrapa rozpoznawacza: zwraca stały fragment HTML."""

    name = "fake"

    async def recognize(
        self, image_png: bytes, *, page: int, hint: str | None = None, use_cache: bool = True
    ) -> str:
        return "<p>OCR tekst</p>"


async def test_convert_document_completes_pending(tmp_path, monkeypatch):
    path = tmp_path / "a.txt"
    path.write_bytes(_TXT.encode("utf-8"))
    pending = PendingPage(page=1, mode="ocr", image_png=_small_png(), reason="chars<150")

    def fake_convert(path, fmt, opts):
        return ConvertedDocument(
            '<section data-page="1"></section>',
            pages=1,
            pending_pages=[pending],
            metadata={},
            warnings=[],
            stats={},
        )

    monkeypatch.setattr("app.services.ingest_convert.convert", fake_convert)
    doc = await convert_document(
        path, "txt", ConvertOptions(), executor=None, ocr=FakeRecognizer(), vision=None
    )
    assert "OCR tekst" in doc.html
    assert doc.pending_pages == []


def test_tesseract_available_cached(monkeypatch):
    tesseract_available.cache_clear()
    calls = []

    def fake_self_check():
        calls.append(1)
        return {"tesseract": True}

    monkeypatch.setattr("app.services.ingest_convert.self_check", fake_self_check)
    assert tesseract_available() is True
    assert tesseract_available() is True
    assert len(calls) == 1  # drugie wywołanie z cache, self_check nie wołany ponownie
    monkeypatch.setattr("app.services.ingest_convert.self_check", lambda: {"tesseract": False})
    tesseract_available.cache_clear()
    assert tesseract_available() is False
    tesseract_available.cache_clear()
