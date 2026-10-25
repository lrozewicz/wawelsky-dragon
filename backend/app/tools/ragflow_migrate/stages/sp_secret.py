"""Odszyfrowanie sekretu klienta SharePoint źródła (hub-compat) — kontrakt §9 WP E4-6b1.

Format źródła: ``"<iv hex>:<authTag hex>:<ciphertext hex>"``, AES-256-GCM bez AAD, klucz 32 B
z zapisu hex. Odszyfrowanie: ``AESGCM(key).decrypt(iv, ciphertext + tag, None)``.
"""

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

#: Długość klucza AES-256 w bajtach (zapis źródłowy: 64 znaki hex).
_KEY_BYTES = 32
#: Liczba części szyfrogramu źródłowego: iv, tag, ciphertext.
_PARTS = 3

#: Komunikat bez klucza, szyfrogramu i sekretu — ten sam dla każdej przyczyny błędu.
_MESSAGE = "cannot decrypt source secret"


class SourceSecretError(Exception):
    """Nie udało się odszyfrować sekretu źródła; komunikat nie zawiera klucza ani szyfrogramu."""


def decrypt_source_secret(key_hex: str, payload: str) -> str:
    """Sekret jawny z szyfrogramu źródła; każdy błąd formatu/klucza → ``SourceSecretError``.

    Wyjątek nie przenosi ani klucza, ani szyfrogramu, ani sekretu (kontrakt §9).
    """
    try:
        key = bytes.fromhex(key_hex)
    except ValueError:
        raise SourceSecretError(_MESSAGE) from None
    if len(key) != _KEY_BYTES:
        raise SourceSecretError(_MESSAGE)
    parts = payload.split(":")
    if len(parts) != _PARTS:
        raise SourceSecretError(_MESSAGE)
    try:
        iv, tag, ciphertext = (bytes.fromhex(part) for part in parts)
        return AESGCM(key).decrypt(iv, ciphertext + tag, None).decode()
    except (InvalidTag, ValueError, UnicodeDecodeError):
        raise SourceSecretError(_MESSAGE) from None
