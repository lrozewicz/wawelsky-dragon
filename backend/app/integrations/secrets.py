"""Sekrety integracji: format `v1:<nonce_b64>:<ct+tag_b64>` z AAD per integracja (09 §11).

Przeniesienie szyfrogramu do innej integracji nie zadziała — AAD zawiera `integration_id`.
Klucz (64 hex) pochodzi z `container.settings.crypto_key` (WD_CRYPTO_KEY).
"""

import base64
import binascii

from app.core.crypto import decrypt, encrypt
from app.core.errors import ValidationFailed

_VERSION = "v1"
_NONCE_BYTES = 12
_PARTS = 3


def _aad(integration_id: int) -> bytes:
    """Associated data wiążące szyfrogram z konkretną integracją."""
    return f"integration:{integration_id}".encode()


def encrypt_secret(key_hex: str, integration_id: int, plaintext: str) -> tuple[str, str]:
    """Zwraca `(enc, last4)`: zaszyfrowany sekret w formacie `v1:` i jego ostatnie 4 znaki."""
    blob = encrypt(key_hex, plaintext.encode(), _aad(integration_id))
    nonce = base64.b64encode(blob[:_NONCE_BYTES]).decode("ascii")
    body = base64.b64encode(blob[_NONCE_BYTES:]).decode("ascii")
    return f"{_VERSION}:{nonce}:{body}", plaintext[-4:]


def decrypt_secret(key_hex: str, integration_id: int, enc: str) -> str:
    """Odszyfrowuje `enc`; zły format, klucz albo AAD → ValidationFailed("cannot decrypt")."""
    parts = enc.split(":")
    if len(parts) != _PARTS or parts[0] != _VERSION:
        raise ValidationFailed("cannot decrypt")
    try:
        nonce = base64.b64decode(parts[1], validate=True)
        body = base64.b64decode(parts[2], validate=True)
    except (binascii.Error, ValueError):
        raise ValidationFailed("cannot decrypt") from None
    return decrypt(key_hex, nonce + body, _aad(integration_id)).decode()
