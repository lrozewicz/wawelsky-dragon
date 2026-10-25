"""Uwierzytelnianie SVC: nagłówek `X-API-Secret` (kontrakt C7, K7 §1.7)."""

import hmac

from fastapi import Request

from app.api.auth.principal import container_of
from app.core.errors import Unauthorized

_HEADER = "X-API-Secret"


async def require_secret(request: Request) -> None:
    """Wymaga `X-API-Secret` równego `Settings.hub_compat_api_secret` (stały czas).

    Pusty sekret w konfiguracji odrzuca wszystko (także żądanie z pustym nagłówkiem);
    brak nagłówka traktowany jak `""`. Naruszenie → 401 `{"error": "Unauthorized"}`.
    """
    secret = container_of(request).settings.hub_compat_api_secret.get_secret_value()
    header = request.headers.get(_HEADER, "")
    if not secret or not hmac.compare_digest(header.encode(), secret.encode()):
        raise Unauthorized("Unauthorized")
