"""Kategorie walidacji paczki .wdkb: zgodność wpisów z manifestem i spójność wektorów.

Moduł-liść (nie importuje ``validate.py``): wspólne typy wyniku walidacji, kody błędów (K19 §3)
oraz kroki 6-7 z K19 §5. Orkiestracja i kontrole bezpieczeństwa ścieżek są w ``validate.py``.
"""

from __future__ import annotations

import hashlib
import math
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, cast

from app.services.kb_package.format import (
    CHUNKS_PATH,
    DOCUMENTS_PATH,
    MANIFEST_PATH,
    VECTOR_PART_ROWS,
    VECTORS_PREFIX,
    Manifest,
    read_npy_header,
)

INVALID_ARCHIVE = "invalid_archive"
MANIFEST_INVALID = "manifest_invalid"
SCHEMA_TOO_NEW = "schema_too_new"
UNSAFE_PATH = "unsafe_path"
ARCHIVE_TOO_LARGE = "archive_too_large"
CHECKSUM_MISMATCH = "checksum_mismatch"
MISSING_ENTRY = "missing_entry"
UNEXPECTED_ENTRY = "unexpected_entry"
DIMENSION_MISMATCH = "dimension_mismatch"
# K20 §2: archiwum bez manifestu to nie paczka .wdkb (zastępuje missing_entry dla manifestu).
NOT_A_PACKAGE = "not_a_package"

READ_BLOCK = 1_048_576  # blok czytania strumieniowego i próg kontroli współczynnika kompresji
NAME_MAX_CHARS = 200  # długość nazwy wpisu w komunikacie (bezpieczne obcięcie)


@dataclass(frozen=True)
class PackageError:
    """Błąd walidacji paczki: kod (K19 §3) i komunikat po polsku."""

    code: str
    message: str


@dataclass(frozen=True)
class ValidatedPackage:
    """Poprawna paczka: ścieżka pliku i sparsowany manifest."""

    path: Path
    manifest: Manifest


def safe_entry_name(name: str) -> str:
    """Nazwa wpisu bezpieczna do komunikatu: bez znaków sterujących i obcięta do 200 znaków."""
    return "".join(ch for ch in name if ch.isprintable())[:NAME_MAX_CHARS]


# --- krok 6: zgodność wpisów z manifestem --------------------------------------------------


def _hash_entry(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo, *, limit: int
) -> tuple[str, int] | None:
    """SHA-256 i rozmiar wpisu czytanego strumieniowo; ``None``, gdy danych jest ponad ``limit``.

    Nagłówek ZIP może kłamać — faktycznie odczytane bajty nie mogą przekroczyć deklaracji.
    """
    digest = hashlib.sha256()
    read = 0
    with archive.open(info) as fp:
        while True:
            block = fp.read(READ_BLOCK)
            if not block:
                break
            read += len(block)
            if read > limit:
                return None
            digest.update(block)
    return digest.hexdigest(), read


def check_entries_against_manifest(  # noqa: PLR0911 — każdy naruszony warunek kończy krok
    archive: zipfile.ZipFile, manifest: Manifest
) -> list[PackageError]:
    """Krok 6: obecność wpisów z manifestu, brak nadmiarowych, SHA-256 i rozmiar."""
    by_name = {info.filename: info for info in archive.infolist()}
    paths = [entry.path for entry in manifest.entries]
    if len(set(paths)) != len(paths):
        return [PackageError(MANIFEST_INVALID, "Manifest zawiera zduplikowane ścieżki wpisów")]
    listed = set(paths)
    for entry in manifest.entries:
        if entry.path not in by_name:
            return [
                PackageError(
                    MISSING_ENTRY, f"W paczce brakuje wpisu „{safe_entry_name(entry.path)}”"
                )
            ]
    for info in archive.infolist():
        if info.filename != MANIFEST_PATH and info.filename not in listed:
            return [
                PackageError(
                    UNEXPECTED_ENTRY,
                    f"Wpis „{safe_entry_name(info.filename)}” nie występuje w manifeście",
                )
            ]
    for entry in manifest.entries:
        info = by_name[entry.path]
        result = _hash_entry(archive, info, limit=max(info.file_size, entry.size))
        if result is None:
            return [
                PackageError(
                    ARCHIVE_TOO_LARGE,
                    f"Wpis „{safe_entry_name(entry.path)}” ma więcej danych,"
                    " niż deklaruje nagłówek",
                )
            ]
        sha256, size = result
        if size != entry.size:
            return [
                PackageError(
                    CHECKSUM_MISMATCH,
                    f"Rozmiar wpisu „{safe_entry_name(entry.path)}” ({size} B) niezgodny"
                    f" z manifestem ({entry.size} B)",
                )
            ]
        if sha256 != entry.sha256.lower():
            return [
                PackageError(
                    CHECKSUM_MISMATCH,
                    f"Suma SHA-256 wpisu „{safe_entry_name(entry.path)}” niezgodna z manifestem",
                )
            ]
    return []


# --- krok 7: spójność wektorów i liczników -------------------------------------------------


def check_consistency(archive: zipfile.ZipFile, manifest: Manifest) -> list[PackageError]:
    """Krok 7: części/kształt ``.npy`` wobec ``counts``/``dimension`` i liczba linii JSONL."""
    by_name = {info.filename: info for info in archive.infolist()}
    vectors = sorted(name for name in by_name if name.startswith(VECTORS_PREFIX))
    if manifest.embedding.included:
        errors = _check_vectors(archive, manifest, vectors, by_name)
        if errors:
            return errors
    errors = _check_line_counts(archive, manifest, by_name)
    if errors:
        return errors
    if not manifest.embedding.included and vectors:
        return [
            PackageError(UNEXPECTED_ENTRY, f"Paczka bez wektorów zawiera wpisy „{VECTORS_PREFIX}*”")
        ]
    return []


def _check_vectors(  # noqa: PLR0911 — każdy naruszony warunek kończy krok
    archive: zipfile.ZipFile,
    manifest: Manifest,
    vectors: list[str],
    by_name: dict[str, zipfile.ZipInfo],
) -> list[PackageError]:
    """Spójność plików ``vectors/*.npy`` z ``counts`` i ``embedding.dimension``."""
    chunks = manifest.counts.chunks
    parts = math.ceil(chunks / VECTOR_PART_ROWS)
    if not vectors:
        if chunks > 0:
            return [
                PackageError(
                    MISSING_ENTRY, "Paczka deklaruje wektory, ale nie zawiera plików vectors/*.npy"
                )
            ]
        return []
    if len(vectors) != parts:
        return [
            PackageError(
                DIMENSION_MISMATCH,
                f"Liczba części wektorów ({len(vectors)}) niezgodna z counts.chunks ({chunks})",
            )
        ]
    total_rows = 0
    for index, name in enumerate(vectors):
        expected = (
            VECTOR_PART_ROWS if index < parts - 1 else chunks - VECTOR_PART_ROWS * (parts - 1)
        )
        try:
            rows, columns = _vector_shape(archive, by_name[name])
        except ValueError as exc:
            return [
                PackageError(
                    DIMENSION_MISMATCH,
                    f"Niepoprawny plik wektorów „{safe_entry_name(name)}”: {exc}",
                )
            ]
        if columns != manifest.embedding.dimension:
            return [
                PackageError(
                    DIMENSION_MISMATCH,
                    f"Wektor „{safe_entry_name(name)}” ma {columns} kolumn, wymiar modelu to"
                    f" {manifest.embedding.dimension}",
                )
            ]
        if rows != expected:
            return [
                PackageError(
                    DIMENSION_MISMATCH,
                    f"Wektor „{safe_entry_name(name)}” ma {rows} wierszy, oczekiwano {expected}",
                )
            ]
        total_rows += rows
    if total_rows != manifest.counts.vectors or total_rows != chunks:
        return [
            PackageError(
                DIMENSION_MISMATCH,
                f"Suma wierszy wektorów ({total_rows}) niezgodna z counts.vectors"
                f" ({manifest.counts.vectors}) i counts.chunks ({chunks})",
            )
        ]
    return []


def _vector_shape(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> tuple[int, int]:
    """``(wiersze, kolumny)`` z nagłówka NPY; ``ValueError`` przy niepoprawnym pliku."""
    with archive.open(info) as fp:
        rows, columns = read_npy_header(cast("BinaryIO", fp))
    if not isinstance(rows, int) or not isinstance(columns, int):
        raise ValueError(f"niepoprawny kształt macierzy: {(rows, columns)!r}")
    return rows, columns


def _check_line_counts(
    archive: zipfile.ZipFile, manifest: Manifest, by_name: dict[str, zipfile.ZipInfo]
) -> list[PackageError]:
    """Liczba linii ``chunks.jsonl``/``documents.jsonl`` zgodna z licznikami manifestu."""
    expected = ((CHUNKS_PATH, manifest.counts.chunks), (DOCUMENTS_PATH, manifest.counts.documents))
    for name, count in expected:
        lines = _count_lines(archive, by_name.get(name))
        if lines != count:
            return [
                PackageError(
                    MANIFEST_INVALID,
                    f"Liczba linii „{name}” ({lines}) niezgodna z manifestem ({count})",
                )
            ]
    return []


def _count_lines(archive: zipfile.ZipFile, info: zipfile.ZipInfo | None) -> int:
    """Liczba linii wpisu JSONL czytanego strumieniowo (brak wpisu = 0 linii)."""
    if info is None:
        return 0
    lines = 0
    ends_with_newline = True
    with archive.open(info) as fp:
        while True:
            block = fp.read(READ_BLOCK)
            if not block:
                break
            lines += block.count(b"\n")
            ends_with_newline = block.endswith(b"\n")
    return lines if ends_with_newline else lines + 1
