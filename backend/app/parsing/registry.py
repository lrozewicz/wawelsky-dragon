"""Rejestr formatów (kontrakt C9, K5 §4.2) — wykrywanie po magic bytes i jedno wejście konwersji."""

from __future__ import annotations

import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.parsing.converters.doc import convert_doc
from app.parsing.converters.docx import convert_docx
from app.parsing.converters.eml import convert_eml
from app.parsing.converters.html_in import convert_html
from app.parsing.converters.image import convert_image
from app.parsing.converters.json_in import convert_json, convert_jsonl
from app.parsing.converters.markdown import convert_markdown
from app.parsing.converters.pdf import convert_pdf
from app.parsing.converters.pptx import convert_ppt, convert_pptx
from app.parsing.converters.sheets import convert_csv, convert_tsv, convert_xls, convert_xlsx
from app.parsing.converters.text import convert_code, convert_text
from app.parsing.errors import ConversionFailed, corrupted_file, unsupported_format
from app.parsing.types import ConvertedDocument, ConvertOptions

_CFB_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # sygnatura CFB/OLE
_HEADER_BYTES = 8192  # tyle nagłówka czyta detect_format

# klucze, których brak magic oznacza uszkodzenie pliku (krok 3 C9)
_BINARY_FORMATS = frozenset(
    {
        "pdf",
        "docx",
        "doc",
        "xlsx",
        "xlsm",
        "xls",
        "pptx",
        "ppt",
        "png",
        "jpg",
        "webp",
        "tiff",
        "bmp",
    }
)


@dataclass(frozen=True)
class ConverterSpec:
    """Jeden konwerter formatu: nazwa `klucz.biblioteka`, aliasy rozszerzeń, funkcja."""

    name: str
    extensions: tuple[str, ...]
    fn: Callable[[Path, ConvertOptions], ConvertedDocument]
    needs_binaries: tuple[str, ...] = ()


# klucz formatu → lista konwerterów (pierwszy = domyślny); kolejność kluczy wg C9
REGISTRY: dict[str, list[ConverterSpec]] = {
    "pdf": [ConverterSpec("pdf.pdfplumber", ("pdf",), convert_pdf)],
    "docx": [ConverterSpec("docx.mammoth", ("docx",), convert_docx)],
    "doc": [ConverterSpec("doc.wvhtml", ("doc",), convert_doc, ("wvHtml",))],
    "xlsx": [ConverterSpec("xlsx.openpyxl", ("xlsx",), convert_xlsx)],
    "xlsm": [ConverterSpec("xlsm.openpyxl", ("xlsm",), convert_xlsx)],
    "xls": [ConverterSpec("xls.xlrd", ("xls",), convert_xls)],
    "csv": [ConverterSpec("csv.stdlib", ("csv",), convert_csv)],
    "tsv": [ConverterSpec("tsv.stdlib", ("tsv",), convert_tsv)],
    "pptx": [ConverterSpec("pptx.python-pptx", ("pptx",), convert_pptx)],
    "ppt": [ConverterSpec("ppt.catppt", ("ppt",), convert_ppt, ("catppt",))],
    "md": [ConverterSpec("md.markdown-it", ("md", "markdown"), convert_markdown)],
    "html": [ConverterSpec("html.bs4", ("html", "htm"), convert_html)],
    "txt": [ConverterSpec("txt.stdlib", ("txt", "text"), convert_text)],
    "code": [
        ConverterSpec(
            "code.stdlib",
            (
                "py",
                "js",
                "ts",
                "java",
                "c",
                "h",
                "cpp",
                "hpp",
                "cs",
                "go",
                "rs",
                "rb",
                "php",
                "sql",
                "sh",
                "yaml",
                "yml",
                "xml",
                "toml",
                "ini",
                "cfg",
                "log",
                "rst",
            ),
            convert_code,
        )
    ],
    "json": [ConverterSpec("json.stdlib", ("json",), convert_json)],
    "jsonl": [ConverterSpec("jsonl.stdlib", ("jsonl", "ndjson"), convert_jsonl)],
    "eml": [ConverterSpec("eml.stdlib", ("eml",), convert_eml)],
    "png": [ConverterSpec("png.pillow", ("png",), convert_image)],
    "jpg": [ConverterSpec("jpg.pillow", ("jpg", "jpeg"), convert_image)],
    "webp": [ConverterSpec("webp.pillow", ("webp",), convert_image)],
    "tiff": [ConverterSpec("tiff.pillow", ("tif", "tiff"), convert_image)],
    "bmp": [ConverterSpec("bmp.pillow", ("bmp",), convert_image)],
}

# rozszerzenie (alias) → klucz formatu, wyprowadzony z `extensions`
EXTENSION_ALIASES: dict[str, str] = {
    ext: key for key, specs in REGISTRY.items() for ext in specs[0].extensions
}


def detect_format(  # noqa: PLR0911, PLR0912 — kolejność kroków narzucona kontraktem C9
    path: Path, declared_ext: str
) -> str:
    """Rozpoznaje format: plik 0 B → rozszerzenie; potem magic bytes; na końcu rozszerzenie."""
    ext = declared_ext.lower().lstrip(".")
    key = EXTENSION_ALIASES.get(ext)
    with path.open("rb") as handle:
        head = handle.read(_HEADER_BYTES)
    if not head:  # krok 1: plik 0 B
        if key is None:
            raise unsupported_format(f".{ext}")
        return key
    # krok 2: magic bytes, w kolejności z C9
    if b"%PDF-" in head[:1024]:
        return "pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if head[:2] == b"BM" and key == "bmp":
        return "bmp"
    if head[:4] == b"PK\x03\x04":
        return _detect_zip(path, ext, key)
    if head[:8] == _CFB_MAGIC:
        if key in ("doc", "xls", "ppt", "docx", "xlsx", "xlsm", "pptx"):
            return key  # OOXML w CFB = zaszyfrowany → konwerter zgłosi EncryptedFile
        raise unsupported_format("OLE compound file")
    # krok 3: brak magic
    if key in _BINARY_FORMATS:
        raise corrupted_file(ext, "file content does not match its extension")
    if key is not None:
        return key
    raise unsupported_format(f".{ext}")


def _detect_zip(path: Path, ext: str, key: str | None) -> str:
    """Kontener ZIP: OOXML po zawartości, inny ZIP i uszkodzony wg rozszerzenia."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
    except zipfile.BadZipFile:
        if key in ("docx", "xlsx", "xlsm", "pptx"):
            return key  # konwerter zgłosi CorruptedFile
        raise unsupported_format(f".{ext}") from None
    if "word/document.xml" in names:
        return "docx"
    if "xl/workbook.xml" in names:
        if ext == "xlsm" or "xl/vbaProject.bin" in names:
            return "xlsm"
        return "xlsx"
    if "ppt/presentation.xml" in names:
        return "pptx"
    raise unsupported_format("ZIP archive")


def convert(path: Path, fmt: str, opts: ConvertOptions) -> ConvertedDocument:
    """Jedyne wejście konwersji: domyślny konwerter formatu z opakowaniem błędów obcych."""
    if fmt not in REGISTRY:
        raise unsupported_format(fmt)
    try:
        return REGISTRY[fmt][0].fn(path, opts)
    except ConversionFailed:
        raise
    except Exception as exc:  # jedyne szerokie łapanie w module (kontrakt C9)
        raise corrupted_file(fmt, type(exc).__name__) from exc


def supported_formats() -> frozenset[str]:
    """Klucze formatów dostępnych w rejestrze."""
    return frozenset(REGISTRY)
