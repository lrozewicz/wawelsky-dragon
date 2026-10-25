"""Testy limitu 100 plików/żądanie (H4, kontrakt WP E5-2a T1, DEC-213).

Wyrocznia: ``uv run pytest tests/unit/api/test_file_safety.py -q``.
"""

import pytest

from app.api.ragflow.file_safety import MAX_FILES_PER_REQUEST, ensure_file_count
from app.core.errors import ValidationFailed

LIMIT = 100
HTTP_BAD_REQUEST = 400


def test_max_files_per_request_is_100() -> None:
    assert MAX_FILES_PER_REQUEST == LIMIT


def test_exactly_100_files_is_allowed() -> None:
    assert ensure_file_count([object()] * LIMIT) is None


def test_empty_list_is_allowed() -> None:
    assert ensure_file_count([]) is None


def test_101_files_raises_validation_failed_with_contract_message() -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        ensure_file_count([object()] * (LIMIT + 1))
    assert str(excinfo.value) == "Too many files: 101 (max 100 per request)"
    assert excinfo.value.http_status == HTTP_BAD_REQUEST
