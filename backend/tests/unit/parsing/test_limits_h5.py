"""Testy limitów H5 (kontrakt T2) — bomba ZIP i limit stron przez realne konwertery.

Pozycja #24 (docs/architecture/10-testy-jakosc.md): XLSX „zip bomb-like" musi zostać
odrzucony przez `check_zip`, zanim parser XML zacznie pracę. `registry.convert` to jedyne
wejście konwersji, więc testy idą przez nie (nie przez sam `check_zip`).
"""

import zipfile
from pathlib import Path

import pytest

from app.parsing import registry
from app.parsing.errors import LimitExceeded
from app.parsing.types import ConvertOptions
from tests.unit.parsing.factories import PdfPage, PdfText, make_pdf

_BOMB_BYTES = 20 * 1024 * 1024  # ~20 MB powtarzalnych znaków (pozycja #24)
_MIB = 1024 * 1024
_MAX_BOMB_FILE = 100_000  # bomba na dysku musi być mała (silna kompresja)


def _bomb_zip(tmp_path: Path, name: str, members: dict[str, bytes]) -> Path:
    """Zapisuje silnie skompresowany ZIP z podanymi członami (ZIP_DEFLATED)."""
    path = tmp_path / name
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for member, payload in members.items():
            zf.writestr(member, payload)
    return path


def _bomb_xlsx(tmp_path: Path) -> Path:
    """XLSX-bomba: [Content_Types].xml + arkusz z ~20 MB powtarzalnego znaku."""
    return _bomb_zip(
        tmp_path,
        "bomba.xlsx",
        {
            "[Content_Types].xml": b"<Types/>",
            "xl/workbook.xml": b"<workbook/>",
            "xl/worksheets/sheet1.xml": b"A" * _BOMB_BYTES,
        },
    )


def test_xlsx_bomb_uncompressed_limit(tmp_path: Path) -> None:
    """Bomba 20 MB przy limicie 1 MiB → LimitExceeded, plik na dysku < 100 kB."""
    path = _bomb_xlsx(tmp_path)
    assert path.stat().st_size < _MAX_BOMB_FILE
    with pytest.raises(LimitExceeded) as excinfo:
        registry.convert(path, "xlsx", ConvertOptions(max_uncompressed_bytes=_MIB))
    assert "uncompressed bytes" in str(excinfo.value)


def test_xlsx_bomb_archive_ratio(tmp_path: Path) -> None:
    """Bomba przy dużym limicie bajtów i max_archive_ratio=10 → LimitExceeded."""
    path = _bomb_xlsx(tmp_path)
    opts = ConvertOptions(max_uncompressed_bytes=2048 * _MIB, max_archive_ratio=10)
    with pytest.raises(LimitExceeded) as excinfo:
        registry.convert(path, "xlsx", opts)
    assert "archive ratio" in str(excinfo.value)
    assert str(excinfo.value).endswith(" > 10")


@pytest.mark.parametrize(
    ("fmt", "member", "filename"),
    [
        ("docx", "word/document.xml", "bomba.docx"),
        ("pptx", "ppt/presentation.xml", "bomba.pptx"),
    ],
)
def test_ooxml_bomb_limited_before_parsing(
    tmp_path: Path, fmt: str, member: str, filename: str
) -> None:
    """DOCX/PPTX-bomba odrzucone przez limit, zanim parser XML zacznie pracę."""
    path = _bomb_zip(tmp_path, filename, {member: b"B" * _BOMB_BYTES})
    with pytest.raises(LimitExceeded):
        registry.convert(path, fmt, ConvertOptions(max_uncompressed_bytes=_MIB))


def test_pdf_page_limit(tmp_path: Path) -> None:
    """PDF 3-stronicowy przy max_pages=2 → LimitExceeded z „pages 3 > 2"."""
    path = tmp_path / "trzy.pdf"
    page = PdfPage(texts=[PdfText(x=50, top=50, size=12, text="strona testowa")])
    path.write_bytes(make_pdf([page] * 3))
    with pytest.raises(LimitExceeded) as excinfo:
        registry.convert(path, "pdf", ConvertOptions(max_pages=2))
    assert str(excinfo.value) == "Limit exceeded: pages 3 > 2"
