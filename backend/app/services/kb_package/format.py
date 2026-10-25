"""Format paczki .wdkb (K19 §2) — stałe, modele manifestu/linii i NPY 1.0 bez numpy."""

from __future__ import annotations

import ast
import re
import struct
from collections.abc import Iterator, Sequence
from typing import Any, BinaryIO

from pydantic import BaseModel, ConfigDict

FORMAT_NAME = "wdkb"
SCHEMA_VERSION = 1
MANIFEST_PATH = "manifest.json"
DOCUMENTS_PATH = "documents.jsonl"
CHUNKS_PATH = "chunks.jsonl"
VECTORS_PREFIX = "vectors/"
FILES_PREFIX = "files/"
IMAGES_PREFIX = "images/"
VECTOR_PART_ROWS = 10_000
MANIFEST_MAX_BYTES = 1_048_576

# Dozwolone ścieżki wpisów paczki (manifest.json obsługuje się osobno).
ENTRY_PATH_RE: re.Pattern[str] = re.compile(
    r"(?:documents\.jsonl|chunks\.jsonl"
    r"|vectors/[0-9]{6}\.npy"
    r"|files/[0-9a-f]{64}|images/[0-9a-f]{64})\Z"
)

# NPY 1.0: magic (6) + wersja (2) + długość nagłówka uint16 LE (2) + nagłówek ASCII.
NPY_MAGIC = b"\x93NUMPY"
NPY_MAJOR = 1
NPY_MINOR = 0
NPY_DESCR = "<f4"
NPY_HEADER_PREFIX = 10
NPY_ALIGNMENT = 64
NPY_ROW_ITEM_SIZE = 4
NPY_VERSION_SIZE = 2
NPY_HEADER_LEN_SIZE = 2
NPY_NDIM = 2
# Zapas cyfr na liczbę wierszy w nagłówku: dzięki stałej szerokości close() przepisuje nagłówek.
_MAX_ROWS_DIGITS = 19

_MISSING = object()


def vector_part_path(k: int) -> str:
    """Ścieżka k-tej części wektorów, np. ``vectors/000003.npy``."""
    return f"{VECTORS_PREFIX}{k:06d}.npy"


def _npy_header_text(rows: int, dimension: int) -> str:
    """Treść nagłówka NPY 1.0 (dict Pythona) bez dopełnienia."""
    return f"{{'descr': '{NPY_DESCR}', 'fortran_order': False, 'shape': ({rows}, {dimension}), }}"


def _reserved_header_len(dimension: int) -> int:
    """Rozmiar nagłówka NPY (bez 10-bajtowego prefiksu) z zapasem na liczbę wierszy."""
    longest = len(_npy_header_text(10**_MAX_ROWS_DIGITS - 1, dimension)) + 1  # + '\n'
    total = -(-(longest + NPY_HEADER_PREFIX) // NPY_ALIGNMENT) * NPY_ALIGNMENT
    return total - NPY_HEADER_PREFIX


def _npy_header_bytes(rows: int, dimension: int, header_len: int) -> bytes:
    """Nagłówek ASCII dopełniony spacjami do ``header_len`` bajtów, zakończony ``\\n``."""
    text = _npy_header_text(rows, dimension)
    padding = header_len - len(text) - 1
    if padding < 0:
        raise ValueError("Zbyt duża liczba wierszy dla nagłówka NPY")
    return text.encode("ascii") + b" " * padding + b"\n"


class ManifestEntry(BaseModel):
    """Wpis manifestu: plik paczki z sumą SHA-256 i rozmiarem."""

    model_config = ConfigDict(extra="ignore")

    path: str
    sha256: str
    size: int


class ManifestDataset(BaseModel):
    """Metadane datasetu w manifeście."""

    model_config = ConfigDict(extra="ignore")

    name: str
    description: str | None
    language: str
    chunk_method: str
    parser_config: dict[str, Any]
    similarity_threshold: float
    vector_similarity_weight: float
    pagerank: int


class ManifestEmbedding(BaseModel):
    """Model embeddingów paczki."""

    model_config = ConfigDict(extra="ignore")

    model_name: str
    dimension: int
    included: bool


class ManifestCounts(BaseModel):
    """Liczniki zawartości paczki."""

    model_config = ConfigDict(extra="ignore")

    documents: int
    chunks: int
    vectors: int


class Manifest(BaseModel):
    """Manifest paczki .wdkb (K19 §2)."""

    model_config = ConfigDict(extra="ignore")

    format: str
    schema_version: int
    wd_version: str
    created_at: str
    source_instance_id: str
    dataset: ManifestDataset
    embedding: ManifestEmbedding
    counts: ManifestCounts
    entries: list[ManifestEntry]


class DocumentLine(BaseModel):
    """Linia ``documents.jsonl`` (K19 §2)."""

    model_config = ConfigDict(extra="ignore")

    ref: str
    name: str
    type: str
    suffix: str
    size: int
    file_sha256: str | None
    chunk_method: str
    parser_config: dict[str, Any]
    meta_fields: dict[str, Any]
    run: str
    progress_msg: str
    token_num: int
    chunk_num: int


class ChunkLine(BaseModel):
    """Linia ``chunks.jsonl`` (K19 §2)."""

    model_config = ConfigDict(extra="ignore")

    ref: str
    document_ref: str
    ordinal: int
    chunk_type: str
    content: str
    content_llm: str | None
    keywords: list[str]
    questions: list[str]
    # Kształt zależy od źródła (K19 §2 nie precyzuje typu): kolumna ``chunks.tags`` to JSON-lista
    # (DDL-default ``'[]'``), a RAGFlow-owe ``tag_feas`` bywają obiektem (T12, DEC-341).
    tags: list[Any] | dict[str, Any]
    positions: Any
    page_from: int | None
    page_to: int | None
    image_sha256: str | None
    parent_ref: str | None
    available: bool
    embed_source: str | None
    token_count: int


class NpyWriter:
    """Strumieniowy zapis macierzy float32 (NPY 1.0) do pliku seekable.

    Nagłówek z liczbą wierszy jest zapisywany w ``__init__`` (z zerową liczbą
    wierszy, z zapasem miejsca) i przepisywany w ``close()`` — rozmiar nagłówka
    nie zmienia się, bo pole liczby wierszy ma stałą szerokość.
    """

    def __init__(self, fp: BinaryIO, dimension: int) -> None:
        if dimension <= 0:
            raise ValueError("Wymiar wektora musi być dodatni")
        self._fp = fp
        self._dimension = dimension
        self._rows = 0
        self._header_len = _reserved_header_len(dimension)
        self._rewrite_header()

    def _rewrite_header(self) -> None:
        """Zapisuje nagłówek na początku pliku (przepisuje poprzedni)."""
        self._fp.seek(0)
        self._fp.write(NPY_MAGIC)
        self._fp.write(bytes((NPY_MAJOR, NPY_MINOR)))
        self._fp.write(struct.pack("<H", self._header_len))
        self._fp.write(_npy_header_bytes(self._rows, self._dimension, self._header_len))

    def write_rows(self, rows: Sequence[Sequence[float]]) -> None:
        """Dopisuje wiersze po nagłówku; wiersz o złej długości to ``ValueError``."""
        for row in rows:
            if len(row) != self._dimension:
                raise ValueError(f"Wiersz ma {len(row)} kolumn, oczekiwano {self._dimension}")
        payload = b"".join(struct.pack(f"<{self._dimension}f", *row) for row in rows)
        self._fp.write(payload)
        self._rows += len(rows)

    def close(self) -> int:
        """Przepisuje nagłówek z prawdziwą liczbą wierszy; zwraca tę liczbę."""
        self._rewrite_header()
        self._fp.flush()
        return self._rows


def write_npy(fp: BinaryIO, rows: Sequence[Sequence[float]], dimension: int) -> None:
    """Zapisuje całą macierz ``rows`` (kształt ``(n, dimension)``) jako NPY 1.0."""
    writer = NpyWriter(fp, dimension)
    writer.write_rows(rows)
    writer.close()


def read_npy_header(fp: BinaryIO) -> tuple[int, int]:
    """Czyta nagłówek NPY 1.0 i zwraca ``(wiersze, kolumny)``; zły plik to ``ValueError``."""
    if fp.read(len(NPY_MAGIC)) != NPY_MAGIC:
        raise ValueError("To nie jest plik NPY (niepoprawny magic)")
    version = fp.read(NPY_VERSION_SIZE)
    if version != bytes((NPY_MAJOR, NPY_MINOR)):
        raise ValueError(f"Nieobsługiwana wersja NPY: {version!r} (oczekiwano 1.0)")
    raw_len = fp.read(NPY_HEADER_LEN_SIZE)
    if len(raw_len) != NPY_HEADER_LEN_SIZE:
        raise ValueError("Obcięty nagłówek NPY")
    (header_len,) = struct.unpack("<H", raw_len)
    raw_header = fp.read(header_len)
    if len(raw_header) != header_len:
        raise ValueError("Obcięty nagłówek NPY")
    header = _parse_header(raw_header)
    rows, cols = header["shape"]
    return rows, cols


def _parse_header(raw_header: bytes) -> dict[str, Any]:
    """Parsuje i waliduje nagłówek NPY (descr, fortran_order, kształt 2D)."""
    try:
        header = ast.literal_eval(raw_header.decode("ascii"))
    except (SyntaxError, ValueError) as exc:
        raise ValueError("Niepoprawny nagłówek NPY") from exc
    if not isinstance(header, dict):
        raise ValueError("Niepoprawny nagłówek NPY")
    if header.get("descr") != NPY_DESCR:
        raise ValueError(f"Nieobsługiwany descr NPY: {header.get('descr')!r}")
    if header.get("fortran_order") is not False:
        raise ValueError("Nieobsługiwany fortran_order w NPY")
    shape = header.get("shape", _MISSING)
    if not isinstance(shape, tuple) or len(shape) != NPY_NDIM:
        raise ValueError(f"Kształt NPY musi być 2-wymiarowy, jest {shape!r}")
    if not all(isinstance(size, int) for size in shape):
        raise ValueError(f"Kształt NPY musi mieć całkowite wymiary, jest {shape!r}")
    return header


def read_npy(fp: BinaryIO) -> Iterator[list[float]]:
    """Czyta macierz NPY strumieniowo, wiersz po wierszu."""
    rows, dimension = read_npy_header(fp)
    row_bytes = dimension * NPY_ROW_ITEM_SIZE
    fmt = f"<{dimension}f"
    for _ in range(rows):
        raw = fp.read(row_bytes)
        if len(raw) != row_bytes:
            raise ValueError("Obcięte dane macierzy NPY")
        yield list(struct.unpack(fmt, raw))
