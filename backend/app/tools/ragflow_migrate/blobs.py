"""Bloby migracji RAGFlow → WD: odczyt źródła, plan kluczy i kopiowanie z weryfikacją.

Kontrakt WP E4-6b1 §4 (zadanie T3). Moduł nie zna bazy: jedyne I/O to pliki źródłowe
(``--src-files-dir`` w układzie ``<root>/<bucket>/<location>``) oraz port ``Storage``.
``documents.content_hash`` w celu to xxh128 (DEC-132); SHA-256 służy wyłącznie do
weryfikacji kopii po zapisie.
"""

import asyncio
import hashlib
import re
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Literal

import xxhash

from app.core.errors import NotFound
from app.storage.base import Storage
from app.storage.keys import StorageKey, document_key, filemanager_key

#: Rozmiar bloku odczytu źródła (kontrakt §4: 1 MiB).
CHUNK_SIZE = 1 << 20

#: Suffix rozszerzenia: małe litery i cyfry, 1-16 znaków (to samo co w ``app.storage.keys``).
_SUFFIX_RE = re.compile(r"[a-z0-9]{1,16}")


@dataclass(frozen=True)
class BlobRef:
    """Wskazanie bloba w źródle: kubełek MinIO RAGFlow i klucz wewnątrz kubełka."""

    bucket: str
    location: str


@dataclass(frozen=True)
class BlobInfo:
    """Metadane bloba źródłowego; ``xxh128`` liczony tak samo jak w ``FilesystemStorage``."""

    size: int
    sha256: str
    xxh128: str


class SourceFiles:
    """Katalog ``--src-files-dir`` jako źródło blobów."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def path(self, ref: BlobRef) -> Path | None:
        """Ścieżka bloba; ``None`` gdy puste pole, wyjście poza root albo brak zwykłego pliku."""
        if not ref.bucket or not ref.location:
            return None
        candidate = (self._root / ref.bucket / ref.location).resolve()
        if not candidate.is_relative_to(self._root) or not candidate.is_file():
            return None
        return candidate

    def inspect(self, ref: BlobRef) -> BlobInfo | None:
        """Metadane bloba; ``None`` gdy brak pliku albo ścieżka jest niebezpieczna."""
        path = self.path(ref)
        if path is None:
            return None
        sha256 = hashlib.sha256()
        xxh128 = xxhash.xxh128()
        size = 0
        with path.open("rb") as fh:
            while chunk := fh.read(CHUNK_SIZE):
                size += len(chunk)
                sha256.update(chunk)
                xxh128.update(chunk)
        return BlobInfo(size=size, sha256=sha256.hexdigest(), xxh128=xxh128.hexdigest())

    async def stream(self, ref: BlobRef, chunk_size: int = 1 << 20) -> AsyncIterator[bytes]:
        """Strumień bloba blokami; odczyt blokujący w wątku, plik zamknięty w ``finally``."""
        path = self.path(ref)
        if path is None:
            raise NotFound(f"source blob not found: {ref.bucket}/{ref.location}")
        fh = await asyncio.to_thread(_open_read, path)
        try:
            while chunk := await asyncio.to_thread(fh.read, chunk_size):
                yield chunk
        finally:
            await asyncio.to_thread(fh.close)


def _open_read(path: Path) -> BinaryIO:
    """Otwiera plik do odczytu binarnego (wołane w wątku — ruff ASYNC230)."""
    return path.open("rb")


def blob_suffix(name: str) -> str:
    """Rozszerzenie nazwy: małe litery bez kropki, tylko ``[a-z0-9]{1,16}``, inaczej ``""``."""
    _, dot, suffix = name.rpartition(".")
    if not dot:
        return ""
    suffix = suffix.lower()
    return suffix if _SUFFIX_RE.fullmatch(suffix) else ""


@dataclass(frozen=True)
class BlobEntry:
    """Jeden blob do skopiowania: dokąd, skąd, ile i kto go używa."""

    dest: StorageKey
    ref: BlobRef
    expected_size: int
    owners: tuple[str, ...]


@dataclass(frozen=True)
class BlobPlan:
    """Plan blobów etapu ``documents``: wpisy plus mapy id → dest."""

    entries: dict[StorageKey, BlobEntry]
    doc_dest: dict[str, StorageKey]
    file_dest: dict[str, StorageKey]


def _text(value: Any) -> str:
    """Wartość kolumny jako tekst; ``None`` → ``''`` (pusty ``location`` z kontraktu §4)."""
    return "" if value is None else str(value)


def _size(value: Any) -> int:
    """Wartość kolumny jako rozmiar; ``None`` → ``0``."""
    return 0 if value is None else int(value)


def _is_folder(row: Mapping[str, Any]) -> bool:
    return _text(row.get("type")) == "folder"


def _is_kb_view(row: Mapping[str, Any]) -> bool:
    """Prawda dla pliku-widoku RAGFlow (``source_type='knowledgebase'``)."""
    return _text(row.get("source_type")) == "knowledgebase"


def plan_blobs(
    files: Sequence[Mapping[str, Any]],
    documents: Sequence[Mapping[str, Any]],
    links: Sequence[Mapping[str, Any]],
) -> BlobPlan:
    """Buduje plan blobów wg reguł kontraktu §4; kolejność wpisów po ``dest``."""
    file_by_id = {_text(row.get("id")): row for row in files}
    files_by_doc: dict[str, list[str]] = {}
    for link in links:
        document_id = _text(link.get("document_id"))
        file_id = _text(link.get("file_id"))
        if document_id and file_id in file_by_id:
            files_by_doc.setdefault(document_id, []).append(file_id)

    refs: dict[StorageKey, tuple[BlobRef, int]] = {}
    owners: dict[StorageKey, set[str]] = {}
    doc_dest: dict[str, StorageKey] = {}
    file_dest: dict[str, StorageKey] = {}

    def add(dest: StorageKey, ref: BlobRef, size: int, owner: str) -> None:
        """Dokłada właściciela do wpisu; ``ref``/``size`` wygrywa pierwsze źródło."""
        refs.setdefault(dest, (ref, size))
        owners.setdefault(dest, set()).add(owner)

    for document in documents:
        document_id = _text(document.get("id"))
        linked = [file_by_id[fid] for fid in files_by_doc.get(document_id, [])]
        managers = [f for f in linked if not _is_folder(f) and not _is_kb_view(f)]
        if managers:
            manager = managers[0]
            file_id = _text(manager.get("id"))
            dest = filemanager_key(file_id, blob_suffix(_text(manager.get("name"))))
            ref = BlobRef(_text(manager.get("parent_id")), _text(manager.get("location")))
            size = _size(manager.get("size"))
            add(dest, ref, size, f"file:{file_id}")
            file_dest[file_id] = dest
        else:
            dest = document_key(
                _text(document.get("kb_id")), document_id, blob_suffix(_text(document.get("name")))
            )
            ref = BlobRef(_text(document.get("kb_id")), _text(document.get("location")))
            size = _size(document.get("size"))
        doc_dest[document_id] = dest
        add(dest, ref, size, f"document:{document_id}")
        # Plik-widok (``source_type='knowledgebase'``) nie ma własnego bloba.
        for view in linked:
            if _is_kb_view(view):
                file_id = _text(view.get("id"))
                file_dest[file_id] = dest
                add(dest, ref, size, f"file:{file_id}")

    for row in files:
        file_id = _text(row.get("id"))
        if _is_folder(row) or file_id in file_dest:
            continue
        dest = filemanager_key(file_id, blob_suffix(_text(row.get("name"))))
        ref = BlobRef(_text(row.get("parent_id")), _text(row.get("location")))
        add(dest, ref, _size(row.get("size")), f"file:{file_id}")
        file_dest[file_id] = dest

    entries = {
        dest: BlobEntry(dest, refs[dest][0], refs[dest][1], tuple(sorted(owners[dest])))
        for dest in sorted(refs)
    }
    return BlobPlan(entries=entries, doc_dest=doc_dest, file_dest=file_dest)


@dataclass(frozen=True)
class CopyOutcome:
    """Wynik kopiowania bloba; ``content_hash`` to xxh128 źródła, ``''`` gdy brak kopii."""

    status: Literal["copied", "unchanged", "missing", "size_mismatch"]
    content_hash: str
    actual_size: int | None


async def copy_blob(
    storage: Storage,
    source: SourceFiles,
    entry: BlobEntry,
    *,
    dry_run: bool,
    new_keys: list[str],
) -> CopyOutcome:
    """Kopiuje blob do storage i weryfikuje odczyt; ``new_keys`` dostaje tylko nowe klucze."""
    info = source.inspect(entry.ref)
    if info is None:
        return CopyOutcome("missing", "", None)
    if info.size != entry.expected_size:
        return CopyOutcome("size_mismatch", "", info.size)
    dest = entry.dest
    if await _stored_matches(storage, dest, info):
        return CopyOutcome("unchanged", info.xxh128, info.size)
    if dry_run:
        return CopyOutcome("copied", info.xxh128, info.size)
    existed = await storage.exists(dest)
    stored = await storage.put(dest, source.stream(entry.ref))
    if stored.size != info.size or stored.content_hash != info.xxh128:
        raise RuntimeError(f"blob copy verification failed: {dest}")
    if await _stored_sha256(storage, dest) != info.sha256:
        raise RuntimeError(f"blob copy verification failed: {dest}")
    if not existed:
        new_keys.append(str(dest))
    return CopyOutcome("copied", info.xxh128, info.size)


async def _stored_matches(storage: Storage, dest: StorageKey, info: BlobInfo) -> bool:
    """Prawda, gdy w storage leży już identyczny blob (rozmiar i xxh128 treści)."""
    if not await storage.exists(dest):
        return False
    if await asyncio.to_thread(_local_size, storage, dest) != info.size:
        return False
    digest = xxhash.xxh128()
    async for chunk in storage.open(dest):
        digest.update(chunk)
    return digest.hexdigest() == info.xxh128


def _local_size(storage: Storage, dest: StorageKey) -> int:
    """Rozmiar pliku pod kluczem w storage (wołane w wątku)."""
    return storage.local_path(dest).stat().st_size


async def _stored_sha256(storage: Storage, dest: StorageKey) -> str:
    """SHA-256 treści zapisanej w storage (weryfikacja kopii po zapisie)."""
    digest = hashlib.sha256()
    async for chunk in storage.open(dest):
        digest.update(chunk)
    return digest.hexdigest()
