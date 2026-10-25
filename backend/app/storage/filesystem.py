"""FilesystemStorage — jedyna implementacja portu Storage (K5 §1.3, kontrakt C3).

Wszystkie blokujące operacje plikowe idą przez `asyncio.to_thread` — dostęp do pliku
zamknięty jest w funkcjach synchronicznych wołanych z wątku (ruff ASYNC230).
"""

import asyncio
import os
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

import xxhash

from app.core.errors import NotFound, UpstreamError, ValidationFailed
from app.storage.base import StoredObject
from app.storage.keys import StorageKey, validate_key

_LAYOUT_DIRS: tuple[str, ...] = ("files", "images", "filemanager", "tmp")


async def _as_chunks(data: bytes | AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    """Ujednolica wejście put: bytes jako jeden kawałek, strumień bez zmian."""
    if isinstance(data, bytes):
        yield data
    else:
        async for chunk in data:
            yield chunk


class FilesystemStorage:
    """Storage na plikach: strumieniowy zapis przez tmp/, fsync i atomowe os.replace."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def local_path(self, key: StorageKey) -> Path:
        """root / key po walidacji, bez sprawdzania istnienia."""
        return self.root / validate_key(key)

    async def put(
        self,
        key: StorageKey,
        data: bytes | AsyncIterator[bytes],
        *,
        max_bytes: int | None = None,
    ) -> StoredObject:
        """Zapisuje strumieniowo do tmp/{uuid}, limit sprawdza przed zapisem kawałka (C3)."""
        dest = self.local_path(key)
        tmp = self.root / "tmp" / uuid4().hex
        digest = xxhash.xxh128()
        size = 0
        fh: BinaryIO | None = None
        try:
            await asyncio.to_thread(self._mkdirs, dest.parent)
            fh = await asyncio.to_thread(self._open_tmp, tmp)
            async for chunk in _as_chunks(data):
                size += len(chunk)
                if max_bytes is not None and size > max_bytes:
                    raise ValidationFailed(f"file exceeds limit of {max_bytes} bytes")
                digest.update(chunk)
                await asyncio.to_thread(fh.write, chunk)
            await asyncio.to_thread(self._finish_tmp, fh, tmp, dest)
            fh = None
        finally:
            if fh is not None:
                await asyncio.to_thread(self._discard_tmp, fh, tmp)
        return StoredObject(key, size, digest.hexdigest())

    async def open(self, key: StorageKey, *, chunk_size: int = 1 << 20) -> AsyncIterator[bytes]:
        """Async generator odczytu; brak pliku → NotFound przy pierwszym __anext__ (C3)."""
        path = self.local_path(key)
        if not await asyncio.to_thread(path.is_file):
            raise NotFound(f"storage object not found: {key}")
        fh = await asyncio.to_thread(self._open_read, path)
        try:
            while chunk := await asyncio.to_thread(fh.read, chunk_size):
                yield chunk
        finally:
            if not fh.closed:
                await asyncio.to_thread(self._close, fh)

    async def exists(self, key: StorageKey) -> bool:
        """Prawda, gdy pod kluczem jest zwykły plik."""
        return await asyncio.to_thread(self.local_path(key).is_file)

    async def delete(self, key: StorageKey) -> None:
        """Usuwa obiekt; brak pliku nie jest błędem."""
        await asyncio.to_thread(self.local_path(key).unlink, missing_ok=True)

    async def delete_prefix(self, prefix: StorageKey) -> int:
        """Usuwa cały katalog prefixu i zwraca liczbę usuniętych plików; brak katalogu → 0."""
        return await asyncio.to_thread(self._delete_prefix, validate_key(prefix))

    async def ensure_layout(self) -> None:
        """Tworzy katalogi układu, czyści tmp/ i sprawdza zapis; błąd → UpstreamError (C3)."""
        await asyncio.to_thread(self._ensure_layout)

    def _mkdirs(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)

    def _open_tmp(self, tmp: Path) -> BinaryIO:
        self._mkdirs(tmp.parent)
        return open(tmp, "wb")

    def _open_read(self, path: Path) -> BinaryIO:
        return open(path, "rb")

    @staticmethod
    def _close(fh: BinaryIO) -> None:
        fh.close()

    def _finish_tmp(self, fh: BinaryIO, tmp: Path, dest: Path) -> None:
        fh.flush()
        os.fsync(fh.fileno())
        fh.close()
        os.replace(tmp, dest)

    def _discard_tmp(self, fh: BinaryIO, tmp: Path) -> None:
        fh.close()
        tmp.unlink(missing_ok=True)

    def _delete_prefix(self, prefix: StorageKey) -> int:
        directory = self.root / prefix
        if not directory.is_dir():
            return 0
        count = sum(1 for entry in directory.rglob("*") if entry.is_file())
        shutil.rmtree(directory)
        return count

    def _ensure_layout(self) -> None:
        try:
            for name in _LAYOUT_DIRS:
                self._mkdirs(self.root / name)
            tmp = self.root / "tmp"
            for entry in tmp.iterdir():
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
            probe = tmp / f".probe-{uuid4().hex}"
            probe.write_bytes(b"")
            probe.unlink()
        except OSError as exc:
            raise UpstreamError(f"storage not writable: {exc}") from exc
