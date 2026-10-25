"""Parsowanie żądań SVC: body, aktor, pola wymagane, e-mail ze ścieżki (kontrakt C7)."""

from collections.abc import Mapping

from fastapi import Request

from app.api.auth.principal import json_body
from app.core.errors import ValidationFailed


async def body_of(request: Request) -> dict[str, object]:
    """Ciało JSON żądania jako dict; puste/uszkodzone/nie-dict → `{}` (C7).

    Czyta `Request.body()`, więc działa też dla DELETE z JSON-em (httpx: `json=…`).
    """
    return await json_body(request)


def actor_of(body: Mapping[str, object]) -> str:
    """Aktor mutacji: niepuste `body["actor"]`, inaczej `"X-API-Secret"` (C7, K7 §1.10)."""
    actor = body.get("actor")
    return actor if isinstance(actor, str) and actor else "X-API-Secret"


def require_str(body: Mapping[str, object], name: str, message: str) -> str:
    """Wymagane niepuste pole tekstowe; brak/nie-string/pusty → `ValidationFailed` (C7)."""
    value = body.get(name)
    if not isinstance(value, str) or not value:
        raise ValidationFailed(message)
    return value


def email_of_path(email: str) -> str:
    """E-mail ze ścieżki: `strip()` + lowercase (C7; dopasowanie case-insensitive)."""
    return email.strip().lower()
