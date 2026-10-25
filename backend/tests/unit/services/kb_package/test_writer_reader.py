"""Testy PackageWriter/PackageReader (K19 §2, CONTRACT §2/§4) — round-trip przez walidator.

Paczki buduje ``PackageWriter``, wynik waliduje ``validate_package`` (pełny round-trip
writer→validate→reader), zgodnie z briefem T3 — walidator T4 jest już scalony w bazie.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from app.services.kb_package import format as fmt
from app.services.kb_package.reader import PackageReader
from app.services.kb_package.validate import ValidatedPackage, validate_package
from app.services.kb_package.writer import PackageWriter

MAX_BYTES = 100 * 1024 * 1024
MAX_RATIO = 100
DIMENSION = 4
FILE_DATA = b"oryginal dokumentu"
PART_ROWS = fmt.VECTOR_PART_ROWS
DOCUMENTS = 2
CHUNKS = 3
STREAM_PARTS = (b"abc", b"defg")


def _document(ref: str) -> dict[str, Any]:
    """Linia documents.jsonl wg K19 §2."""
    return {
        "ref": ref,
        "name": f"{ref}.pdf",
        "type": "pdf",
        "suffix": "pdf",
        "size": 1024,
        "file_sha256": None,
        "chunk_method": "naive",
        "parser_config": {},
        "meta_fields": {},
        "run": "3",  # DONE — run surowe (K19 §2)
        "progress_msg": "",
        "token_num": 10,
        "chunk_num": 1,
    }


def _chunk(ref: str, document_ref: str, ordinal: int) -> dict[str, Any]:
    """Linia chunks.jsonl wg K19 §2."""
    return {
        "ref": ref,
        "document_ref": document_ref,
        "ordinal": ordinal,
        "chunk_type": "text",
        "content": f"treść {ref}",
        "content_llm": None,
        "keywords": [],
        "questions": [],
        "tags": {},
        "positions": None,
        "page_from": None,
        "page_to": None,
        "image_sha256": None,
        "parent_ref": None,
        "available": True,
        "embed_source": None,
        "token_count": 5,
    }


def _jsonl(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(json.dumps(row, ensure_ascii=False).encode("utf-8") + b"\n" for row in rows)


def _npy(rows: list[list[float]]) -> bytes:
    buf = io.BytesIO()
    fmt.write_npy(buf, rows, DIMENSION)
    return buf.getvalue()


def _manifest(*, documents: int, chunks: int, vectors: int, included: bool = True) -> fmt.Manifest:
    """Manifest wg K19 §2; ``entries`` uzupełnia writer w ``finish``."""
    return fmt.Manifest.model_validate(
        {
            "format": fmt.FORMAT_NAME,
            "schema_version": fmt.SCHEMA_VERSION,
            "wd_version": "0.9.0",
            "created_at": "2026-10-12T21:00:00Z",
            "source_instance_id": "0123456789abcdef0123456789abcdef",
            "dataset": {
                "name": "Baza testowa",
                "description": None,
                "language": "Polish",
                "chunk_method": "naive",
                "parser_config": {},
                "similarity_threshold": 0.2,
                "vector_similarity_weight": 0.3,
                "pagerank": 0,
            },
            "embedding": {"model_name": "bge-m3", "dimension": DIMENSION, "included": included},
            "counts": {"documents": documents, "chunks": chunks, "vectors": vectors},
            "entries": [],
        }
    )


def _standard_package(
    final: Path, *, max_bytes: int = MAX_BYTES
) -> tuple[fmt.Manifest, dict[str, bytes], int, str]:
    """Buduje standardową paczkę: 2 dokumenty, 3 chunki, 3 wektory, 1 plik."""
    file_sha = hashlib.sha256(FILE_DATA).hexdigest()
    blobs = {
        fmt.DOCUMENTS_PATH: _jsonl([_document("d1"), _document("d2")]),
        fmt.CHUNKS_PATH: _jsonl(
            [_chunk("c1", "d1", 0), _chunk("c2", "d1", 1), _chunk("c3", "d2", 0)]
        ),
        fmt.vector_part_path(0): _npy(
            [[0.0, 0.1, 0.2, 0.3], [1.0, 1.1, 1.2, 1.3], [2.0, 2.1, 2.2, 2.3]]
        ),
        f"{fmt.FILES_PREFIX}{file_sha}": FILE_DATA,
    }
    writer = PackageWriter(final, max_bytes=max_bytes)
    for path, data in blobs.items():
        writer.add_bytes(path, data)
    manifest = _manifest(documents=DOCUMENTS, chunks=CHUNKS, vectors=CHUNKS)
    size = writer.finish(manifest)
    return manifest, blobs, size, file_sha


def test_round_trip_writer_validate_reader(tmp_path: Path) -> None:
    """Writer → validate → reader: plik istnieje, .part nie, wpisy i zawartość zgodne."""
    final = tmp_path / "baza.wdkb.zip"
    manifest, blobs, size, file_sha = _standard_package(final)
    part = final.with_name(final.name + ".part")

    assert final.is_file()
    assert not part.exists()
    assert size == final.stat().st_size

    with zipfile.ZipFile(final) as zf:
        assert set(zf.namelist()) == {fmt.MANIFEST_PATH, *blobs}

    assert [entry.path for entry in manifest.entries] == list(blobs)
    for entry in manifest.entries:
        data = blobs[entry.path]
        assert entry.sha256 == hashlib.sha256(data).hexdigest()
        assert entry.size == len(data)

    pkg = validate_package(final, max_bytes=MAX_BYTES, max_ratio=MAX_RATIO)
    assert isinstance(pkg, ValidatedPackage), pkg
    reader = PackageReader(pkg)

    documents = list(reader.documents())
    chunks = list(reader.chunks())
    vectors = list(reader.vectors())
    assert [doc.ref for doc in documents] == ["d1", "d2"]
    assert [chunk.ref for chunk in chunks] == ["c1", "c2", "c3"]
    assert len(vectors) == CHUNKS
    assert vectors[1][0] == pytest.approx(1.0)
    assert chunks[0].available is True
    assert documents[0].name == "d1.pdf"

    with reader.open_entry(f"{fmt.FILES_PREFIX}{file_sha}") as fp:
        assert fp.read() == FILE_DATA


def test_vectors_more_than_one_part_round_trip(tmp_path: Path) -> None:
    """10001 wektorów w 2 częściach (10000+1) → ``vectors()`` zwraca 10001 w kolejności."""
    final = tmp_path / "duza.wdkb.zip"
    count = PART_ROWS + 1
    first = [[float(index) for _ in range(DIMENSION)] for index in range(PART_ROWS)]
    second = [[float(PART_ROWS) for _ in range(DIMENSION)]]
    blobs = {
        fmt.DOCUMENTS_PATH: _jsonl([_document("d1")]),
        fmt.CHUNKS_PATH: _jsonl([_chunk(f"c{i}", "d1", i) for i in range(count)]),
        fmt.vector_part_path(0): _npy(first),
        fmt.vector_part_path(1): _npy(second),
    }
    writer = PackageWriter(final, max_bytes=MAX_BYTES)
    for path, data in blobs.items():
        writer.add_bytes(path, data)
    manifest = _manifest(documents=1, chunks=count, vectors=count)
    writer.finish(manifest)

    pkg = validate_package(final, max_bytes=MAX_BYTES, max_ratio=MAX_RATIO)
    assert isinstance(pkg, ValidatedPackage), pkg
    vectors = list(PackageReader(pkg).vectors())
    assert len(vectors) == count
    assert [row[0] for row in vectors] == [float(i) for i in range(count)]


def test_vectors_empty_when_not_included(tmp_path: Path) -> None:
    """``embedding.included=false`` → ``vectors()`` jest pusty."""
    final = tmp_path / "bez-wektorow.wdkb.zip"
    writer = PackageWriter(final, max_bytes=MAX_BYTES)
    writer.add_bytes(fmt.DOCUMENTS_PATH, _jsonl([_document("d1")]))
    writer.add_bytes(fmt.CHUNKS_PATH, _jsonl([_chunk("c1", "d1", 0)]))
    manifest = _manifest(documents=1, chunks=1, vectors=0, included=False)
    writer.finish(manifest)

    pkg = validate_package(final, max_bytes=MAX_BYTES, max_ratio=MAX_RATIO)
    assert isinstance(pkg, ValidatedPackage), pkg
    assert list(PackageReader(pkg).vectors()) == []


def test_add_file_streams_chunks(tmp_path: Path) -> None:
    """``add_file`` czyta iterowalny strumień porcjami i liczy SHA-256/size w locie."""
    final = tmp_path / "strumien.wdkb.zip"
    writer = PackageWriter(final, max_bytes=MAX_BYTES)

    def stream() -> Any:
        yield from STREAM_PARTS

    entry = writer.add_file("documents.jsonl", stream())
    joined = b"".join(STREAM_PARTS)
    assert entry.size == len(joined)
    assert entry.sha256 == hashlib.sha256(joined).hexdigest()
    writer.abort()


def test_add_file_rejects_bad_path_and_duplicate(tmp_path: Path) -> None:
    """Ścieżka spoza ``ENTRY_PATH_RE`` i duplikat → ``ValueError``."""
    writer = PackageWriter(tmp_path / "zly.wdkb.zip", max_bytes=MAX_BYTES)
    with pytest.raises(ValueError):
        writer.add_file("../x", [b"a"])
    with pytest.raises(ValueError):
        writer.add_bytes("files/zz", b"a")
    writer.add_bytes(fmt.DOCUMENTS_PATH, b"a")
    with pytest.raises(ValueError):
        writer.add_bytes(fmt.DOCUMENTS_PATH, b"b")
    writer.abort()


def test_add_file_rejects_over_max_bytes(tmp_path: Path) -> None:
    """Suma rozmiarów > ``max_bytes`` → ``ValueError`` i ``.part`` znika (automatyczny abort)."""
    final = tmp_path / "limit.wdkb.zip"
    part = final.with_name(final.name + ".part")
    writer = PackageWriter(final, max_bytes=10)
    with pytest.raises(ValueError):
        writer.add_bytes(fmt.DOCUMENTS_PATH, b"x" * 20)
    assert not part.exists()
    assert not final.exists()


def test_finish_counts_manifest_against_max_bytes(tmp_path: Path) -> None:
    """``max_bytes`` obejmuje ``manifest.json``: wpisy mieszczą się, ale manifest już nie → błąd."""
    final = tmp_path / "manifest-limit.wdkb.zip"
    part = final.with_name(final.name + ".part")
    data = _jsonl([_document("d1")])
    writer = PackageWriter(final, max_bytes=len(data) + 1)
    writer.add_bytes(fmt.DOCUMENTS_PATH, data)  # sam wpis mieści się w limicie
    with pytest.raises(ValueError):
        writer.finish(_manifest(documents=1, chunks=0, vectors=0, included=False))
    assert not part.exists()
    assert not final.exists()


def test_abort_removes_part_and_is_idempotent(tmp_path: Path) -> None:
    """``abort`` usuwa .part i nie rzuca, gdy pliku już nie ma."""
    final = tmp_path / "przerwany.wdkb.zip"
    writer = PackageWriter(final, max_bytes=MAX_BYTES)
    part = final.with_name(final.name + ".part")
    writer.add_bytes(fmt.DOCUMENTS_PATH, b"a")
    assert part.exists()
    writer.abort()
    assert not part.exists()
    assert not final.exists()
    writer.abort()


def test_finish_creates_missing_parent_dirs(tmp_path: Path) -> None:
    """Brak katalogu rodzica ``final_path`` → writer tworzy go (``mkdir(parents=True)``)."""
    final = tmp_path / "zagniezdzony" / "katalog" / "baza.wdkb.zip"
    writer = PackageWriter(final, max_bytes=MAX_BYTES)
    writer.add_bytes(fmt.DOCUMENTS_PATH, _jsonl([_document("d1")]))
    writer.add_bytes(fmt.CHUNKS_PATH, _jsonl([_chunk("c1", "d1", 0)]))
    writer.add_bytes(fmt.vector_part_path(0), _npy([[0.0, 1.0, 2.0, 3.0]]))
    writer.finish(_manifest(documents=1, chunks=1, vectors=1))
    assert final.is_file()


def test_finish_overwrites_given_entries(tmp_path: Path) -> None:
    """``finish`` nadpisuje ``manifest.entries`` wpisami zebranymi w kolejności dodania."""
    final = tmp_path / "wpisy.wdkb.zip"
    writer = PackageWriter(final, max_bytes=MAX_BYTES)
    writer.add_bytes(fmt.CHUNKS_PATH, _jsonl([_chunk("c1", "d1", 0)]))
    writer.add_bytes(fmt.DOCUMENTS_PATH, _jsonl([_document("d1")]))
    writer.add_bytes(fmt.vector_part_path(0), _npy([[0.0, 1.0, 2.0, 3.0]]))
    manifest = _manifest(documents=1, chunks=1, vectors=1)
    manifest.entries = [fmt.ManifestEntry(path=fmt.MANIFEST_PATH, sha256="0" * 64, size=1)]
    writer.finish(manifest)
    assert [entry.path for entry in manifest.entries] == [
        fmt.CHUNKS_PATH,
        fmt.DOCUMENTS_PATH,
        fmt.vector_part_path(0),
    ]


def test_open_entry_unknown_path_raises_keyerror(tmp_path: Path) -> None:
    """Ścieżka spoza ``manifest.entries`` → ``KeyError``."""
    final = tmp_path / "wpisy.wdkb.zip"
    _standard_package(final)
    pkg = validate_package(final, max_bytes=MAX_BYTES, max_ratio=MAX_RATIO)
    assert isinstance(pkg, ValidatedPackage), pkg
    reader = PackageReader(pkg)
    with pytest.raises(KeyError):
        reader.open_entry("files/" + "0" * 64)


def test_deterministic_zip(tmp_path: Path) -> None:
    """Dwa zapisy tych samych danych dają identyczny SHA-256 pliku (stałe ``created_at``)."""
    first = tmp_path / "a.wdkb.zip"
    second = tmp_path / "b.wdkb.zip"
    _standard_package(first)
    _standard_package(second)
    assert (
        hashlib.sha256(first.read_bytes()).hexdigest()
        == hashlib.sha256(second.read_bytes()).hexdigest()
    )
