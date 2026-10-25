"""Wspólne narzędzia konwerterów (kontrakt C4) — zamykanie konwersji, ZIP, binarki, PNG."""

from __future__ import annotations

import io
import shutil
import subprocess
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from PIL import Image

from app.parsing.errors import (
    binary_missing,
    corrupted_file,
    empty_document,
    encrypted_file,
    limit_exceeded,
)
from app.parsing.html import sanitize_html, text_chars
from app.parsing.types import ConvertedDocument, ConvertOptions, PendingPage

_CFB_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # CFB/OLE — zaszyfrowany OOXML
_BASE_STATS = {"chars": 0, "pages_text": 0, "pages_ocr": 0, "pages_vision": 0}


def finish(  # noqa: PLR0913 — sygnatura z kontraktu C4, nie wolno jej zmieniać
    html: str,
    *,
    diagnosis: str,
    pages: int | None = None,
    pending: Sequence[PendingPage] = (),
    metadata: Mapping[str, str] | None = None,
    warnings: Sequence[str] = (),
    stats: Mapping[str, int] | None = None,
) -> ConvertedDocument:
    """Zamyka konwersję: sanityzacja, licznik znaków, EmptyDocument przy pustym wyniku."""
    clean = sanitize_html(html)
    chars = text_chars(clean)
    if chars == 0 and not pending:
        raise empty_document(diagnosis)
    result = _BASE_STATS | dict(stats or {})
    result["chars"] = chars  # licznik zawsze z obliczenia, nie z podanych statystyk
    return ConvertedDocument(
        clean, pages, list(pending), dict(metadata or {}), list(warnings), result
    )


def read_bytes(path: Path) -> bytes:
    """Odczyt pliku; plik 0 B to od razu pusty dokument."""
    data = path.read_bytes()
    if not data:
        raise empty_document("file is empty")
    return data


def check_zip(path: Path, fmt: str, opts: ConvertOptions) -> None:
    """Bramki przed otwarciem kontenera ZIP: szyfrowanie CFB, uszkodzony plik, zip-bomb."""
    with path.open("rb") as f:
        if f.read(len(_CFB_MAGIC)) == _CFB_MAGIC:
            raise encrypted_file(fmt)
    try:
        with zipfile.ZipFile(path) as zf:
            total = sum(info.file_size for info in zf.infolist())
    except zipfile.BadZipFile:
        raise corrupted_file(fmt, "not a valid ZIP container") from None
    if total > opts.max_uncompressed_bytes:
        raise limit_exceeded("uncompressed bytes", total, opts.max_uncompressed_bytes)
    ratio = total // max(1, path.stat().st_size)
    if ratio > opts.max_archive_ratio:
        raise limit_exceeded("archive ratio", ratio, opts.max_archive_ratio)


def run_binary(binary: str, args: Sequence[str], *, fmt: str, timeout_s: float = 120.0) -> bytes:
    """Uruchamia program zewnętrzny (lista argumentów, bez powłoki) i zwraca stdout."""
    if shutil.which(binary) is None:
        raise binary_missing(binary)
    try:
        proc = subprocess.run([binary, *args], capture_output=True, timeout=timeout_s, check=False)  # noqa: S603 — lista argumentów bez powłoki, binarka z self-check
    except subprocess.TimeoutExpired:
        raise corrupted_file(fmt, f"{binary} timed out") from None
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()[:200]
        raise corrupted_file(fmt, f"{binary} failed: {stderr}")
    return proc.stdout


def png_bytes(image: Image.Image) -> bytes:
    """Serializuje obraz do PNG; tryby inne niż RGB/L konwertuje do RGB."""
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
