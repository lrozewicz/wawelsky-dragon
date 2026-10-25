"""Testy kluczy storage wg C1 — przykłady dosłownie z kontraktu i briefu T1."""

import pytest

from app.core.errors import ValidationFailed
from app.storage.keys import (
    chunk_image_key,
    dataset_prefix,
    derived_key,
    document_key,
    document_prefix,
    filemanager_key,
    image_key,
    is_filemanager_key,
    validate_key,
)


def test_document_key_examples() -> None:
    assert document_key("d1", "x1", "pdf") == "files/d1/x1/original.pdf"
    assert document_key("d1", "x1", "") == "files/d1/x1/original"


def test_derived_key_example() -> None:
    assert derived_key("d1", "x1", "normalized.html") == "files/d1/x1/derived/normalized.html"


def test_prefix_examples() -> None:
    assert document_prefix("d1", "x1") == "files/d1/x1"
    assert dataset_prefix("d1") == "files/d1"


def test_chunk_image_and_filemanager_examples() -> None:
    assert chunk_image_key("d1", "c1") == "images/d1/c1.png"
    assert filemanager_key("f1", "docx") == "filemanager/f1/original.docx"


def test_image_key_example() -> None:
    """E2-1 DOC2: id trasy ``{dataset_id}-{object_key}`` → klucz ``images/{ds}/{object_key}``."""
    assert image_key("d1", "page-1.png") == "images/d1/page-1.png"
    assert image_key("d1", "c1.png") == chunk_image_key("d1", "c1")
    with pytest.raises(ValidationFailed):
        image_key("d1", "../etc/passwd")


def test_is_filemanager_key_examples() -> None:
    """E4-5a T1: blob `filemanager/` należy do wiersza `files` (K16 §1 p. 5)."""
    assert is_filemanager_key("filemanager/abc/original.txt") is True
    assert is_filemanager_key(filemanager_key("f1", "txt")) is True
    assert is_filemanager_key("files/ds/doc/original") is False
    assert is_filemanager_key("images/ds/c1.png") is False
    assert is_filemanager_key("") is False
    assert is_filemanager_key("filemanager") is False


@pytest.mark.parametrize(
    "key",
    [
        "../etc/passwd",
        "/abs",
        "a//b",
        "a/./b",
        "files/../x",
        "files/a/",
        "files\\a",
        "",
    ],
)
def test_validate_key_rejects(key: str) -> None:
    with pytest.raises(ValidationFailed):
        validate_key(key)


def test_validate_key_accepts_plain_path() -> None:
    assert validate_key("files/d1/x1/original.pdf") == "files/d1/x1/original.pdf"


@pytest.mark.parametrize("suffix", ["PDF", ".pdf", "a/b", "a" * 17])
def test_document_key_rejects_bad_suffix(suffix: str) -> None:
    with pytest.raises(ValidationFailed, match="invalid suffix"):
        document_key("d1", "x1", suffix)


@pytest.mark.parametrize("suffix", ["", "pdf", "a" * 16])
def test_document_key_accepts_good_suffix(suffix: str) -> None:
    ext = f".{suffix}" if suffix else ""
    assert document_key("d1", "x1", suffix) == f"files/d1/x1/original{ext}"


def test_document_key_rejects_parent_segment() -> None:
    with pytest.raises(ValidationFailed):
        document_key("..", "x", "pdf")
