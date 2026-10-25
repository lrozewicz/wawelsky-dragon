"""Testy plików negatywnych przez pełną ścieżkę detect_format + convert (T8, C9, 05 §9.1)."""

import io
import re
from pathlib import Path

import pytest
from docx import Document

from app.parsing.errors import CorruptedFile, EmptyDocument, EncryptedFile, UnsupportedFormat
from app.parsing.registry import convert, detect_format
from app.parsing.types import ConvertOptions
from tests.unit.parsing.factories import PdfPage, make_pdf

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "parsing"


def _docx_bytes() -> bytes:
    document = Document()
    document.add_paragraph("Zażółć gęślą jaźń")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


# tabela negatywna C9: (nazwa pliku, zawartość, oczekiwana klasa, prefiks komunikatu z fabryk C2)
_CASES = [
    pytest.param(
        "empty.pdf",
        make_pdf([PdfPage()]),
        EmptyDocument,
        "No text could be extracted: ",
        id="empty.pdf",
    ),
    pytest.param(
        "zero_bytes.txt",
        b"",
        EmptyDocument,
        "No text could be extracted: ",
        id="zero_bytes.txt",
    ),
    pytest.param(
        "corrupted.docx",
        _docx_bytes()[:200],
        CorruptedFile,
        "File is corrupted or unreadable (",
        id="corrupted.docx",
    ),
    pytest.param(
        "wrong_extension.pdf",
        b"hello world, not a pdf",
        CorruptedFile,
        "File is corrupted or unreadable (",
        id="wrong_extension.pdf",
    ),
    pytest.param(
        "unsupported.bin",
        bytes(range(256)) * 4,
        UnsupportedFormat,
        "Unsupported file format: ",
        id="unsupported.bin",
    ),
]


@pytest.mark.parametrize(("filename", "content", "expected", "prefix"), _CASES)
def test_negative_row(
    filename: str, content: bytes, expected: type[Exception], prefix: str, tmp_path: Path
) -> None:
    path = tmp_path / filename
    path.write_bytes(content)
    # błąd może paść już w detect_format (wrong_extension.pdf, unsupported.bin) albo w convert
    with pytest.raises(expected, match=re.escape(prefix)):
        convert(path, detect_format(path, path.suffix), ConvertOptions())


def test_encrypted_pdf_fixture() -> None:
    path = FIXTURES / "encrypted.pdf"
    with pytest.raises(EncryptedFile):
        convert(path, detect_format(path, path.suffix), ConvertOptions())
