"""Testy kluczy cache modułu LLM (kontrakt C10)."""

import hashlib
import inspect
import struct
import sys

import pytest

from app.llm.cache_keys import (
    CACHE_TTL_MS,
    chat_cache_key,
    embedding_cache_key,
    pack_vector,
    unpack_vector,
    vision_cache_key,
)

_MESSAGES = [{"role": "user", "content": "cześć"}]
_OTHER_MESSAGES = [{"role": "user", "content": "inny"}]
_KEY_HEX_LEN = 64
_3072_FLOATS_BYTES = 3072 * 4


def _vision_key(**overrides: object) -> str:
    """Klucz wizji z domyślnymi wejściami i nadpisaniami (kontrakt E5-H8e §C3)."""
    base: dict[str, object] = {
        "model": "xiaomi-ocr-0",
        "base_url": "http://llm/v1",
        "image_sha256": "a" * 64,
        "prompt": "przepisz",
        "temperature": 0.0,
        "max_tokens": 8192,
        "extra_body": {"chat_template": "x"},
    }
    base.update(overrides)
    return vision_cache_key(**base)  # type: ignore[arg-type]


def test_cache_ttl_ms_is_30_days() -> None:
    assert CACHE_TTL_MS == 30 * 24 * 3600 * 1000


def test_chat_cache_key_deterministic_and_64_hex() -> None:
    first = chat_cache_key("m", _MESSAGES, 0.7, None, None, None)
    second = chat_cache_key("m", _MESSAGES, 0.7, None, None, None)
    assert first == second
    assert len(first) == _KEY_HEX_LEN
    int(first, 16)  # hex bez wyjątku


def test_chat_cache_key_changes_with_any_field() -> None:
    base = chat_cache_key("m", _MESSAGES, 0.7, 0.9, 100, {"x": 1})
    assert chat_cache_key("m2", _MESSAGES, 0.7, 0.9, 100, {"x": 1}) != base
    assert chat_cache_key("m", _OTHER_MESSAGES, 0.7, 0.9, 100, {"x": 1}) != base
    assert chat_cache_key("m", _MESSAGES, 0.8, 0.9, 100, {"x": 1}) != base
    assert chat_cache_key("m", _MESSAGES, None, 0.9, 100, {"x": 1}) != base
    assert chat_cache_key("m", _MESSAGES, 0.7, None, 100, {"x": 1}) != base
    assert chat_cache_key("m", _MESSAGES, 0.7, 0.9, 101, {"x": 1}) != base
    assert chat_cache_key("m", _MESSAGES, 0.7, 0.9, 100, {"x": 2}) != base


def test_chat_cache_key_extra_none_differs_from_empty() -> None:
    none_key = chat_cache_key("m", _MESSAGES, 0.7, None, None, None)
    empty_key = chat_cache_key("m", _MESSAGES, 0.7, None, None, {})
    assert none_key != empty_key


# --- vision_cache_key (kontrakt E5-H8e §C3) ---


def test_vision_cache_key_deterministic_and_64_hex() -> None:
    first = _vision_key()
    assert first == _vision_key()
    assert len(first) == _KEY_HEX_LEN
    int(first, 16)


def test_vision_cache_key_changes_with_any_field() -> None:
    base = _vision_key()
    assert _vision_key(model="other") != base
    assert _vision_key(base_url="http://other/v1") != base
    assert _vision_key(image_sha256="b" * 64) != base
    assert _vision_key(prompt="inny") != base
    assert _vision_key(temperature=0.5) != base
    assert _vision_key(max_tokens=4096) != base
    assert _vision_key(extra_body={"chat_template": "y"}) != base


def test_vision_cache_key_extra_body_none_differs_from_empty() -> None:
    assert _vision_key(extra_body=None) != _vision_key(extra_body={})


def test_vision_cache_key_has_no_api_key() -> None:
    """api_key nie wchodzi do klucza — nie ma go nawet w sygnaturze (C3)."""
    assert "api_key" not in inspect.signature(vision_cache_key).parameters


def test_embedding_cache_key_formula() -> None:
    assert embedding_cache_key("m", 0, "t") == hashlib.sha256(b"m\x1f0\x1ft").hexdigest()


def test_pack_unpack_vector_roundtrip() -> None:
    vector = [0.5, -1.0]
    assert unpack_vector(pack_vector(vector)) == vector


def test_pack_vector_3072_floats_is_12288_bytes() -> None:
    assert len(pack_vector([1.0] * 3072)) == _3072_FLOATS_BYTES


def test_pack_unpack_vector_big_endian(monkeypatch: pytest.MonkeyPatch) -> None:
    # symulacja maszyny big-endian: native (tu little) + byteswap ⇒ big-endian w packu,
    # unpack pozostaje dokładną odwrotnością pack (gwarancja kontraktu C10)
    monkeypatch.setattr(sys, "byteorder", "big")
    vector = [0.5, -1.0]
    blob = pack_vector(vector)
    assert blob == struct.pack(">2f", *vector)
    assert unpack_vector(blob) == vector
