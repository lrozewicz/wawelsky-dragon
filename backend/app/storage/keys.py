"""Klucze storage — jedyne źródło układu ścieżek (K5 §1.1, kontrakt C1)."""

import re
from typing import NewType

from app.core.errors import ValidationFailed

StorageKey = NewType("StorageKey", str)

# Segmenty po "/" niepuste: litery, cyfry, kropka, podkreślenie, myślnik.
_SEGMENT_RE = re.compile(r"[A-Za-z0-9._-]+")
# Suffix rozszerzenia: małe litery i cyfry, 1-16 znaków.
_SUFFIX_RE = re.compile(r"[a-z0-9]{1,16}")


def validate_key(key: str) -> StorageKey:
    """Sprawdza względna ścieżkę POSIX; inaczej ValidationFailed."""
    if key.startswith("/") or key.endswith("/") or "\\" in key:
        raise ValidationFailed(f"invalid storage key: {key!r}")
    for segment in key.split("/"):
        if segment in (".", "..") or _SEGMENT_RE.fullmatch(segment) is None:
            raise ValidationFailed(f"invalid storage key: {key!r}")
    return StorageKey(key)


def _checked_suffix(suffix: str) -> str:
    """Suffix pusty albo [a-z0-9]{1,16}; inny → ValidationFailed."""
    if suffix and _SUFFIX_RE.fullmatch(suffix) is None:
        raise ValidationFailed(f"invalid suffix: {suffix!r}")
    return suffix


def _original_name(suffix: str) -> str:
    """Nazwa "original" z opcjonalnym rozszerzeniem (suffix już sprawdzony)."""
    return f"original.{suffix}" if suffix else "original"


def document_key(dataset_id: str, document_id: str, suffix: str) -> StorageKey:
    """files/{ds}/{doc}/original{.suffix}; suffix "" → "original"."""
    name = _original_name(_checked_suffix(suffix))
    return validate_key(f"files/{dataset_id}/{document_id}/{name}")


def derived_key(dataset_id: str, document_id: str, name: str) -> StorageKey:
    """files/{ds}/{doc}/derived/{name}."""
    return validate_key(f"files/{dataset_id}/{document_id}/derived/{name}")


def document_prefix(dataset_id: str, document_id: str) -> StorageKey:
    """files/{ds}/{doc}."""
    return validate_key(f"files/{dataset_id}/{document_id}")


def dataset_prefix(dataset_id: str) -> StorageKey:
    """files/{ds}."""
    return validate_key(f"files/{dataset_id}")


def chunk_image_key(dataset_id: str, chunk_id: str) -> StorageKey:
    """images/{ds}/{chunk_id}.png."""
    return validate_key(f"images/{dataset_id}/{chunk_id}.png")


def filemanager_key(file_id: str, suffix: str) -> StorageKey:
    """filemanager/{file_id}/original{.suffix}."""
    return validate_key(f"filemanager/{file_id}/{_original_name(_checked_suffix(suffix))}")


def is_filemanager_key(key: str) -> bool:
    """Czy klucz należy do bloba menedżera plików (``filemanager/…``, K16 §1 p. 5).

    Blob pod ``filemanager/`` jest własnością wiersza ``files`` — usunięcie zlinkowanego
    dokumentu nie może go skasować (``IngestService.delete_documents``/``replace``).
    """
    return key.startswith("filemanager/")


def image_key(dataset_id: str, object_key: str) -> StorageKey:
    """images/{ds}/{object_key} — obraz dokumentu wskazany przez ``/documents/images/{id}``.

    ``object_key`` przychodzi z segmentu trasy (po pierwszym myślniku) — walidacja
    ``validate_key`` odrzuca wartości spoza ``[A-Za-z0-9._-]`` (ochrona przed wyjściem
    z katalogu).
    """
    return validate_key(f"images/{dataset_id}/{object_key}")
