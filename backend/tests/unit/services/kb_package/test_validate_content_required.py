"""Pola wymagane w liniach paczki .wdkb (CONTRACT E7-1z §1, MINOR T1).

Wydzielone z ``test_validate_content.py`` (bramka 400 linii/plik). Brak, ``None`` albo pusty string
pola ``ref``/``document_ref``/``chunk_type``/``tags`` w linii ``documents.jsonl``/``chunks.jsonl``
ma dawać ``invalid_archive`` z nazwą pliku, numerem linii (od 1) i polem — nigdy 500
z ``ValidationError`` w ``build_summary``. Pusty string w polu wymaganym to jak brak pola
(E7-1z MINOR, CONTRACT E7-1z §1). ``parent_ref`` równy własnemu ``ref`` to też ``invalid_archive``.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from app.services.kb_package import format as fmt
from app.services.kb_package.validate import INVALID_ARCHIVE, PackageError, validate_package

MAX_BYTES = 100 * 1024 * 1024
MAX_RATIO = 100
DIMENSION = 4


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _document(**over: Any) -> dict[str, Any]:
    """Linia ``documents.jsonl`` z poprawnymi polami; ``over`` nadpisuje wybrane."""
    line: dict[str, Any] = {
        "ref": "d1",
        "name": "raport.pdf",
        "type": "pdf",
        "suffix": "pdf",
        "size": 0,
        "file_sha256": None,
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


def _manifest(*, documents: int, chunks: int, entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "format": fmt.FORMAT_NAME,
        "schema_version": fmt.SCHEMA_VERSION,
        "wd_version": "0.9.0",
        "created_at": "2026-10-13T21:00:00Z",
        "source_instance_id": "0123456789abcdef0123456789abcdef",
        "dataset": {
            "name": "Baza wymagana",
            "description": None,
            "language": "Polish",
            "chunk_method": "naive",
            "parser_config": {},
            "similarity_threshold": 0.2,
            "vector_similarity_weight": 0.3,
            "pagerank": 0,
        },
        "embedding": {"model_name": "bge-m3", "dimension": DIMENSION, "included": False},
        "counts": {"documents": documents, "chunks": chunks, "vectors": 0},
        "entries": entries,
    }


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    return info


def _package(
    tmp_path: Path, *, documents: list[dict[str, Any]], chunks: list[dict[str, Any]]
) -> Path:
    """Paczka bez wektorów i bloba: liczy się wyłącznie treść ``documents``/``chunks`` JSONL."""
    items: list[tuple[str, bytes]] = [
        (fmt.DOCUMENTS_PATH, _jsonl(documents)),
        (fmt.CHUNKS_PATH, _jsonl(chunks)),
    ]
    manifest = _manifest(
        documents=len(documents),
        chunks=len(chunks),
        entries=[{"path": path, "sha256": _sha(data), "size": len(data)} for path, data in items],
    )
    items.append((fmt.MANIFEST_PATH, json.dumps(manifest, ensure_ascii=False).encode()))
    path = tmp_path / "wymagane.wdkb.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in items:
            zf.writestr(_zip_info(name), data)
    return path


def _errors(path: Path) -> list[PackageError]:
    result = validate_package(path, max_bytes=MAX_BYTES, max_ratio=MAX_RATIO)
    assert isinstance(result, list), f"oczekiwano listy błędów, jest {result!r}"
    assert all(isinstance(e, PackageError) for e in result)
    return result


# --- pola wymagane: brak i None ------------------------------------------------------------


def test_document_bez_ref_to_invalid_archive(tmp_path: Path) -> None:
    line = _document()
    del line["ref"]
    path = _package(tmp_path, documents=[line], chunks=[])

    errors = _errors(path)

    assert [e.code for e in errors] == [INVALID_ARCHIVE]
    assert errors[0].message == "documents.jsonl, linia 1: ref — brak"


def test_document_z_ref_none_to_invalid_archive(tmp_path: Path) -> None:
    path = _package(tmp_path, documents=[_document(ref=None)], chunks=[])

    errors = _errors(path)

    assert errors[0].message == "documents.jsonl, linia 1: ref — brak"


def test_chunk_bez_document_ref_to_invalid_archive(tmp_path: Path) -> None:
    path = _package(tmp_path, documents=[_document()], chunks=[_chunk(document_ref=None)])

    errors = _errors(path)

    assert [e.code for e in errors] == [INVALID_ARCHIVE]
    assert errors[0].message == "chunks.jsonl, linia 1: document_ref — brak"


def test_chunk_bez_chunk_type_to_invalid_archive(tmp_path: Path) -> None:
    line = _chunk()
    del line["chunk_type"]
    path = _package(tmp_path, documents=[_document()], chunks=[line])

    errors = _errors(path)

    assert errors[0].message == "chunks.jsonl, linia 1: chunk_type — brak"


def test_chunk_bez_ref_to_invalid_archive(tmp_path: Path) -> None:
    path = _package(tmp_path, documents=[_document()], chunks=[_chunk(ref=None)])

    errors = _errors(path)

    assert errors[0].message == "chunks.jsonl, linia 1: ref — brak"


def test_brak_pola_wskazuje_numer_drugiej_linii(tmp_path: Path) -> None:
    """Błąd wskazuje linię wadliwą (2.), nie pierwszą poprawną."""
    path = _package(
        tmp_path,
        documents=[_document()],
        chunks=[_chunk(), _chunk(ref=None, ordinal=1)],
    )

    errors = _errors(path)

    assert errors[0].message == "chunks.jsonl, linia 2: ref — brak"


# --- pola wymagane: pusty string traktowany jak brak (E7-1z MINOR) --------------------------


def test_document_z_pustym_ref_to_invalid_archive(tmp_path: Path) -> None:
    """Pusty string w ``ref`` dokumentu → ``invalid_archive`` jak dla brakującego pola."""
    path = _package(tmp_path, documents=[_document(ref="")], chunks=[])

    errors = _errors(path)

    assert [e.code for e in errors] == [INVALID_ARCHIVE]
    assert errors[0].message == "documents.jsonl, linia 1: ref — brak"


def test_chunk_z_pustym_ref_to_invalid_archive(tmp_path: Path) -> None:
    path = _package(tmp_path, documents=[_document()], chunks=[_chunk(ref="")])

    errors = _errors(path)

    assert errors[0].message == "chunks.jsonl, linia 1: ref — brak"


def test_chunk_z_pustym_document_ref_to_invalid_archive(tmp_path: Path) -> None:
    path = _package(tmp_path, documents=[_document()], chunks=[_chunk(document_ref="")])

    errors = _errors(path)

    assert errors[0].message == "chunks.jsonl, linia 1: document_ref — brak"


def test_chunk_z_pustym_chunk_type_to_invalid_archive(tmp_path: Path) -> None:
    path = _package(tmp_path, documents=[_document()], chunks=[_chunk(chunk_type="")])

    errors = _errors(path)

    assert errors[0].message == "chunks.jsonl, linia 1: chunk_type — brak"


def test_chunk_z_pustymi_tags_to_invalid_archive(tmp_path: Path) -> None:
    """Pusty string w ``tags`` (pole wymagane) → ``invalid_archive`` jak dla brakującego pola."""
    path = _package(tmp_path, documents=[_document()], chunks=[_chunk(tags="")])

    errors = _errors(path)

    assert [e.code for e in errors] == [INVALID_ARCHIVE]
    assert errors[0].message == "chunks.jsonl, linia 1: tags — brak"


# --- parent_ref wskazujący własny ref ------------------------------------------------------


def test_parent_ref_rownajacy_wlasnemu_ref_to_invalid_archive(tmp_path: Path) -> None:
    path = _package(tmp_path, documents=[_document()], chunks=[_chunk(ref="c1", parent_ref="c1")])

    errors = _errors(path)

    assert [e.code for e in errors] == [INVALID_ARCHIVE]
    assert errors[0].message == "chunks.jsonl, linia 1: parent_ref — odwołuje się do samego siebie"
