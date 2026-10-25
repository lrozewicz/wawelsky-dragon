"""Szyfrowanie klucza dostawcy wyszukiwania (CONTRACT E6-3f §C3, K18 §5).

AES-GCM z AAD wiążącym blob z id dostawcy (`b"web-search-provider:" + id`), styl
`app/services/provider_common.py`. Klucz jawny nigdy nie trafia do `repr`, logu ani wyjątku.
"""

from app.core.config import Settings
from app.core.crypto import decrypt, encrypt


def _aad(provider_id: str) -> bytes:
    """AAD blobu klucza dostawcy — wiąże szyfrogram z id dostawcy (§C3)."""
    return b"web-search-provider:" + provider_id.encode()


def encrypt_key(settings: Settings, provider_id: str, plain: str) -> bytes:
    """Klucz dostawcy: AES-GCM z AAD wiążącym blob z id dostawcy (§C3)."""
    return encrypt(settings.crypto_key.get_secret_value(), plain.encode(), _aad(provider_id))


def decrypt_key(settings: Settings, provider_id: str, blob: bytes) -> str:
    """Odwrotność `encrypt_key`; błąd klucza/AAD → ValidationFailed (§C3)."""
    return decrypt(settings.crypto_key.get_secret_value(), blob, _aad(provider_id)).decode()
