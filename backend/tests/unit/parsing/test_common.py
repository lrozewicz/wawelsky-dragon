"""Testy wspólnych narzędzi konwerterów (kontrakt C4)."""

import io
import shutil
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app.parsing.converters.common import check_zip, finish, png_bytes, read_bytes, run_binary
from app.parsing.errors import (
    BinaryMissing,
    CorruptedFile,
    EmptyDocument,
    EncryptedFile,
    LimitExceeded,
)
from app.parsing.types import ConvertOptions, PendingPage


def test_finish_empty_without_pending_raises() -> None:
    with pytest.raises(EmptyDocument) as excinfo:
        finish("", diagnosis="nic tu nie ma")
    assert str(excinfo.value) == "No text could be extracted: nic tu nie ma"


def test_finish_with_pending_returns_document() -> None:
    pending = [PendingPage(page=1, mode="ocr", image_png=b"png", reason="chars<150")]
    doc = finish(
        "",
        diagnosis="d",
        pages=2,
        pending=pending,
        metadata={"title": "T"},
        warnings=["w"],
        stats={"pages_ocr": 7},
    )
    assert doc.html == ""
    assert doc.pages == 2  # noqa: PLR2004 — wartość kontraktowa parametru
    assert doc.pending_pages == pending
    assert doc.metadata == {"title": "T"}
    assert doc.warnings == ["w"]
    assert set(doc.stats) == {"chars", "pages_text", "pages_ocr", "pages_vision"}
    assert doc.stats["chars"] == 0
    assert doc.stats["pages_ocr"] == 7  # noqa: PLR2004 — statystyka z parametru


@pytest.mark.parametrize(
    ("html", "expected_chars"),
    [("<p>a b</p>", 2), ("<p>a</p><p>bc</p>", 3), ("<table><tr><td>x</td></tr></table>", 1)],
)
def test_finish_counts_chars(html: str, expected_chars: int) -> None:
    doc = finish(html, diagnosis="d")
    assert doc.stats["chars"] == expected_chars
    assert doc.pending_pages == []


def test_finish_chars_always_from_computation() -> None:
    doc = finish("<p>x</p>", diagnosis="d", stats={"chars": 99, "pages_text": 2})
    assert doc.stats["chars"] == 1
    assert doc.stats["pages_text"] == 2  # noqa: PLR2004 — statystyka z parametru


def test_finish_sanitizes_html() -> None:
    doc = finish("<p>a<script>x()</script>b</p>", diagnosis="d")
    assert doc.html == "<p>ab</p>"


def test_read_bytes_empty_raises(tmp_path: Path) -> None:
    path = tmp_path / "f.txt"
    path.write_bytes(b"")
    with pytest.raises(EmptyDocument) as excinfo:
        read_bytes(path)
    assert str(excinfo.value) == "No text could be extracted: file is empty"


def test_read_bytes_ok(tmp_path: Path) -> None:
    path = tmp_path / "f.bin"
    path.write_bytes(b"\x00data")
    assert read_bytes(path) == b"\x00data"


def _zip_with(payload: bytes, tmp_path: Path) -> Path:
    path = tmp_path / "f.xlsx"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("a.txt", payload)
    return path


def test_check_zip_cfb_raises_encrypted(tmp_path: Path) -> None:
    path = tmp_path / "f.xlsx"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"rest")
    with pytest.raises(EncryptedFile) as excinfo:
        check_zip(path, "xlsx", ConvertOptions())
    assert str(excinfo.value) == "File is password-protected (.xlsx)"


def test_check_zip_garbage_raises_corrupted(tmp_path: Path) -> None:
    path = tmp_path / "f.docx"
    path.write_bytes(b"definitely not a zip file")
    with pytest.raises(CorruptedFile) as excinfo:
        check_zip(path, "docx", ConvertOptions())
    message = "File is corrupted or unreadable (.docx): not a valid ZIP container"
    assert str(excinfo.value) == message


def test_check_zip_uncompressed_limit(tmp_path: Path) -> None:
    path = _zip_with(b"a" * 10_000, tmp_path)
    with pytest.raises(LimitExceeded) as excinfo:
        check_zip(path, "xlsx", ConvertOptions(max_uncompressed_bytes=100))
    assert str(excinfo.value) == "Limit exceeded: uncompressed bytes 10000 > 100"


def test_check_zip_archive_ratio(tmp_path: Path) -> None:
    path = _zip_with(b"a" * 10_000, tmp_path)
    opts = ConvertOptions(max_uncompressed_bytes=2048 * 1024 * 1024, max_archive_ratio=2)
    with pytest.raises(LimitExceeded) as excinfo:
        check_zip(path, "xlsx", opts)
    assert str(excinfo.value).startswith("Limit exceeded: archive ratio ")
    assert str(excinfo.value).endswith(" > 2")


def test_check_zip_ok(tmp_path: Path) -> None:
    path = _zip_with(b"hello world " * 10, tmp_path)
    assert check_zip(path, "xlsx", ConvertOptions()) is None


def test_run_binary_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(BinaryMissing) as excinfo:
        run_binary("tesseract", ["--version"], fmt="doc")
    assert (
        str(excinfo.value)
        == "Required program 'tesseract' is not installed; use the worker-ocr image"
    )


def test_run_binary_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/catppt")
    proc = SimpleNamespace(returncode=0, stdout=b"OUT", stderr=b"")
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_kw: proc)
    assert run_binary("catppt", ["f.ppt"], fmt="ppt") == b"OUT"


def test_run_binary_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/catppt")
    proc = SimpleNamespace(returncode=1, stdout=b"", stderr=b"boom\n")
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_kw: proc)
    with pytest.raises(CorruptedFile) as excinfo:
        run_binary("catppt", ["f.ppt"], fmt="ppt")
    assert str(excinfo.value) == "File is corrupted or unreadable (.ppt): catppt failed: boom"


def test_run_binary_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/tesseract")

    def raise_timeout(*_a: object, **_kw: object) -> None:
        raise subprocess.TimeoutExpired(cmd="tesseract", timeout=1)

    monkeypatch.setattr(subprocess, "run", raise_timeout)
    with pytest.raises(CorruptedFile) as excinfo:
        run_binary("tesseract", ["f.png"], fmt="pdf")
    assert str(excinfo.value) == "File is corrupted or unreadable (.pdf): tesseract timed out"


@pytest.mark.parametrize("mode", ["RGBA", "P", "L", "RGB"])
def test_png_bytes(mode: str) -> None:
    data = png_bytes(Image.new(mode, (2, 2)))
    assert data.startswith(b"\x89PNG")
    with Image.open(io.BytesIO(data)) as round_trip:
        assert round_trip.format == "PNG"
