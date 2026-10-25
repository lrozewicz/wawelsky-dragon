"""Testy typów i błędów parsowania (kontrakt C1, C2)."""

import pickle
from collections.abc import Callable

import pytest

from app.core.errors import OperationNotAllowed
from app.parsing.errors import (
    BinaryMissing,
    ConversionFailed,
    CorruptedFile,
    EmptyDocument,
    EncryptedFile,
    LimitExceeded,
    UnsupportedFormat,
    binary_missing,
    corrupted_file,
    empty_document,
    encrypted_file,
    limit_exceeded,
    unsupported_format,
)
from app.parsing.types import ConvertedDocument, ConvertOptions, PendingPage


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("pdf_strategy", "auto"),
        ("pages", ((1, 1_000_000),)),
        ("vision_available", False),
        ("ocr_available", False),
        ("ocr_langs", "pol+eng"),
        ("min_chars", 150),
        ("mojibake_max", 0.05),
        ("cid_max", 0.02),
        ("image_cover", 0.6),
        ("max_pages", 2000),
        ("max_sheet_rows", 200_000),
        ("max_uncompressed_bytes", 2048 * 1024 * 1024),
        ("max_archive_ratio", 100),
    ],
)
def test_convert_options_defaults(field: str, expected: object) -> None:
    assert getattr(ConvertOptions(), field) == expected


@pytest.mark.parametrize(
    "value",
    [
        ConvertOptions(pdf_strategy="vision", pages=((2, 5), (7, 9)), min_chars=20),
        PendingPage(page=3, mode="ocr", image_png=b"\x89PNG-data", reason="chars<150"),
        ConvertedDocument(
            "<p>x</p>",
            3,
            [PendingPage(3, "vision", b"png", "r")],
            {"title": "T"},
            ["w"],
            {"chars": 1},
        ),
    ],
    ids=["options", "pending-page", "document"],
)
def test_pickle_round_trip(value: object) -> None:
    restored = pickle.loads(pickle.dumps(value))  # noqa: S301 — round-trip własnych obiektów
    assert restored == value


@pytest.mark.parametrize(
    ("make", "expected_type", "message", "details"),
    [
        (
            lambda: unsupported_format("doc"),
            UnsupportedFormat,
            "Unsupported file format: doc",
            {"format": "doc"},
        ),
        (
            lambda: corrupted_file("pdf", "bad xref"),
            CorruptedFile,
            "File is corrupted or unreadable (.pdf): bad xref",
            {"format": "pdf", "reason": "bad xref"},
        ),
        (
            lambda: encrypted_file("xlsx"),
            EncryptedFile,
            "File is password-protected (.xlsx)",
            {"format": "xlsx"},
        ),
        (
            lambda: binary_missing("tesseract"),
            BinaryMissing,
            "Required program 'tesseract' is not installed; use the worker-ocr image",
            {"binary": "tesseract"},
        ),
        (
            lambda: limit_exceeded("pages", 3000, 2000),
            LimitExceeded,
            "Limit exceeded: pages 3000 > 2000",
            {"what": "pages", "value": 3000, "limit": 2000},
        ),
        (
            lambda: empty_document("file is empty"),
            EmptyDocument,
            "No text could be extracted: file is empty",
            {"diagnosis": "file is empty"},
        ),
    ],
    ids=["unsupported", "corrupted", "encrypted", "binary", "limit", "empty"],
)
def test_error_factories(
    make: Callable[[], ConversionFailed],
    expected_type: type[ConversionFailed],
    message: str,
    details: dict[str, object],
) -> None:
    error = make()
    assert type(error) is expected_type
    assert str(error) == message
    assert error.details == details
    assert error.transient is False
    assert isinstance(error, OperationNotAllowed)
    assert isinstance(error, ConversionFailed)


@pytest.mark.parametrize(
    "error",
    [
        unsupported_format("doc"),
        corrupted_file("pdf", "bad xref"),
        encrypted_file("xlsx"),
        binary_missing("tesseract"),
        limit_exceeded("pages", 3000, 2000),
        empty_document("file is empty"),
    ],
    ids=["unsupported", "corrupted", "encrypted", "binary", "limit", "empty"],
)
def test_error_pickle_round_trip(error: ConversionFailed) -> None:
    restored = pickle.loads(pickle.dumps(error))  # noqa: S301 — round-trip własnych obiektów
    assert type(restored) is type(error)
    assert str(restored) == str(error)
    assert restored.details == error.details
    assert restored.transient is False
