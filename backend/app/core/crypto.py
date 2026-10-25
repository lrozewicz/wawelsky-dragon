"""Szyfrowanie AES-256-GCM kluczy API (kontrakt C7, K5 §3.6)."""

import os
import re

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.errors import ValidationFailed

_NONCE_BYTES = 12
_TAG_BYTES = 16
_KEY_HEX = re.compile(r"[0-9a-fA-F]{64}")


def _key(key_hex: str) -> bytes:
    """Klucz z zapisu hex; niepoprawny format → ValidationFailed."""
    if _KEY_HEX.fullmatch(key_hex) is None:
        raise ValidationFailed("invalid crypto key")
    return bytes.fromhex(key_hex)


def encrypt(key_hex: str, plaintext: bytes, aad: bytes | None = None) -> bytes:
    """Szyfrowanie: blob = nonce(12) ‖ ciphertext ‖ tag(16); `aad` = associated_data."""
    nonce = os.urandom(_NONCE_BYTES)
    return nonce + AESGCM(_key(key_hex)).encrypt(nonce, plaintext, aad)


def decrypt(key_hex: str, blob: bytes, aad: bytes | None = None) -> bytes:
    """Odszyfrowanie blobu; błędny klucz, zła AAD albo uszkodzony blob → ValidationFailed."""
    key = _key(key_hex)
    if len(blob) < _NONCE_BYTES + _TAG_BYTES:
        raise ValidationFailed("cannot decrypt")
    try:
        return AESGCM(key).decrypt(blob[:_NONCE_BYTES], blob[_NONCE_BYTES:], aad)
    except InvalidTag:
        raise ValidationFailed("cannot decrypt") from None
