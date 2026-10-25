"""Typy pól linii paczki .wdkb w walidatorze treści (T12, DEC-341) — ``tags`` i mapowanie modeli.

Defekt z e2e SC-E7-2-06: eksport zapisuje ``"tags": []`` (kolumna ``chunks.tags`` = JSON-lista,
DDL-default ``'[]'``), a ``ChunkLine.tags`` przyjmował wyłącznie obiekt — ``PUT .../content``
kończył się 500 ``internal_error``. Tu pinujemy: (a) ``tags`` lista przechodzi walidację i parsuje
się do ``ChunkLine``, (b) ``tags`` ani lista, ani obiekt → ``invalid_archive`` z polem ``tags``,
(c) wartość niezgodna z modelem linii (``ChunkLine``/``DocumentLine``) → ``invalid_archive``, nie
``ValidationError`` z ``build_summary``.

Wydzielone z ``test_validate_content.py`` (bramka 400 linii/plik).
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from app.services.kb_package import format as fmt
from app.services.kb_package.reader import PackageReader
from app.services.kb_package.validate import (
    INVALID_ARCHIVE,
    PackageError,
    ValidatedPackage,
    validate_package,
)

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
        "tags": [],
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
    manifest = {
        "format": fmt.FORMAT_NAME,
        "schema_version": fmt.SCHEMA_VERSION,
        "wd_version": "0.9.0",
        "created_at": "2026-10-13T21:00:00Z",
        "source_instance_id": "0123456789abcdef0123456789abcdef",
        "dataset": {
            "name": "Baza typów",
            "description": None,
            "language": "Polish",
            "chunk_method": "naive",
            "parser_config": {},
            "similarity_threshold": 0.2,
            "vector_similarity_weight": 0.3,
            "pagerank": 0,
        },
        "embedding": {"model_name": "bge-m3", "dimension": DIMENSION, "included": False},
        "counts": {"documents": len(documents), "chunks": len(chunks), "vectors": 0},
        "entries": [
            {"path": path, "sha256": _sha(data), "size": len(data)} for path, data in items
        ],
    }
    items.append((fmt.MANIFEST_PATH, json.dumps(manifest, ensure_ascii=False).encode()))
    path = tmp_path / "typy.wdkb.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in items:
            zf.writestr(_zip_info(name), data)
    return path


def _errors(path: Path) -> list[PackageError]:
    result = validate_package(path, max_bytes=MAX_BYTES, max_ratio=MAX_RATIO)
    assert isinstance(result, list), f"oczekiwano listy błędów, jest {result!r}"
    assert all(isinstance(e, PackageError) for e in result)
    return result


# --- tags: oba kształty JSON ---------------------------------------------------------------


def test_tags_lista_z_bazy_przechodzi_i_parsuje_sie_do_chunkline(tmp_path: Path) -> None:
    """``tags: []`` (DDL-default ``chunks.tags``) przechodzi walidację ORAZ ``ChunkLine`` (T12)."""
    path = _package(tmp_path, documents=[_document()], chunks=[_chunk(tags=[])])

    result = validate_package(path, max_bytes=MAX_BYTES, max_ratio=MAX_RATIO)

    assert isinstance(result, ValidatedPackage), result
    assert next(iter(PackageReader(result).chunks())).tags == []


def test_tags_niepusta_lista_przechodzi(tmp_path: Path) -> None:
    """``tags`` z niepustą listą (edycja tagów chunka) też przechodzi walidację (T12)."""
    path = _package(tmp_path, documents=[_document()], chunks=[_chunk(tags=["umowa", "najem"])])

    result = validate_package(path, max_bytes=MAX_BYTES, max_ratio=MAX_RATIO)

    assert isinstance(result, ValidatedPackage), result
    assert next(iter(PackageReader(result).chunks())).tags == ["umowa", "najem"]


def test_tags_obiekt_nadal_przechodzi(tmp_path: Path) -> None:
    """Obiekt ``tags`` (tag_feas RAGFlow) bez zmiany zachowania (T12)."""
    path = _package(tmp_path, documents=[_document()], chunks=[_chunk(tags={"autor": "Jan"})])

    result = validate_package(path, max_bytes=MAX_BYTES, max_ratio=MAX_RATIO)

    assert isinstance(result, ValidatedPackage), result


def test_tags_tekst_to_invalid_archive(tmp_path: Path) -> None:
    """``tags`` ani lista, ani obiekt → ``invalid_archive`` z polem ``tags``, nie 500 (T12)."""
    path = _package(tmp_path, documents=[_document()], chunks=[_chunk(tags="umowa")])

    errors = _errors(path)

    assert [e.code for e in errors] == [INVALID_ARCHIVE]
    assert "chunks.jsonl, linia 1" in errors[0].message
    assert "tags" in errors[0].message


def test_tags_liczba_to_invalid_archive(tmp_path: Path) -> None:
    """``tags`` liczba (inny zły typ JSON) → ``invalid_archive`` z polem ``tags`` (T12)."""
    path = _package(tmp_path, documents=[_document()], chunks=[_chunk(tags=5)])

    errors = _errors(path)

    assert [e.code for e in errors] == [INVALID_ARCHIVE]
    assert errors[0].message.startswith("chunks.jsonl, linia 1: tags")


def test_brak_tags_to_invalid_archive(tmp_path: Path) -> None:
    """Brak ``tags`` w linii chunka → ``invalid_archive`` (pole wymagane przez ``ChunkLine``)."""
    line = _chunk()
    del line["tags"]
    path = _package(tmp_path, documents=[_document()], chunks=[line])

    errors = _errors(path)

    assert errors[0].message == "chunks.jsonl, linia 1: tags — brak"


# --- wartości niezgodne z modelem linii → invalid_archive, nie 500 --------------------------


def test_zly_typ_pola_chunka_to_invalid_archive(tmp_path: Path) -> None:
    """``ordinal`` tekstem → ``invalid_archive`` z polem, zamiast ``ValidationError`` (T12)."""
    path = _package(tmp_path, documents=[_document()], chunks=[_chunk(ordinal="pierwszy")])

    errors = _errors(path)

    assert [e.code for e in errors] == [INVALID_ARCHIVE]
    assert "chunks.jsonl, linia 1" in errors[0].message
    assert "ordinal" in errors[0].message


def test_zly_typ_pola_dokumentu_to_invalid_archive(tmp_path: Path) -> None:
    """``size`` tekstem w ``documents.jsonl`` → ``invalid_archive`` z polem ``size`` (T12)."""
    path = _package(tmp_path, documents=[_document(size="duży")], chunks=[_chunk()])

    errors = _errors(path)

    assert [e.code for e in errors] == [INVALID_ARCHIVE]
    assert "documents.jsonl, linia 1" in errors[0].message
    assert "size" in errors[0].message
