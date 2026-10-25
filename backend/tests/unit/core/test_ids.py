"""Testy generatora identyfikatorów: UUIDv7, chunk id, walidacja (kontrakt C5)."""

import re
import time
import uuid

import pytest

from app.core.errors import ValidationFailed
from app.core.ids import UuidV7Generator, is_valid_id, new_chunk_id, new_id, normalize_id

_UUID_VERSION = 7
_MONOTONIC_COUNT = 10000
_OVERFLOW_CALLS = 5000
_OVERFLOW_NS = 1_790_157_600_000_000_000
_CLOCK_SLOP_MS = 100
_CHUNK_DOC1_ORD0 = "300e1c54d1792550"
_CHUNK_DOC1_ORD1 = "6633c9119e3c5b8d"


def test_new_id_format_and_version() -> None:
    v = new_id()
    assert re.fullmatch(r"[0-9a-f]{32}", v)
    assert uuid.UUID(hex=v).version == _UUID_VERSION
    assert uuid.UUID(hex=v).variant == uuid.RFC_4122


def test_new_id_monotonic_and_unique() -> None:
    ids = [new_id() for _ in range(_MONOTONIC_COUNT)]
    assert ids == sorted(ids)
    assert len(set(ids)) == _MONOTONIC_COUNT


def test_new_id_timestamp_between_before_and_after() -> None:
    before = time.time_ns() // 1_000_000
    v = new_id()
    after = time.time_ns() // 1_000_000
    assert before <= int(v[:12], 16) <= after + _CLOCK_SLOP_MS


def test_new_id_counter_overflow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.ids.time.time_ns", lambda: _OVERFLOW_NS)
    ids = [new_id() for _ in range(_OVERFLOW_CALLS)]
    assert ids == sorted(ids)
    assert len(set(ids)) == _OVERFLOW_CALLS


def test_new_chunk_id_known_values() -> None:
    assert new_chunk_id("doc1", 0, "hello") == _CHUNK_DOC1_ORD0
    assert new_chunk_id("doc1", 1, "hello") == _CHUNK_DOC1_ORD1


def test_new_chunk_id_is_deterministic() -> None:
    assert new_chunk_id("doc1", 0, "hello") == new_chunk_id("doc1", 0, "hello")


@pytest.mark.parametrize(
    "value",
    ["0192f0c1a2b37c4d8e9f0a1b2c3d4e5f", "0192F0C1-A2B3-7C4D-8E9F-0A1B2C3D4E5F"],
)
def test_is_valid_id_true(value: str) -> None:
    assert is_valid_id(value)


@pytest.mark.parametrize(
    "value",
    ["xyz", "0192f0c1a2b37c4d8e9f0a1b2c3d4e5", "{0192f0c1-a2b3-7c4d-8e9f-0a1b2c3d4e5f}", ""],
)
def test_is_valid_id_false(value: str) -> None:
    assert not is_valid_id(value)


def test_normalize_id_lowercases_and_strips_dashes() -> None:
    mixed = "0192F0C1-A2B3-7C4D-8E9F-0A1B2C3D4E5F"
    assert normalize_id(mixed) == "0192f0c1a2b37c4d8e9f0a1b2c3d4e5f"


def test_normalize_id_invalid_raises() -> None:
    with pytest.raises(ValidationFailed, match="Invalid id: bad"):
        normalize_id("bad")


def test_uuid_v7_generator_produces_uuidv7() -> None:
    v = UuidV7Generator().new_id()
    assert re.fullmatch(r"[0-9a-f]{32}", v)
    assert uuid.UUID(hex=v).version == _UUID_VERSION
