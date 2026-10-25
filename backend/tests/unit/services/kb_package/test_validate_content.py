"""Testy walidacji treści paczki .wdkb (CONTRACT E7-1z §1-2) — luki walidatora.

Paczki buduje lokalny helper na ``zipfile`` + ``format.py``: po jednej na lukę z BRIEF.md §Zakres
p. 1. Każda wadliwa treść ``documents.jsonl``/``chunks.jsonl`` daje kod ``invalid_archive`` z nazwą
pliku, numerem linii (od 1) i polem. Testy NPY i ścieżki pinują zachowanie dotychczasowe.
"""

from __future__ import annotations

import hashlib
import io
import json
import struct
import zipfile
from pathlib import Path
from typing import Any

import pytest

from app.services.kb_package import format as fmt
from app.services.kb_package.validate import (
    DIMENSION_MISMATCH,
    INVALID_ARCHIVE,
    UNEXPECTED_ENTRY,
    PackageError,
    ValidatedPackage,
    validate_package,
)

MAX_BYTES = 100 * 1024 * 1024
MAX_RATIO = 100
DIMENSION = 4
BLOB = b"tresc dokumentu"
MISSING_SHA = "0" * 64


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _document(**over: Any) -> dict[str, Any]:
    """Linia ``documents.jsonl`` z poprawnymi polami; ``over`` nadpisuje wybrane."""
    line: dict[str, Any] = {
        "ref": "d1",
        "name": "raport.pdf",
        "type": "pdf",
        "suffix": "pdf",
        "size": len(BLOB),
        "file_sha256": _sha(BLOB),
        "chunk_method": "naive",
        "parser_config": {},
        "meta_fields": {},
        "run": "3",
        "progress_msg": "",
        "token_num": 10,
        "chunk_num": 1,
    }
    line.update(over)
    return line


def _chunk(**over: Any) -> dict[str, Any]:
    """Linia ``chunks.jsonl`` z poprawnymi polami; ``over`` nadpisuje wybrane."""
    line: dict[str, Any] = {
        "ref": "c1",
        "document_ref": "d1",
        "ordinal": 0,
        "chunk_type": "text",
        "content": "tresc chunka",
        "content_llm": None,
        "keywords": [],
        "questions": [],
        "tags": {},
        "positions": [],
        "page_from": None,
        "page_to": None,
        "image_sha256": None,
        "parent_ref": None,
        "available": True,
        "embed_source": "content",
        "token_count": 5,
    }
    line.update(over)
    return line


def _jsonl(objs: list[dict[str, Any]]) -> bytes:
    return b"".join(json.dumps(obj, ensure_ascii=False).encode() + b"\n" for obj in objs)


def _npy_bytes(rows: int, dimension: int = DIMENSION) -> bytes:
    buf = io.BytesIO()
    fmt.write_npy(buf, [[float(r) / 10 for _ in range(dimension)] for r in range(rows)], dimension)
    return buf.getvalue()


def _raw_npy(shape: str) -> bytes:
    """Surowy NPY 1.0 z dowolnym literałem kształtu (do testu niecałkowitych wymiarów)."""
    text = "{'descr': '<f4', 'fortran_order': False, 'shape': " + shape + ", }"
    header = text.encode("ascii") + b"\n"
    prefix = b"\x93NUMPY" + bytes((fmt.NPY_MAJOR, fmt.NPY_MINOR)) + struct.pack("<H", len(header))
    return prefix + header


def _manifest(
    *,
    entries: list[dict[str, Any]],
    documents: int,
    chunks: int,
    vectors: int,
    included: bool = True,
) -> dict[str, Any]:
    return {
        "format": fmt.FORMAT_NAME,
        "schema_version": fmt.SCHEMA_VERSION,
        "wd_version": "0.9.0",
        "created_at": "2026-10-13T21:00:00Z",
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
        "entries": entries,
    }


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    return info


def _entry(path: str, data: bytes) -> dict[str, Any]:
    return {"path": path, "sha256": _sha(data), "size": len(data)}


def _write_zip(path: Path, items: list[tuple[str, bytes]]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in items:
            zf.writestr(_zip_info(name), data)
    return path


def _package(  # noqa: PLR0913 — wszystkie warianty paczki sterowane testem
    tmp_path: Path,
    *,
    documents: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    blob: bool = True,
    vectors: bool = True,
    included: bool = True,
    counts_vectors: int | None = None,
    extra: list[tuple[str, bytes]] | None = None,
    vector_bytes: bytes | None = None,
    name: str = "pkg.wdkb.zip",
) -> Path:
    """Buduje paczkę z podaną treścią JSONL; ``blob``/``vectors`` sterują obecnością wpisów."""
    items: list[tuple[str, bytes]] = [
        (fmt.DOCUMENTS_PATH, _jsonl(documents)),
        (fmt.CHUNKS_PATH, _jsonl(chunks)),
    ]
    if vectors:
        items.append((fmt.vector_part_path(0), vector_bytes or _npy_bytes(len(chunks))))
    if blob:
        items.append((fmt.FILES_PREFIX + _sha(BLOB), BLOB))
    items.extend(extra or [])
    manifest = _manifest(
        entries=[_entry(path, data) for path, data in items],
        documents=len(documents),
        chunks=len(chunks),
        vectors=len(chunks) if counts_vectors is None else counts_vectors,
        included=included,
    )
    items.append((fmt.MANIFEST_PATH, json.dumps(manifest, ensure_ascii=False).encode()))
    return _write_zip(tmp_path / name, items)


def _errors(path: Path) -> list[PackageError]:
    result = validate_package(path, max_bytes=MAX_BYTES, max_ratio=MAX_RATIO)
    assert isinstance(result, list), f"oczekiwano listy błędów, jest {result!r}"
    assert all(isinstance(e, PackageError) for e in result)
    return result


# --- paczka poprawna (sanity) --------------------------------------------------------------


def test_poprawna_paczka_z_trescia_jest_ok(tmp_path: Path) -> None:
    path = _package(tmp_path, documents=[_document()], chunks=[_chunk()])

    result = validate_package(path, max_bytes=MAX_BYTES, max_ratio=MAX_RATIO)

    assert isinstance(result, ValidatedPackage)


# --- luki z BRIEF.md §Zakres p. 1 (czerwone przed implementacją) ----------------------------


def test_file_sha256_bez_wpisu_bloba_to_invalid_archive(tmp_path: Path) -> None:
    # documents.jsonl wskazuje blob, którego nie ma jako files/<sha> w entries
    path = _package(
        tmp_path, documents=[_document(file_sha256=MISSING_SHA)], chunks=[_chunk()], blob=False
    )

    errors = _errors(path)

    assert [e.code for e in errors] == [INVALID_ARCHIVE]
    assert "documents.jsonl, linia 1" in errors[0].message
    assert "file_sha256" in errors[0].message
    assert MISSING_SHA in errors[0].message


def test_image_sha256_bez_wpisu_obrazu_to_invalid_archive(tmp_path: Path) -> None:
    path = _package(
        tmp_path,
        documents=[_document()],
        chunks=[_chunk(image_sha256=MISSING_SHA)],
    )

    errors = _errors(path)

    assert [e.code for e in errors] == [INVALID_ARCHIVE]
    assert "chunks.jsonl, linia 1" in errors[0].message
    assert "image_sha256" in errors[0].message


def test_embed_source_spoza_zbioru_to_invalid_archive(tmp_path: Path) -> None:
    path = _package(tmp_path, documents=[_document()], chunks=[_chunk(embed_source="foo")])

    errors = _errors(path)

    assert [e.code for e in errors] == [INVALID_ARCHIVE]
    assert "chunks.jsonl, linia 1" in errors[0].message
    assert "embed_source" in errors[0].message


def test_chunk_type_spoza_enum_to_invalid_archive(tmp_path: Path) -> None:
    path = _package(tmp_path, documents=[_document()], chunks=[_chunk(chunk_type="foo")])

    errors = _errors(path)

    assert [e.code for e in errors] == [INVALID_ARCHIVE]
    assert "chunks.jsonl, linia 1" in errors[0].message
    assert "chunk_type" in errors[0].message


def test_wiszacy_document_ref_to_invalid_archive(tmp_path: Path) -> None:
    path = _package(tmp_path, documents=[_document()], chunks=[_chunk(document_ref="d99")])

    errors = _errors(path)

    assert [e.code for e in errors] == [INVALID_ARCHIVE]
    assert "chunks.jsonl, linia 1" in errors[0].message
    assert "document_ref" in errors[0].message
    assert "d99" in errors[0].message


def test_wiszacy_parent_ref_to_invalid_archive(tmp_path: Path) -> None:
    path = _package(tmp_path, documents=[_document()], chunks=[_chunk(parent_ref="c99")])

    errors = _errors(path)

    assert [e.code for e in errors] == [INVALID_ARCHIVE]
    assert "chunks.jsonl, linia 1" in errors[0].message
    assert "parent_ref" in errors[0].message
    assert "c99" in errors[0].message


def test_zduplikowany_ref_w_chunkach_to_invalid_archive(tmp_path: Path) -> None:
    path = _package(
        tmp_path,
        documents=[_document()],
        chunks=[_chunk(ref="c1"), _chunk(ref="c1", ordinal=1)],
    )

    errors = _errors(path)

    assert [e.code for e in errors] == [INVALID_ARCHIVE]
    assert "chunks.jsonl, linia 2" in errors[0].message
    assert "ref" in errors[0].message


def test_zduplikowany_ref_w_dokumentach_to_invalid_archive(tmp_path: Path) -> None:
    path = _package(
        tmp_path,
        documents=[_document(ref="d1"), _document(ref="d1", name="drugi.pdf")],
        chunks=[_chunk()],
    )

    errors = _errors(path)

    assert [e.code for e in errors] == [INVALID_ARCHIVE]
    assert "documents.jsonl, linia 2" in errors[0].message
    assert "ref" in errors[0].message


def test_wektory_bez_wpisow_przy_zeru_chunkow_to_invalid_archive(tmp_path: Path) -> None:
    # included=true i counts.vectors>0, ale paczka nie ma żadnego vectors/* — nawet gdy chunks=0
    path = _package(
        tmp_path,
        documents=[],
        chunks=[],
        vectors=False,
        included=True,
        counts_vectors=3,
    )

    errors = _errors(path)

    assert [e.code for e in errors] == [INVALID_ARCHIVE]


def test_zla_linia_json_w_chunks_to_invalid_archive(tmp_path: Path) -> None:
    # malformed JSON na drugiej linii: nazwa pliku i numer linii w komunikacie
    items = [
        (fmt.DOCUMENTS_PATH, _jsonl([_document()])),
        (fmt.CHUNKS_PATH, _jsonl([_chunk()]) + b"{to nie json\n"),
        (fmt.FILES_PREFIX + _sha(BLOB), BLOB),
        (fmt.vector_part_path(0), _npy_bytes(2)),
    ]
    manifest = _manifest(
        entries=[_entry(path, data) for path, data in items],
        documents=1,
        chunks=2,
        vectors=2,
    )
    items.append((fmt.MANIFEST_PATH, json.dumps(manifest).encode()))
    path = _write_zip(tmp_path / "zla-linia.wdkb.zip", items)

    errors = _errors(path)

    assert [e.code for e in errors] == [INVALID_ARCHIVE]
    assert "chunks.jsonl, linia 2" in errors[0].message


# --- pin: ścieżka wpisu i kształt NPY (kod dotychczasowy) ----------------------------------


def test_sciezka_z_doklejona_nowa_linia_to_unexpected_entry(tmp_path: Path) -> None:
    """K20 §2: nazwa bezpieczna, ale spoza formatu paczki → ``unexpected_entry``."""
    path = _package(
        tmp_path,
        documents=[_document()],
        chunks=[_chunk()],
        extra=[("documents.jsonl\n", b"x")],
    )

    errors = _errors(path)

    assert [e.code for e in errors] == [UNEXPECTED_ENTRY]
    assert "documents.jsonl" in errors[0].message


def test_npy_z_niecalkowitym_ksztaltem_to_dimension_mismatch(tmp_path: Path) -> None:
    path = _package(
        tmp_path,
        documents=[_document()],
        chunks=[_chunk()],
        vector_bytes=_raw_npy("(1.0, 4)"),
    )

    errors = _errors(path)

    assert [e.code for e in errors] == [DIMENSION_MISMATCH]


def test_read_npy_header_odrzuca_niecalkowity_ksztalt() -> None:
    with pytest.raises(ValueError):
        fmt.read_npy_header(io.BytesIO(_raw_npy("('1', 4)")))


# --- luki nie należące do walidatora treści ------------------------------------------------


def test_brak_chunkow_dla_dokumentu_nie_jest_bledem_tresci(tmp_path: Path) -> None:
    """Dokument bez chunków to poprawna treść (liczniki pilnuje manifest)."""
    path = _package(
        tmp_path,
        documents=[_document()],
        chunks=[],
        vectors=False,
        included=True,
        counts_vectors=0,
    )

    result = validate_package(path, max_bytes=MAX_BYTES, max_ratio=MAX_RATIO)

    assert isinstance(result, ValidatedPackage)
