"""Zapis paczki .wdkb (K19 §2, CONTRACT §2) — strumieniowo i deterministycznie.

Writer buduje paczkę w pliku ``final_path + ".part"`` i podmienia ją atomowo w ``finish``.
Wpisy mają ustaloną datę (2020-01-01) i prawa pliku, więc ten sam manifest + te same dane
dają bajt w bajt identyczny ZIP.
"""

from __future__ import annotations

import hashlib
import os
import zipfile
from collections.abc import Iterable
from pathlib import Path

from app.services.kb_package.format import (
    ENTRY_PATH_RE,
    MANIFEST_PATH,
    Manifest,
    ManifestEntry,
)

# Stała data i prawa pliku wpisów — źródło deterministyczności ZIP-a.
FIXED_DATE_TIME = (2020, 1, 1, 0, 0, 0)
FILE_MODE_ATTR = 0o644 << 16


def _entry_info(path: str) -> zipfile.ZipInfo:
    """``ZipInfo`` wpisu z ustaloną datą, kompresją i prawami pliku."""
    info = zipfile.ZipInfo(path, date_time=FIXED_DATE_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = FILE_MODE_ATTR
    return info


class PackageWriter:
    """Buduje paczkę .wdkb: wpisy przez ``add_file``/``add_bytes``, manifest w ``finish``."""

    def __init__(self, final_path: Path, *, max_bytes: int) -> None:
        self._final_path = final_path
        self._part_path = final_path.with_name(final_path.name + ".part")
        self._max_bytes = max_bytes
        self._total = 0
        self._entries: list[ManifestEntry] = []
        self._paths: set[str] = set()
        self._final_path.parent.mkdir(parents=True, exist_ok=True)
        self._zip = zipfile.ZipFile(self._part_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True)

    def add_file(self, path: str, chunks: Iterable[bytes]) -> ManifestEntry:
        """Dodaje wpis strumieniowo; SHA-256 i rozmiar liczone w locie.

        Przekroczenie ``max_bytes`` → ``ValueError`` i automatyczne ``abort()`` (usuwa ``.part``),
        żeby nieudany zapis nie zostawiał częściowego pliku (MINOR T3).
        """
        self._check_path(path)
        digest = hashlib.sha256()
        size = 0
        try:
            with self._zip.open(_entry_info(path), "w", force_zip64=True) as fp:
                for chunk in chunks:
                    if self._total + size + len(chunk) > self._max_bytes:
                        raise ValueError("package too large")
                    fp.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
        except ValueError:
            self.abort()
            raise
        self._total += size
        entry = ManifestEntry(path=path, sha256=digest.hexdigest(), size=size)
        self._entries.append(entry)
        self._paths.add(path)
        return entry

    def add_bytes(self, path: str, data: bytes) -> ManifestEntry:
        """Dodaje wpis z jednego bufora bajtów."""
        return self.add_file(path, (data,))

    def finish(self, manifest: Manifest) -> int:
        """Uzupełnia ``manifest.entries``, zapisuje manifest.json, zamyka ZIP i zwraca rozmiar.

        ``manifest.json`` wchodzi do limitu ``max_bytes``; przekroczenie → ``ValueError`` i
        ``abort()`` (MINOR T3).
        """
        manifest.entries = list(self._entries)
        payload = manifest.model_dump_json().encode("utf-8")
        if self._total + len(payload) > self._max_bytes:
            self.abort()
            raise ValueError("package too large")
        with self._zip.open(_entry_info(MANIFEST_PATH), "w", force_zip64=True) as fp:
            fp.write(payload)
        self._total += len(payload)
        self._zip.close()
        os.replace(self._part_path, self._final_path)
        return self._final_path.stat().st_size

    def abort(self) -> None:
        """Zamyka ZIP i usuwa plik ``.part`` (brak pliku nie jest błędem)."""
        self._zip.close()
        self._part_path.unlink(missing_ok=True)

    def _check_path(self, path: str) -> None:
        """Waliduje ścieżkę wpisu (wzorzec z formatu) i odrzuca duplikat."""
        if not ENTRY_PATH_RE.fullmatch(path):
            raise ValueError(f"Niedozwolona ścieżka wpisu paczki: {path!r}")
        if path in self._paths:
            raise ValueError(f"Zduplikowany wpis paczki: {path!r}")
