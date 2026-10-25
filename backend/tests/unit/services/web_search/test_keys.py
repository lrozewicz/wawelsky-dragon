"""Testy szyfrowania klucza dostawcy wyszukiwania (CONTRACT E6-3f §C3, K18 §5).

`keys.encrypt_key`/`decrypt_key` to AES-GCM z AAD `b"web-search-provider:" + id` (styl
`provider_common.py`): round-trip, szyfrogram różny od jawnego i niezawierający go, inny
`provider_id` (AAD) → `ValidationFailed`.
"""

import pytest

from app.core.config import Settings
from app.core.errors import ValidationFailed
from app.services.web_search import keys

CRYPTO_KEY = "ab" * 32
PROVIDER_ID = "5ea4c00d5ea4c00d5ea4c00d5ea4c00d"
PLAIN = "tvly-SECRET-key"


def _settings() -> Settings:
    """Ustawienia testowe z prawidłowym kluczem szyfrowania (64 hex)."""
    return Settings(env="test", crypto_key=CRYPTO_KEY)


def test_round_trip() -> None:
    """`decrypt_key(encrypt_key(s, id, plain))` oddaje jawny klucz (§C3)."""
    settings = _settings()
    blob = keys.encrypt_key(settings, PROVIDER_ID, PLAIN)
    assert keys.decrypt_key(settings, PROVIDER_ID, blob) == PLAIN


def test_blob_differs_from_plaintext_and_does_not_contain_it() -> None:
    """Szyfrogram różni się od jawnego klucza i nie zawiera go jako podciągu (§C3)."""
    blob = keys.encrypt_key(_settings(), PROVIDER_ID, PLAIN)
    assert blob != PLAIN.encode()
    assert PLAIN.encode() not in blob
    # Blob z AAD: sam szyfrogram nie wystarczy do odszyfrowania po innym id (§C3).
    assert isinstance(blob, bytes)


def test_different_provider_id_fails_decryption() -> None:
    """AAD wiąże blob z id dostawcy: inny id → `ValidationFailed` („cannot decrypt", §C3)."""
    blob = keys.encrypt_key(_settings(), PROVIDER_ID, PLAIN)
    with pytest.raises(ValidationFailed):
        keys.decrypt_key(_settings(), "0" * 32, blob)
