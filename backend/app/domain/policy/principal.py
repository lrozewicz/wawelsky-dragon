"""Podmiot dostępu — definicja dosłowna z kontraktu C1 (07 §2)."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Principal:
    """Uwierzytelniony podmiot wywołujący (07 §2)."""

    user_id: str
    email: str
    is_superuser: bool
    is_service: bool
    auth_kind: Literal["jwt", "legacy_token", "api_key", "session_cookie"]
    api_key_id: str | None = None
    scopes: frozenset[str] = frozenset()  # v1: pusty = pełne uprawnienia właściciela
