"""Testy `decrypt_source_secret` — algorytm źródła Sekretu SharePoint (brief T7, kontrakt §9)."""

import os

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.tools.ragflow_migrate.stages.sp_secret import SourceSecretError, decrypt_source_secret

#: Klucz 32 B w zapisie hex (64 znaki) — jak `SHAREPOINT_CRYPTO_KEY` w źródle (kontrakt §9).
KEY = "fedcba9876543210" * 4
SECRET = "fixture-sp-client-secret-0001"  # noqa: S105 — sekret wyłącznie testowy (fixture)


def _seal(key_hex: str, plaintext: str) -> str:
    """Szyfrogram w formacie źródła `iv:tag:ct` (AES-256-GCM, IV 12 B, bez AAD)."""
    iv = os.urandom(12)
    blob = AESGCM(bytes.fromhex(key_hex)).encrypt(iv, plaintext.encode(), None)
    return f"{iv.hex()}:{blob[-16:].hex()}:{blob[:-16].hex()}"


def test_decrypts_reference_ciphertext() -> None:
    """Szyfrogram zrobiony tak jak w źródle (hub-compat `crypto.ts`) → jawny sekret."""
    assert decrypt_source_secret(KEY, _seal(KEY, SECRET)) == SECRET


def test_wrong_key_is_rejected() -> None:
    """Inny poprawny klucz → `SourceSecretError`; komunikat bez klucza, szyfrogramu i sekretu."""
    payload = _seal(KEY, SECRET)
    with pytest.raises(SourceSecretError) as excinfo:
        decrypt_source_secret("00" * 32, payload)
    assert KEY not in str(excinfo.value)
    assert payload not in str(excinfo.value)
    assert SECRET not in str(excinfo.value)


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param("", id="empty"),
        pytest.param("abcd:ef01", id="two_parts"),
        pytest.param(f"{os.urandom(12).hex()}:{'zz' * 16}:{'aa' * 8}", id="non_hex"),
        pytest.param(f"{os.urandom(12).hex()}:{'aa' * 16}", id="missing_ciphertext"),
    ],
)
def test_bad_payload_is_rejected(payload: str) -> None:
    """Zły format, nie-hex albo pusty szyfrogram → `SourceSecretError` bez treści w komunikacie."""
    with pytest.raises(SourceSecretError) as excinfo:
        decrypt_source_secret(KEY, payload)
    message = str(excinfo.value)
    assert SECRET not in message
    assert not payload or payload not in message


@pytest.mark.parametrize(
    "key_hex",
    [
        pytest.param("zz" + "00" * 31, id="non_hex"),
        pytest.param("00" * 16, id="too_short"),
        pytest.param("", id="empty"),
    ],
)
def test_bad_key_is_rejected(key_hex: str) -> None:
    """Klucz nie-hex albo o złej długości → `SourceSecretError` bez klucza w komunikacie."""
    payload = _seal(KEY, SECRET)
    with pytest.raises(SourceSecretError) as excinfo:
        decrypt_source_secret(key_hex, payload)
    message = str(excinfo.value)
    assert payload not in message
    assert not key_hex or key_hex not in message
