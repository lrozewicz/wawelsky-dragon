"""Stan i dane początkowe stubu Microsoft Graph (C3)."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

SITE_ID = "site-e2e"
SITE_NAME = "E2E Site"
SITE_URL_PREFIX = "https://contoso.sharepoint.test/sites/e2e"
LAST_MODIFIED = "2026-09-01T10:00:00Z"

DRIVE_DOCS = "drive-docs"
DRIVE_ARCH = "drive-arch"
DRIVE_NAMES: dict[str, str] = {DRIVE_DOCS: "Dokumenty", DRIVE_ARCH: "Archiwum"}

_NOTATKA = b"Notatka z SharePointa, smok wawelski.\n"
_ARCH = b"Archiwum, stary dokument.\n"

_MIME_BY_SUFFIX = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain",
}


@dataclass(frozen=True)
class FileEntry:
    """Plik w napędzie: identyfikator, nazwa, wersja dodania, treść i typ MIME."""

    id: str
    name: str
    drive_id: str
    version: int
    content: bytes
    mime_type: str


def _mime_type(name: str) -> str:
    """Typ MIME z rozszerzenia nazwy; nieznane rozszerzenie → `application/octet-stream`."""
    suffix = Path(name).suffix.lstrip(".").lower()
    return _MIME_BY_SUFFIX.get(suffix, "application/octet-stream")


def _entry(item_id: str, name: str, drive_id: str, version: int, content: bytes) -> FileEntry:
    """Buduje wpis pliku z typem MIME wyliczonym z nazwy."""
    return FileEntry(item_id, name, drive_id, version, content, _mime_type(name))


def _initial_files() -> dict[str, FileEntry]:
    """Cztery pliki początkowe (wersja 0) w dwóch napędach — stan `reset` (C3)."""
    return {
        "item-pdf": _entry(
            "item-pdf", "sample.pdf", DRIVE_DOCS, 0, (FIXTURES_DIR / "sample.pdf").read_bytes()
        ),
        "item-docx": _entry(
            "item-docx", "sample.docx", DRIVE_DOCS, 0, (FIXTURES_DIR / "sample.docx").read_bytes()
        ),
        "item-txt": _entry("item-txt", "notatka.txt", DRIVE_DOCS, 0, _NOTATKA),
        "item-arch": _entry("item-arch", "arch.txt", DRIVE_ARCH, 0, _ARCH),
    }


def item_json(entry: FileEntry) -> dict[str, Any]:
    """driveItem w kształcie Graph (C3)."""
    drive_name = DRIVE_NAMES[entry.drive_id]
    return {
        "id": entry.id,
        "name": entry.name,
        "size": len(entry.content),
        "cTag": f"c{entry.id}-{entry.version}",
        "eTag": f"e{entry.id}-{entry.version}",
        "file": {"mimeType": entry.mime_type},
        "parentReference": {"path": f"/drives/{entry.drive_id}/root:"},
        "webUrl": f"{SITE_URL_PREFIX}/{drive_name}/{entry.name}",
        "lastModifiedDateTime": LAST_MODIFIED,
    }


class State:
    """Stan w pamięci: pliki, bieżąca wersja i licznik identyfikatorów; chroniony blokadą."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._files: dict[str, FileEntry] = {}
        self._version = 0
        self._next_number = 1
        self.reset()

    def reset(self) -> None:
        """Przywraca dane początkowe i zeruje wersję."""
        with self._lock:
            self._files = _initial_files()
            self._version = 0
            self._next_number = 1

    def has_drive(self, drive_id: str) -> bool:
        """Czy napęd o tym identyfikatorze istnieje w stubie."""
        return drive_id in DRIVE_NAMES

    def files(self, drive_id: str) -> list[FileEntry]:
        """Wszystkie pliki napędu w kolejności dodania (pełne przejście delty)."""
        with self._lock:
            return [entry for entry in self._files.values() if entry.drive_id == drive_id]

    def changed(self, drive_id: str, since: int) -> list[FileEntry]:
        """Pliki napędu dodane z wersją większą niż `since` (delta z kursorem)."""
        with self._lock:
            return [
                entry
                for entry in self._files.values()
                if entry.drive_id == drive_id and entry.version > since
            ]

    def get(self, drive_id: str, item_id: str) -> FileEntry | None:
        """Plik w danym napędzie albo `None`, gdy brak lub należy do innego napędu."""
        with self._lock:
            entry = self._files.get(item_id)
        if entry is None or entry.drive_id != drive_id:
            return None
        return entry

    def current_version(self) -> int:
        """Bieżąca wersja stanu (wartość kursora delty)."""
        with self._lock:
            return self._version

    def add(self, drive_id: str, name: str, text: str) -> FileEntry:
        """Dodaje plik tekstowy, podbija wersję i zwraca nowy wpis."""
        with self._lock:
            self._version += 1
            entry = FileEntry(
                f"item-{self._next_number}",
                name,
                drive_id,
                self._version,
                text.encode("utf-8"),
                _mime_type(name),
            )
            self._next_number += 1
            self._files[entry.id] = entry
            return entry
