"""Testy FilesystemStorage wg C3 — scenariusze z briefu T1."""

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import xxhash

from app.core.errors import NotFound, UpstreamError, ValidationFailed
from app.storage.base import StoredObject
from app.storage.filesystem import FilesystemStorage
from app.storage.keys import StorageKey, derived_key, document_key, document_prefix

_CHUNK = 4
_DATA_LEN = 10
_LIMIT = 5
_OVERWRITE_SIZE = 11
_REMOVED_COUNT = 3


async def test_put_bytes(tmp_path: Path) -> None:
    fs = FilesystemStorage(tmp_path)
    data = b"hello"
    stored = await fs.put(StorageKey("files/a/b"), data)
    assert stored == StoredObject(StorageKey("files/a/b"), 5, xxhash.xxh128(data).hexdigest())
    dest = tmp_path / "files" / "a" / "b"
    assert dest.is_file()
    assert dest.read_bytes() == data
    assert not any((tmp_path / "tmp").iterdir())


async def test_put_async_iterator(tmp_path: Path) -> None:
    fs = FilesystemStorage(tmp_path)
    parts = [b"aa", b"bbb", b"cc"]

    async def stream() -> AsyncIterator[bytes]:
        for part in parts:
            yield part

    stored = await fs.put(StorageKey("files/s"), stream())
    joined = b"".join(parts)
    assert stored.size == len(joined)
    assert stored.content_hash == xxhash.xxh128(joined).hexdigest()
    assert (tmp_path / "files" / "s").read_bytes() == joined
    assert not any((tmp_path / "tmp").iterdir())


async def test_put_exceeds_max_bytes_bytes(tmp_path: Path) -> None:
    fs = FilesystemStorage(tmp_path)
    with pytest.raises(ValidationFailed, match="file exceeds limit of 5 bytes"):
        await fs.put(StorageKey("files/big"), b"123456", max_bytes=_LIMIT)
    assert not (tmp_path / "files" / "big").exists()
    assert not any((tmp_path / "tmp").iterdir())


async def test_put_exceeds_max_bytes_stream(tmp_path: Path) -> None:
    fs = FilesystemStorage(tmp_path)

    async def stream() -> AsyncIterator[bytes]:
        yield b"123"
        yield b"456"

    with pytest.raises(ValidationFailed, match="file exceeds limit of 5 bytes"):
        await fs.put(StorageKey("files/big"), stream(), max_bytes=_LIMIT)
    assert not (tmp_path / "files" / "big").exists()
    assert not any((tmp_path / "tmp").iterdir())


async def test_put_overwrite(tmp_path: Path) -> None:
    fs = FilesystemStorage(tmp_path)
    key = StorageKey("files/a")
    await fs.put(key, b"old")
    stored = await fs.put(key, b"new-content")
    assert stored.size == _OVERWRITE_SIZE
    assert (tmp_path / "files" / "a").read_bytes() == b"new-content"


async def test_put_iterator_exception(tmp_path: Path) -> None:
    fs = FilesystemStorage(tmp_path)

    async def stream() -> AsyncIterator[bytes]:
        yield b"part"
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await fs.put(StorageKey("files/x"), stream())
    assert not (tmp_path / "files" / "x").exists()
    assert not any((tmp_path / "tmp").iterdir())


async def test_open_chunks(tmp_path: Path) -> None:
    fs = FilesystemStorage(tmp_path)
    data = b"0123456789"
    stored = await fs.put(StorageKey("files/ten"), data)
    chunks = [chunk async for chunk in fs.open(stored.key, chunk_size=_CHUNK)]
    assert [len(chunk) for chunk in chunks] == [_CHUNK, _CHUNK, _DATA_LEN - 2 * _CHUNK]
    assert b"".join(chunks) == data


async def test_open_missing_key_raises_not_found_at_iteration(tmp_path: Path) -> None:
    fs = FilesystemStorage(tmp_path)
    with pytest.raises(NotFound, match="storage object not found"):
        _ = [chunk async for chunk in fs.open(StorageKey("files/missing"))]


async def test_exists_and_delete_twice(tmp_path: Path) -> None:
    fs = FilesystemStorage(tmp_path)
    key = StorageKey("files/a")
    assert await fs.exists(key) is False
    await fs.put(key, b"data")
    assert await fs.exists(key) is True
    await fs.delete(key)
    assert await fs.exists(key) is False
    await fs.delete(key)  # drugi raz bez błędu


async def test_delete_prefix(tmp_path: Path) -> None:
    fs = FilesystemStorage(tmp_path)
    await fs.put(document_key("d1", "x1", "pdf"), b"a")
    await fs.put(derived_key("d1", "x1", "a"), b"b")
    await fs.put(derived_key("d1", "x1", "b"), b"c")
    await fs.put(document_key("d1", "x2", "pdf"), b"d")
    removed = await fs.delete_prefix(document_prefix("d1", "x1"))
    assert removed == _REMOVED_COUNT
    assert not (tmp_path / "files" / "d1" / "x1").exists()
    assert await fs.delete_prefix(document_prefix("d1", "x1")) == 0
    assert (tmp_path / "files" / "d1" / "x2" / "original.pdf").is_file()


async def test_ensure_layout(tmp_path: Path) -> None:
    fs = FilesystemStorage(tmp_path)
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    (tmp / "stale.bin").write_bytes(b"x")
    (tmp / "stale-dir").mkdir()
    (tmp / "stale-dir" / "inner.bin").write_bytes(b"y")
    await fs.ensure_layout()
    for name in ("files", "images", "filemanager", "tmp"):
        assert (tmp_path / name).is_dir()
    assert list(tmp.iterdir()) == []


async def test_ensure_layout_readonly_root(tmp_path: Path) -> None:
    if os.geteuid() == 0:
        pytest.skip("root pomija uprawnienia systemu plików")
    ro = tmp_path / "ro"
    ro.mkdir()
    fs = FilesystemStorage(ro)
    ro.chmod(0o500)
    try:
        with pytest.raises(UpstreamError, match=r"^storage not writable"):
            await fs.ensure_layout()
    finally:
        ro.chmod(0o700)


def test_local_path(tmp_path: Path) -> None:
    fs = FilesystemStorage(tmp_path)
    assert fs.local_path(StorageKey("files/a")) == tmp_path / "files" / "a"
    with pytest.raises(ValidationFailed):
        fs.local_path(StorageKey("../x"))
