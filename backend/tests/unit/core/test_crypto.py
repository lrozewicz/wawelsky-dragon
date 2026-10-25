"""Testy szyfrowania AES-256-GCM (kontrakt C7, K5 §3.6)."""

import pytest

from app.core.crypto import decrypt, encrypt
from app.core.errors import ValidationFailed

KEY = "00" * 32


def test_roundtrip() -> None:
    blob = encrypt(KEY, b"sekret")
    assert decrypt(KEY, blob) == b"sekret"


def test_blob_length() -> None:
    # nonce(12) + plaintext(6) + tag(16).
    assert len(encrypt(KEY, b"sekret")) == 12 + 6 + 16


def test_same_plaintext_different_blobs() -> None:
    assert encrypt(KEY, b"sekret") != encrypt(KEY, b"sekret")


def test_empty_plaintext_roundtrip() -> None:
    assert decrypt(KEY, encrypt(KEY, b"")) == b""


def test_wrong_key() -> None:
    with pytest.raises(ValidationFailed) as exc_info:
        decrypt("11" * 32, encrypt(KEY, b"sekret"))
    assert exc_info.value.message == "cannot decrypt"


def test_flipped_ciphertext_byte() -> None:
    blob = bytearray(encrypt(KEY, b"sekret"))
    blob[-1] ^= 0x01
    with pytest.raises(ValidationFailed) as exc_info:
        decrypt(KEY, bytes(blob))
    assert exc_info.value.message == "cannot decrypt"


def test_too_short_blob() -> None:
    with pytest.raises(ValidationFailed) as exc_info:
        decrypt(KEY, b"short")
    assert exc_info.value.message == "cannot decrypt"


def test_encrypt_invalid_key_format() -> None:
    with pytest.raises(ValidationFailed) as exc_info:
        encrypt("abc", b"x")
    assert exc_info.value.message == "invalid crypto key"


def test_encrypt_wrong_key_length() -> None:
    with pytest.raises(ValidationFailed) as exc_info:
        encrypt("00" * 31, b"x")
    assert exc_info.value.message == "invalid crypto key"


def test_decrypt_invalid_key_format() -> None:
    with pytest.raises(ValidationFailed) as exc_info:
        decrypt("zz" * 32, b"x" * 34)
    assert exc_info.value.message == "invalid crypto key"


# --- AAD (WP E4-2b, kontrakt: `aad` jako associated_data AESGCM) ---


def test_aad_roundtrip() -> None:
    aad = b"integration:7"
    assert decrypt(KEY, encrypt(KEY, b"sekret", aad), aad) == b"sekret"


def test_aad_wrong_aad_rejected() -> None:
    with pytest.raises(ValidationFailed) as exc_info:
        decrypt(KEY, encrypt(KEY, b"sekret", b"integration:7"), b"integration:8")
    assert exc_info.value.message == "cannot decrypt"


def test_aad_missing_aad_rejected() -> None:
    # Szyfrogram z AAD nie odszyfruje się bez AAD.
    with pytest.raises(ValidationFailed) as exc_info:
        decrypt(KEY, encrypt(KEY, b"sekret", b"integration:7"))
    assert exc_info.value.message == "cannot decrypt"


def test_aad_extra_aad_rejected() -> None:
    # Szyfrogram bez AAD nie odszyfruje się z AAD.
    with pytest.raises(ValidationFailed) as exc_info:
        decrypt(KEY, encrypt(KEY, b"sekret"), b"integration:7")
    assert exc_info.value.message == "cannot decrypt"


def test_aad_omitted_unchanged() -> None:
    # Wywołania bez `aad` zachowują się jak dotąd (zgodność wsteczna).
    assert decrypt(KEY, encrypt(KEY, b"sekret")) == b"sekret"
