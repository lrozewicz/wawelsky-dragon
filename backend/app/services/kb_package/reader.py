"""Odczyt paczki .wdkb (K19 §2, CONTRACT §4) — strumieniowo, po walidacji.

Reader przyjmuje ``ValidatedPackage`` (wynik ``validate_package``), więc nie powtarza kontroli
bezpieczeństwa — czyta wpisy JSONL linia po linii i wektory część po części.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import BinaryIO, TypeVar, cast

from app.services.kb_package.format import (
    CHUNKS_PATH,
    DOCUMENTS_PATH,
    ChunkLine,
    DocumentLine,
    read_npy,
    vector_part_path,
)
from app.services.kb_package.validate import ValidatedPackage

LineModel = TypeVar("LineModel", DocumentLine, ChunkLine)


class PackageReader:
    """Czyta zawartość zwalidowanej paczki .wdkb (dokumenty, chunki, wektory, pliki)."""

    def __init__(self, pkg: ValidatedPackage) -> None:
        self._pkg = pkg
        self._entries = {entry.path for entry in pkg.manifest.entries}

    def documents(self) -> Iterator[DocumentLine]:
        """Linie ``documents.jsonl`` (pusta sekwencja, gdy wpisu brak w manifeście)."""
        return self._lines(DOCUMENTS_PATH, DocumentLine)

    def chunks(self) -> Iterator[ChunkLine]:
        """Linie ``chunks.jsonl`` (pusta sekwencja, gdy wpisu brak w manifeście)."""
        return self._lines(CHUNKS_PATH, ChunkLine)

    def vectors(self) -> Iterator[list[float]]:
        """Wiersze kolejnych ``vectors/*.npy``; puste, gdy ``embedding.included`` fałszywe."""
        if not self._pkg.manifest.embedding.included:
            return
        with zipfile.ZipFile(self._pkg.path) as zf:
            index = 0
            while vector_part_path(index) in self._entries:
                with zf.open(vector_part_path(index)) as fp:
                    yield from read_npy(cast("BinaryIO", fp))
                index += 1

    def open_entry(self, path: str) -> AbstractContextManager[BinaryIO]:
        """Strumień wpisu ``files/<sha>``/``images/<sha>``.

        Ścieżka spoza ``manifest.entries`` → ``KeyError``.
        """
        if path not in self._entries:
            raise KeyError(path)
        return self._open(path)

    @contextmanager
    def _open(self, path: str) -> Iterator[BinaryIO]:
        with zipfile.ZipFile(self._pkg.path) as zf, zf.open(path) as fp:
            yield cast("BinaryIO", fp)

    def _lines(self, path: str, model: type[LineModel]) -> Iterator[LineModel]:
        """Parsuje wpis JSONL linia po linii do modelu pydantic; puste linie pomija."""
        if path not in self._entries:
            return
        with (
            zipfile.ZipFile(self._pkg.path) as zf,
            zf.open(path) as raw,
            io.TextIOWrapper(raw, encoding="utf-8") as text,
        ):
            for line in text:
                stripped = line.strip()
                if stripped:
                    yield model.model_validate_json(stripped)
