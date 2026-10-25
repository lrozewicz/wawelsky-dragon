"""Testy źródła blobów, planu kluczy i kopiowania (brief T3, WP E4-6b1)."""

import hashlib
from pathlib import Path
from typing import Any

import pytest
import xxhash

from app.core.errors import NotFound
from app.storage.base import StoredObject
from app.storage.filesystem import FilesystemStorage
from app.storage.keys import StorageKey, document_key, filemanager_key
from app.tools.ragflow_migrate.blobs import (
    BlobEntry,
    BlobInfo,
    BlobRef,
    CopyOutcome,
    SourceFiles,
    blob_suffix,
    copy_blob,
    plan_blobs,
)

DATA = b"cce75dba-bytes"


def write_blob(root: Path, bucket: str, location: str, data: bytes) -> None:
    """Kładzie blob źródłowy w układzie ``<root>/<bucket>/<location>``."""
    path = root / bucket / location
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def file_row(  # noqa: PLR0913, PLR0917 — pełny wiersz tabeli źródłowej w jednym miejscu
    fid: str,
    parent: str,
    name: str,
    size: int,
    location: str | None,
    source_type: str = "",
    type_: str = "txt",
) -> dict[str, Any]:
    return {
        "id": fid,
        "parent_id": parent,
        "name": name,
        "type": type_,
        "size": size,
        "location": location,
        "source_type": source_type,
    }


def doc_row(did: str, kb_id: str, name: str, size: int, location: str | None) -> dict[str, Any]:
    return {"id": did, "kb_id": kb_id, "name": name, "location": location, "size": size}


def link_row(fid: str, did: str) -> dict[str, Any]:
    return {"file_id": fid, "document_id": did}


async def read_storage(storage: FilesystemStorage, key: StorageKey) -> bytes:
    return b"".join([chunk async for chunk in storage.open(key)])


def source_with_raport(tmp_path: Path, data: bytes = DATA) -> tuple[SourceFiles, BlobEntry]:
    """Źródło z plikiem ``kb1/raport.pdf`` i wpisem planu wskazującym na dest w storage."""
    root = tmp_path / "src"
    write_blob(root, "kb1", "raport.pdf", data)
    entry = BlobEntry(
        dest=StorageKey("filemanager/f1/original.pdf"),
        ref=BlobRef("kb1", "raport.pdf"),
        expected_size=len(data),
        owners=("file:f1",),
    )
    return SourceFiles(root), entry


# --- SourceFiles -------------------------------------------------------------------


def test_inspect_reads_size_and_hashes(tmp_path: Path) -> None:
    """Istniejący plik → metadane z hashami policzonymi niezależnie w teście."""
    root = tmp_path / "src"
    write_blob(root, "kb1", "raport.pdf", DATA)
    source = SourceFiles(root)
    ref = BlobRef("kb1", "raport.pdf")
    assert source.inspect(ref) == BlobInfo(
        size=len(DATA),
        sha256=hashlib.sha256(DATA).hexdigest(),
        xxh128=xxhash.xxh128(DATA).hexdigest(),
    )
    assert source.path(ref) == (root / "kb1" / "raport.pdf").resolve()


def test_inspect_missing_file_is_none(tmp_path: Path) -> None:
    """Brak pliku → ``None`` (``missing`` w ``copy_blob``)."""
    source = SourceFiles(tmp_path / "src")
    assert source.inspect(BlobRef("kb1", "brak.txt")) is None


def test_path_rejects_traversal_and_escape(tmp_path: Path) -> None:
    """``..``, wyjście poza root i symlink na zewnątrz root → ``None``."""
    root = tmp_path / "src"
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"tajne")
    write_blob(root, "kb1", "ok.txt", b"x")
    (root / "kb1" / "link.txt").symlink_to(outside)
    source = SourceFiles(root)
    assert source.path(BlobRef("kb1", "../x")) is None
    assert source.path(BlobRef("kb1", "../../outside.txt")) is None
    assert source.path(BlobRef("kb1", "link.txt")) is None
    assert source.inspect(BlobRef("kb1", "link.txt")) is None
    assert source.path(BlobRef("", "ok.txt")) is None
    assert source.path(BlobRef("kb1", "")) is None


async def test_stream_yields_chunks(tmp_path: Path) -> None:
    """``stream`` czyta blokami po ``chunk_size`` i składa oryginalną treść."""
    root = tmp_path / "src"
    data = b"a" * 5000
    write_blob(root, "kb1", "duzy.bin", data)
    source = SourceFiles(root)
    chunks = [chunk async for chunk in source.stream(BlobRef("kb1", "duzy.bin"), chunk_size=1024)]
    assert b"".join(chunks) == data
    assert [len(chunk) for chunk in chunks] == [1024, 1024, 1024, 1024, 904]


async def test_stream_missing_blob_raises(tmp_path: Path) -> None:
    """Strumień nieistniejącego bloba → ``NotFound`` (bez czytania czegokolwiek)."""
    source = SourceFiles(tmp_path / "src")
    with pytest.raises(NotFound):
        async for _ in source.stream(BlobRef("kb1", "brak.txt")):
            pass


# --- blob_suffix -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Raport.PDF", "pdf"),
        ("a.tar.gz", "gz"),
        ("x", ""),
        ("a.b c", ""),
        ("a.averyveryverylongsuffix123", ""),
    ],
)
def test_blob_suffix_examples(name: str, expected: str) -> None:
    """Przykłady z kontraktu §4 dosłownie."""
    assert blob_suffix(name) == expected


# --- plan_blobs --------------------------------------------------------------------


def test_plan_folder_has_no_blob() -> None:
    """Folder (``type='folder'``) nie dostaje wpisu ani nie trafia do ``file_dest``."""
    plan = plan_blobs([file_row("f1", "root", "/", 0, None, type_="folder")], [], [])
    assert plan.entries == {}
    assert plan.doc_dest == {}
    assert plan.file_dest == {}


def test_plan_document_with_manager_file() -> None:
    """Dokument z linkiem do pliku z menedżera → wpis ``filemanager/…`` dla obu."""
    files = [file_row("f1", "root1", "raport.pdf", 19, "raport.pdf", "local", type_="pdf")]
    documents = [doc_row("d1", "kb1", "raport.pdf", 19, "raport.pdf")]
    plan = plan_blobs(files, documents, [link_row("f1", "d1")])
    dest = filemanager_key("f1", "pdf")
    assert plan.doc_dest == {"d1": dest}
    assert plan.file_dest == {"f1": dest}
    assert plan.entries[dest] == BlobEntry(
        dest=dest,
        ref=BlobRef("root1", "raport.pdf"),
        expected_size=19,
        owners=("document:d1", "file:f1"),
    )


def test_plan_document_without_link_and_knowledgebase_file() -> None:
    """Dokument bez linku → ``document_key``; plik ``knowledgebase`` to widok (bez wpisu)."""
    files = [file_row("f2", "p1", "umowa.docx", 19, "umowa.docx", "knowledgebase", type_="docx")]
    documents = [doc_row("d2", "kb1", "umowa.docx", 19, "umowa.docx")]
    plan = plan_blobs(files, documents, [link_row("f2", "d2")])
    dest = document_key("kb1", "d2", "docx")
    assert plan.doc_dest == {"d2": dest}
    assert plan.file_dest == {"f2": dest}
    assert set(plan.entries) == {dest}
    assert plan.entries[dest].ref == BlobRef("kb1", "umowa.docx")
    assert plan.entries[dest].owners == ("document:d2", "file:f2")


def test_plan_manager_file_wins_over_knowledgebase_view() -> None:
    """Plik-widok dokłada tylko właściciela i ``file_dest`` do wpisu pliku menedżera."""
    files = [
        file_row("f1", "root1", "raport.pdf", 19, "raport.pdf", "", type_="pdf"),
        file_row("f6", "p2", "raport.pdf", 19, "raport.pdf", "knowledgebase", type_="pdf"),
    ]
    documents = [doc_row("d1", "kb1", "raport.pdf", 19, "raport.pdf")]
    plan = plan_blobs(files, documents, [link_row("f1", "d1"), link_row("f6", "d1")])
    dest = filemanager_key("f1", "pdf")
    assert plan.file_dest == {"f1": dest, "f6": dest}
    assert set(plan.entries) == {dest}
    assert plan.entries[dest].owners == ("document:d1", "file:f1", "file:f6")


def test_plan_local_file_without_document() -> None:
    """Plik lokalny bez dokumentu → ``filemanager_key`` i właściciel tylko ``file:``."""
    size = 28
    files = [file_row("f3", "root2", "notatka.txt", size, "notatka.txt", "", type_="txt")]
    plan = plan_blobs(files, [], [])
    dest = filemanager_key("f3", "txt")
    assert plan.doc_dest == {}
    assert plan.file_dest == {"f3": dest}
    assert plan.entries[dest].ref == BlobRef("root2", "notatka.txt")
    assert plan.entries[dest].expected_size == size
    assert plan.entries[dest].owners == ("file:f3",)


def test_plan_knowledgebase_file_without_link() -> None:
    """Plik ``knowledgebase`` bez linku → własny wpis jak plik lokalny."""
    files = [file_row("f4", "p1", "faq.html", 17, "faq.html", "knowledgebase", type_="html")]
    plan = plan_blobs(files, [], [])
    dest = filemanager_key("f4", "html")
    assert plan.doc_dest == {}
    assert plan.file_dest == {"f4": dest}
    assert plan.entries[dest].ref == BlobRef("p1", "faq.html")
    assert plan.entries[dest].owners == ("file:f4",)


def test_plan_empty_location_keeps_empty_ref() -> None:
    """Pusty ``location`` → ``ref.location == ''`` (``inspect`` zwróci potem ``None``)."""
    documents = [doc_row("d3", "kb1", "brak.pdf", 0, None)]
    plan = plan_blobs([], documents, [])
    dest = document_key("kb1", "d3", "pdf")
    assert plan.doc_dest == {"d3": dest}
    assert plan.entries[dest].ref == BlobRef("kb1", "")
    assert plan.entries[dest].expected_size == 0


def test_plan_local_file_shared_by_two_documents() -> None:
    """Plik lokalny z dwoma dokumentami → jeden wpis z trzema właścicielami."""
    files = [file_row("f5", "root3", "wspolny.txt", 22, "wspolny.txt", "", type_="txt")]
    documents = [
        doc_row("d6", "kb1", "a.txt", 22, "wspolny.txt"),
        doc_row("d7", "kb1", "b.txt", 22, "wspolny.txt"),
    ]
    plan = plan_blobs(files, documents, [link_row("f5", "d6"), link_row("f5", "d7")])
    dest = filemanager_key("f5", "txt")
    assert set(plan.entries) == {dest}
    assert plan.entries[dest].owners == ("document:d6", "document:d7", "file:f5")
    assert plan.doc_dest == {"d6": dest, "d7": dest}
    assert plan.file_dest == {"f5": dest}


def test_plan_ignores_links_to_unknown_rows() -> None:
    """Link do nieznanego pliku lub bez ``document_id`` nie tworzy wpisu."""
    files = [file_row("f3", "root2", "notatka.txt", 28, "notatka.txt", "", type_="txt")]
    links = [link_row("nie-ma", "d9"), link_row("f3", "")]
    plan = plan_blobs(files, [], links)
    assert plan.doc_dest == {}
    assert set(plan.entries) == {filemanager_key("f3", "txt")}


def test_plan_entries_sorted_by_dest() -> None:
    """Kolejność ``entries`` zależy tylko od ``dest`` (deterministyczna)."""
    files = [
        file_row("f_c", "r", "c.txt", 1, "c.txt", "", type_="txt"),
        file_row("f_a", "r", "a.txt", 1, "a.txt", "", type_="txt"),
        file_row("f_b", "r", "b.txt", 1, "b.txt", "", type_="txt"),
    ]
    plan = plan_blobs(files, [], [])
    assert list(plan.entries) == sorted(plan.entries)
    assert list(plan.entries) == [
        filemanager_key("f_a", "txt"),
        filemanager_key("f_b", "txt"),
        filemanager_key("f_c", "txt"),
    ]


# --- copy_blob ---------------------------------------------------------------------


async def test_copy_blob_copies_and_registers_new_key(tmp_path: Path) -> None:
    """Pierwsza kopia: ``copied``, blob w storage, klucz dopisany do ``new_keys``."""
    source, entry = source_with_raport(tmp_path)
    storage = FilesystemStorage(tmp_path / "wd")
    new_keys: list[str] = []
    outcome = await copy_blob(storage, source, entry, dry_run=False, new_keys=new_keys)
    assert outcome == CopyOutcome("copied", xxhash.xxh128(DATA).hexdigest(), len(DATA))
    assert new_keys == [str(entry.dest)]
    assert await read_storage(storage, entry.dest) == DATA


async def test_copy_blob_second_call_is_unchanged(tmp_path: Path) -> None:
    """Powtórka na niezmienionym źródle: ``unchanged`` i ``new_keys`` bez zmian."""
    source, entry = source_with_raport(tmp_path)
    storage = FilesystemStorage(tmp_path / "wd")
    new_keys: list[str] = []
    await copy_blob(storage, source, entry, dry_run=False, new_keys=new_keys)
    outcome = await copy_blob(storage, source, entry, dry_run=False, new_keys=new_keys)
    assert outcome.status == "unchanged"
    assert outcome.content_hash == xxhash.xxh128(DATA).hexdigest()
    assert outcome.actual_size == len(DATA)
    assert new_keys == [str(entry.dest)]


async def test_copy_blob_missing_blob(tmp_path: Path) -> None:
    """Brak pliku w źródle: ``missing``, bez hasha i rozmiaru."""
    source = SourceFiles(tmp_path / "src")
    entry = BlobEntry(
        dest=StorageKey("filemanager/f1/original.pdf"),
        ref=BlobRef("kb1", "brak.pdf"),
        expected_size=5,
        owners=("file:f1",),
    )
    storage = FilesystemStorage(tmp_path / "wd")
    new_keys: list[str] = []
    outcome = await copy_blob(storage, source, entry, dry_run=False, new_keys=new_keys)
    assert outcome == CopyOutcome("missing", "", None)
    assert new_keys == []
    assert await storage.exists(entry.dest) is False


async def test_copy_blob_size_mismatch_copies_nothing(tmp_path: Path) -> None:
    """Rozmiar deklarowany ≠ rzeczywisty: ``size_mismatch``, storage pusty."""
    source, entry = source_with_raport(tmp_path)
    entry = BlobEntry(entry.dest, entry.ref, entry.expected_size + 1, entry.owners)
    storage = FilesystemStorage(tmp_path / "wd")
    new_keys: list[str] = []
    outcome = await copy_blob(storage, source, entry, dry_run=False, new_keys=new_keys)
    assert outcome == CopyOutcome("size_mismatch", "", len(DATA))
    assert new_keys == []
    assert await storage.exists(entry.dest) is False


async def test_copy_blob_dry_run_writes_nothing(tmp_path: Path) -> None:
    """``dry_run``: wynik ``copied``, ale bez zapisu i bez ``new_keys``."""
    source, entry = source_with_raport(tmp_path)
    storage = FilesystemStorage(tmp_path / "wd")
    new_keys: list[str] = []
    outcome = await copy_blob(storage, source, entry, dry_run=True, new_keys=new_keys)
    assert outcome.status == "copied"
    assert outcome.actual_size == len(DATA)
    assert new_keys == []
    assert await storage.exists(entry.dest) is False


async def test_copy_blob_overwrites_changed_source_without_new_key(tmp_path: Path) -> None:
    """Zmieniona treść (ten sam rozmiar) → nadpisanie, ale klucz nie jest „nowy”."""
    root = tmp_path / "src"
    changed = b"zmieniona-tres"  # ta sama długość co DATA, inna treść
    write_blob(root, "kb1", "raport.pdf", DATA)
    entry = BlobEntry(
        dest=StorageKey("filemanager/f1/original.pdf"),
        ref=BlobRef("kb1", "raport.pdf"),
        expected_size=len(DATA),
        owners=("file:f1",),
    )
    source = SourceFiles(root)
    storage = FilesystemStorage(tmp_path / "wd")
    new_keys: list[str] = []
    await copy_blob(storage, source, entry, dry_run=False, new_keys=new_keys)
    write_blob(root, "kb1", "raport.pdf", changed)
    assert len(changed) == entry.expected_size
    outcome = await copy_blob(storage, source, entry, dry_run=False, new_keys=new_keys)
    assert outcome.status == "copied"
    assert outcome.content_hash == xxhash.xxh128(changed).hexdigest()
    assert new_keys == [str(entry.dest)]
    assert await read_storage(storage, entry.dest) == changed


async def test_copy_blob_rewrites_when_stored_size_differs(tmp_path: Path) -> None:
    """Inny rozmiar w storage → kopiowanie od nowa, klucz nadal nie jest nowy."""
    root = tmp_path / "src"
    shorter = b"krotki"
    write_blob(root, "kb1", "raport.pdf", DATA)
    entry = BlobEntry(
        dest=StorageKey("filemanager/f1/original.pdf"),
        ref=BlobRef("kb1", "raport.pdf"),
        expected_size=len(DATA),
        owners=("file:f1",),
    )
    source = SourceFiles(root)
    storage = FilesystemStorage(tmp_path / "wd")
    new_keys: list[str] = []
    await copy_blob(storage, source, entry, dry_run=False, new_keys=new_keys)
    write_blob(root, "kb1", "raport.pdf", shorter)
    outcome = await copy_blob(
        storage,
        source,
        BlobEntry(entry.dest, entry.ref, len(shorter), entry.owners),
        dry_run=False,
        new_keys=new_keys,
    )
    assert outcome.status == "copied"
    assert new_keys == [str(entry.dest)]
    assert await read_storage(storage, entry.dest) == shorter


class BadHashStorage:
    """Atrapa storage: zapisuje, ale zwraca inny ``content_hash`` niż treść."""

    def __init__(self, root: Path) -> None:
        self.root = root

    async def exists(self, key: StorageKey) -> bool:
        return False

    def local_path(self, key: StorageKey) -> Path:
        return self.root / key

    async def put(
        self, key: StorageKey, data: Any, *, max_bytes: int | None = None
    ) -> StoredObject:
        size = 0
        async for chunk in data:
            size += len(chunk)
        return StoredObject(key, size, "0" * 32)


async def test_copy_blob_verification_failure_raises(tmp_path: Path) -> None:
    """Niezgodny ``content_hash`` po zapisie → ``RuntimeError`` z kluczem dest."""
    source, entry = source_with_raport(tmp_path)
    storage = BadHashStorage(tmp_path / "wd")
    new_keys: list[str] = []
    with pytest.raises(RuntimeError, match=f"blob copy verification failed: {entry.dest}"):
        await copy_blob(storage, source, entry, dry_run=False, new_keys=new_keys)


class CorruptingStorage:
    """Atrapa storage: zapisuje inne bajty, ale raportuje metadane źródła."""

    def __init__(self, backing: FilesystemStorage, *, size: int, content_hash: str) -> None:
        self._backing = backing
        self._size = size
        self._content_hash = content_hash

    async def exists(self, key: StorageKey) -> bool:
        return await self._backing.exists(key)

    def local_path(self, key: StorageKey) -> Path:
        return self._backing.local_path(key)

    def open(self, key: StorageKey, *, chunk_size: int = 1 << 20) -> Any:
        return self._backing.open(key, chunk_size=chunk_size)

    async def put(
        self, key: StorageKey, data: Any, *, max_bytes: int | None = None
    ) -> StoredObject:
        async for _ in data:
            pass
        await self._backing.put(key, b"?" * self._size)
        return StoredObject(key, self._size, self._content_hash)


async def test_copy_blob_readback_sha256_mismatch_raises(tmp_path: Path) -> None:
    """Inna treść w storage (mimo zgodnych metadanych) → ``RuntimeError``."""
    source, entry = source_with_raport(tmp_path)
    storage = CorruptingStorage(
        FilesystemStorage(tmp_path / "wd"),
        size=len(DATA),
        content_hash=xxhash.xxh128(DATA).hexdigest(),
    )
    new_keys: list[str] = []
    with pytest.raises(RuntimeError, match=f"blob copy verification failed: {entry.dest}"):
        await copy_blob(storage, source, entry, dry_run=False, new_keys=new_keys)
