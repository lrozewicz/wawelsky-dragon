"""Wpisy plikowe paczki .wdkb: tmp, pliki, obrazy i linie JSONL (CONTRACT E7-1a §3).

Wydzielone z ``kb_export_build`` (limit rozmiaru modułu): obsługa plików tymczasowych w
``<storage_root>/tmp``, dokładanie do ZIP oryginałów dokumentów i obrazów chunków (strumieniowo,
z dedupem po SHA-256) oraz zamiana wierszy DB na linie ``documents.jsonl``/``chunks.jsonl``.
Obrazy: ``chunks.image_id`` trzyma identyfikator trasy ``{dataset_id}-{sha}`` (E7-1b), więc klucz
storage to ``image_key(dataset_id, sha)`` — sufiks po pierwszym myślniku, tak jak czyta go
``app.services.documents_files``; gdy prefiks nie jest id-em datasetu, cały ``image_id`` jest
kluczem obiektu. Brak obiektu/pliku → ``None`` w linii, bez przerywania eksportu.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO

from sqlalchemy.engine import RowMapping

from app.services.kb_package import format as fmt
from app.services.kb_package.writer import PackageWriter
from app.storage.keys import StorageKey, image_key

if TYPE_CHECKING:
    from app.core.container import Container

__all__ = [
    "add_chunk_image",
    "add_document_file",
    "chunk_line",
    "document_line",
    "image_storage_key",
    "json_list",
    "json_value",
    "jsonl",
    "open_tmp",
    "read_blocks",
    "remove_tmp",
]

# Nazwa podkatalogu na pliki tymczasowe (K5 §1.3: layout ``tmp``).
TMP_DIR = "tmp"
# Rozmiar bloku czytania pliku tymczasowego przy dokładaniu do ZIP.
COPY_BLOCK = 1 << 20


def open_tmp(container: Container, tmp_paths: list[Path]) -> tuple[Path, BinaryIO]:
    """Tworzy plik tymczasowy w ``<storage_root>/tmp`` (seekable, binarny) i rejestruje go."""
    tmp_dir = Path(container.settings.storage_root) / TMP_DIR
    tmp_dir.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=tmp_dir, suffix=".tmp")
    path = Path(name)
    tmp_paths.append(path)
    return path, os.fdopen(fd, "w+b")


def read_blocks(path: Path) -> Iterator[bytes]:
    """Bloki bajtów pliku tymczasowego (strumień do wpisu ZIP)."""
    with open(path, "rb") as fp:
        while True:
            block = fp.read(COPY_BLOCK)
            if not block:
                return
            yield block


def remove_tmp(paths: list[Path]) -> None:
    """Usuwa pliki tymczasowe (brak pliku nie jest błędem)."""
    for path in paths:
        path.unlink(missing_ok=True)


async def add_document_file(
    container: Container,
    writer: PackageWriter,
    *,
    row: RowMapping,
    seen: set[str],
    tmp_paths: list[Path],
) -> str | None:
    """Dodaje plik dokumentu (dedup po sha) i zwraca sha256 albo ``None``, gdy brak pliku.

    Blob leci strumieniem storage → plik tymczasowy (sha liczony w locie) → wpis ZIP, więc
    oryginał dokumentu nie musi mieścić się w pamięci.
    """
    location = str(row["location"]) if row["location"] else ""
    if not location:
        return None
    key = StorageKey(location)
    if not await container.storage.exists(key):
        return None
    path, fp = open_tmp(container, tmp_paths)
    digest = hashlib.sha256()
    async for block in container.storage.open(key):
        digest.update(block)
        fp.write(block)
    fp.close()
    sha = digest.hexdigest()
    if sha not in seen:
        writer.add_file(f"{fmt.FILES_PREFIX}{sha}", read_blocks(path))
        seen.add(sha)
    return sha


async def add_chunk_image(
    container: Container,
    writer: PackageWriter,
    *,
    dataset_id: str,
    row: RowMapping,
    seen: set[str],
) -> str | None:
    """Dodaje obraz chunka (dedup po sha) i zwraca sha256 albo ``None``, gdy brak obrazu/obiektu."""
    image_id = row["image_id"]
    if not image_id:
        return None
    key = image_storage_key(dataset_id, str(image_id))
    if not await container.storage.exists(key):
        return None
    data = b"".join([block async for block in container.storage.open(key)])
    digest = hashlib.sha256(data).hexdigest()
    if digest not in seen:
        writer.add_file(f"{fmt.IMAGES_PREFIX}{digest}", (data,))
        seen.add(digest)
    return digest


def image_storage_key(dataset_id: str, image_id: str) -> StorageKey:
    """Klucz storage obrazu chunka z ``chunks.image_id`` (format trasy ``{dataset_id}-{sha}``)."""
    prefix, sep, rest = image_id.partition("-")
    object_key = rest if sep and prefix == dataset_id else image_id
    return image_key(dataset_id, object_key)


def document_line(ref: str, row: RowMapping, file_sha: str | None) -> dict[str, Any]:
    """Linia ``documents.jsonl`` (K19 §2); ``token_num``/``chunk_num`` z ``*_count``."""
    return {
        "ref": ref,
        "name": str(row["name"]),
        "type": str(row["type"]),
        "suffix": str(row["suffix"]),
        "size": int(row["size"]),
        "file_sha256": file_sha,
        "chunk_method": str(row["chunk_method"]),
        "parser_config": json_value(row["parser_config"]),
        "meta_fields": json_value(row["meta_fields"]),
        "run": str(row["run"]),
        "progress_msg": str(row["progress_msg"]),
        "token_num": int(row["token_count"]),
        "chunk_num": int(row["chunk_count"]),
    }


def chunk_line(
    ref: str,
    row: RowMapping,
    document_ref: str | None,
    image_sha: str | None,
    parent_ref: str | None,
) -> dict[str, Any]:
    """Linia ``chunks.jsonl`` (K19 §2) — ``available`` i edycje treści z DB 1:1."""
    return {
        "ref": ref,
        "document_ref": document_ref,
        "ordinal": int(row["ordinal"]),
        "chunk_type": str(row["chunk_type"]),
        "content": str(row["content"]),
        "content_llm": row["content_llm"],
        "keywords": json_list(row["keywords"]),
        "questions": json_list(row["questions"]),
        "tags": json_value(row["tags"]),
        "positions": json_value(row["positions"]),
        "page_from": row["page_from"],
        "page_to": row["page_to"],
        "image_sha256": image_sha,
        "parent_ref": parent_ref,
        "available": bool(row["available"]),
        "embed_source": str(row["embed_source"]),
        "token_count": int(row["token_count"]),
    }


def jsonl(line: Mapping[str, Any]) -> bytes:
    """Linia JSONL (UTF-8, zakończona ``\\n``)."""
    return json.dumps(dict(line), ensure_ascii=False).encode("utf-8") + b"\n"


def json_value(value: Any) -> Any:
    """JSON z bazy: ``str`` → parsowany, ``None``/obiekt → bez zmian."""
    return json.loads(value) if isinstance(value, str) else value


def json_list(value: Any) -> list[Any]:
    """Kolumna JSON-owa jako lista (``None`` → pusta)."""
    parsed = json_value(value)
    return list(parsed) if parsed is not None else []
