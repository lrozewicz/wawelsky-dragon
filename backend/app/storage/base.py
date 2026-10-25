"""Port storage — dosłownie K5 §1.2 (kontrakt C2)."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.storage.keys import StorageKey


@dataclass(frozen=True)
class StoredObject:
    """Metadane zapisanego obiektu."""

    key: StorageKey
    size: int
    content_hash: str  # xxh128 hexdigest (32 znaki) → documents.content_hash CHAR(32)


class Storage(Protocol):
    """Port magazynu obiektów (pliki, przyszłe S3 itd.)."""

    async def put(
        self,
        key: StorageKey,
        data: bytes | AsyncIterator[bytes],
        *,
        max_bytes: int | None = None,
    ) -> StoredObject: ...
    def open(self, key: StorageKey, *, chunk_size: int = 1 << 20) -> AsyncIterator[bytes]: ...
    def local_path(self, key: StorageKey) -> Path: ...
    async def exists(self, key: StorageKey) -> bool: ...
    async def delete(self, key: StorageKey) -> None: ...
    async def delete_prefix(self, prefix: StorageKey) -> int: ...
    async def ensure_layout(self) -> None: ...
