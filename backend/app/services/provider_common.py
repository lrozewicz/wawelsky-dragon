"""Wspólne helpery dostawców modeli (kontrakt K13 §0-§4, CONTRACT E3-6b §T1).

Warstwa usług nie może importować modułu tras (import-linter „compat-isolated"), więc stałe
nazw dostawcy (`PROVIDER_NAMES`, `provider_id`, `provider_name`) mieszkają tutaj, a
`app/api/ragflow/routes/models.py` re-eksportuje je pod tymi samymi nazwami.
"""

import hashlib

from app.core.config import Settings
from app.core.crypto import decrypt, encrypt
from app.core.errors import NotFound, ValidationFailed
from app.domain.policy import Action, Principal, ResourceRef, require

# Wartość kolumny `models.provider` / `provider_instances.provider` (K13 §0 p. 3).
PROVIDER_COLUMN = "litellm"

# Nazwa instancji domyślnej (środowiskowej) — zastrzeżona bez rozróżniania wielkości liter.
DEFAULT_INSTANCE_NAME = "default"

# Stała maska klucza API w odpowiedziach (K13 §3 — klucz nigdy nie wraca w plaintekście).
API_KEY_MASK = "********"

# Nazwa dostawcy w odpowiedziach: WD ma jedną bramkę zgodną z OpenAI (K5 §3), w bazie nazwaną
# 'litellm'; złoto v0.27.2 (system--13.json) zna tę fabrykę pod nazwą "OpenAI-API-Compatible".
PROVIDER_NAMES: dict[str, str] = {"litellm": "OpenAI-API-Compatible"}


def provider_name(raw: str) -> str:
    """Nazwa dostawcy z kolumny ``models.provider`` w nazewnictwie upstreamu."""
    return PROVIDER_NAMES.get(raw, raw)


def provider_id(raw: str) -> str:
    """Identyfikator dostawcy: WD nie ma tabeli dostawców → stabilny skrót nazwy (32 hex)."""
    return hashlib.sha256(f"wd-provider:{raw}".encode()).hexdigest()[:32]


def resolve_provider(name: str) -> str:
    """Nazwa dostawcy (upstream, kolumna albo id) → wartość kolumny; brak → 102 (K13 §0 p. 3)."""
    for column, upstream in PROVIDER_NAMES.items():
        if name in (column, upstream, provider_id(column)):
            return column
    raise NotFound(f"Provider {name} not found")


def normalize_base_url(raw: object) -> str:
    """`base_url` w postaci ``http(s)://…`` bez końcowego ``/``; inaczej 101 (K13 §2)."""
    if not isinstance(raw, str) or not raw.startswith(("http://", "https://")):
        raise ValidationFailed("base_url must be an http(s) URL")
    return raw.rstrip("/")


def require_superuser(principal: Principal) -> None:
    """Strażnik zapisu K13 §2 — identyczna decyzja jak `DefaultModelsService.set` (C0 p. 2)."""
    require(principal, Action.MANAGE, ResourceRef(kind="model", owner_id=None))


def encrypt_key(settings: Settings, instance_id: str, plain: str) -> bytes:
    """Klucz instancji: AES-GCM z AAD wiążącym blob z id instancji (K13 §1)."""
    aad = b"provider-instance:" + instance_id.encode()
    return encrypt(settings.crypto_key.get_secret_value(), plain.encode(), aad)


def decrypt_key(settings: Settings, instance_id: str, blob: bytes) -> str:
    """Odwrotność `encrypt_key`; błąd klucza/AAD → ValidationFailed (C7)."""
    aad = b"provider-instance:" + instance_id.encode()
    return decrypt(settings.crypto_key.get_secret_value(), blob, aad).decode()


def is_default_name(name: str) -> bool:
    """Czy nazwa instancji to zastrzeżona „default" (bez rozróżniania wielkości liter)."""
    return name.casefold() == DEFAULT_INSTANCE_NAME


def dedupe(items: list[str]) -> list[str]:
    """Lista bez powtórzeń, w kolejności pierwszego wystąpienia (K13 §4 p. 3, 8).

    Powtórzone pozycje żądania DELETE (instancje albo modele) są jedną operacją: jeden wpis
    audytu na obiekt, bez błędu.
    """
    return list(dict.fromkeys(items))
