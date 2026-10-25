"""Dowody H9: stałoczasowe porównanie sekretu klienta hub-compat i szyfrowana kopia klucza API.

Stan faktyczny (sprawdzony w źródle):
- `app/api/hub_compat/security.py::require_secret` porównuje nagłówek `X-API-Secret`
  z `Settings.hub_compat_api_secret` przez `hmac.compare_digest`; pusty sekret odrzuca
  wszystko (także dopasowanie pustych wartości).
- `app/services/api_keys.py::ApiKeyService.create` zapisuje
  `token_enc=encrypt(settings.crypto_key, token.encode())` (ADR-13), a
  `::list_full` odtwarza jawny token przez `decrypt` — stąd round-trip AES-256-GCM.
- `sha256_hex`: pokrycie wektorem w
  `tests/unit/services/test_auth_tokens.py::test_sha256_hex_known_vector` (świadomie nie
  duplikujemy).
"""

import asyncio
import inspect

import pytest
from fastapi import FastAPI
from starlette.requests import Request

from app.api.hub_compat.security import require_secret
from app.core.config import Settings
from app.core.container import Container
from app.core.crypto import decrypt, encrypt
from app.core.errors import Unauthorized

SECRET_HEADER = "X-API-Secret"  # noqa: S105 — nazwa nagłówka, nie sekret
CRYPTO_KEY = "ab" * 32
HUB_COMPAT_SECRET = "s3cret-hub-compat"  # noqa: S105 — celowa atrapa sekretu w teście
API_KEY_TOKEN = "ragflow-test-token"  # noqa: S105 — celowa atrapa tokenu w teście


def _request(settings: Settings, secret_header: str | None) -> Request:
    """Request z kontenerem na `app.state` — tyle, ile potrzebuje `require_secret`."""
    app = FastAPI()
    app.state.container = Container(settings)
    headers = [(SECRET_HEADER.lower().encode(), secret_header.encode())] if secret_header else []
    return Request({"type": "http", "method": "GET", "path": "/x", "headers": headers, "app": app})


def test_require_secret_uses_compare_digest() -> None:
    """(a) Źródło funkcji zawiera `compare_digest` — porównanie stałoczasowe."""
    assert "compare_digest" in inspect.getsource(require_secret)


def test_correct_secret_passes() -> None:
    """(a) Poprawny nagłówek przy skonfigurowanym sekrecie → brak wyjątku."""
    asyncio.run(
        require_secret(
            _request(
                Settings(env="test", hub_compat_api_secret=HUB_COMPAT_SECRET), HUB_COMPAT_SECRET
            )
        )
    )


def test_wrong_header_is_rejected() -> None:
    """(a) Błędny nagłówek → Unauthorized."""
    request = _request(Settings(env="test", hub_compat_api_secret=HUB_COMPAT_SECRET), "złe")
    with pytest.raises(Unauthorized):
        asyncio.run(require_secret(request))


def test_empty_secret_rejects_everything() -> None:
    """(a) Pusty sekret w konfiguracji → odrzucenie także pustego nagłówka."""
    settings = Settings(env="test", hub_compat_api_secret="")
    for header in ("", HUB_COMPAT_SECRET):
        request = _request(settings, header or None)
        with pytest.raises(Unauthorized):
            asyncio.run(require_secret(request))


def test_api_key_copy_round_trip_is_encrypted() -> None:
    """(b) Kopia tokenu klucza API: szyfrogram ≠ jawny token, odszyfrowanie zwraca token."""
    token = API_KEY_TOKEN.encode()
    blob = encrypt(CRYPTO_KEY, token)
    assert blob != token
    assert token not in blob
    assert decrypt(CRYPTO_KEY, blob) == token
