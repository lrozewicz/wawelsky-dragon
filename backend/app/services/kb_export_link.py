"""Podpisany link pobrania eksportu i ścieżki paczki (kontrakt E7-1a §2, T0).

Bezstanowy moduł pomocniczy dla akcji ``export_dataset`` (worker) i trasy pobrania
(``GET /exports/{task_id}/download``). Link niesie ``task_id``, ``exp`` (sekundowa data
wygaśnięcia) i ``sig`` = hex(HMAC-SHA256(secret, ``export:{task_id}:{exp}``)) — serwer
weryfikuje podpis bez trzymania stanu sesji. ``secret`` to ``settings.secret_key``.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import unicodedata
from pathlib import Path

__all__ = [
    "EXPORTS_DIR",
    "EXPORT_LINK_TTL_S",
    "download_path",
    "export_file_name",
    "export_package_path",
    "sign_export",
    "verify_export",
]

# Domyślny czas życia linku pobrania (24 h) — kontrakt E7-1a §2.
EXPORT_LINK_TTL_S = 86_400

# Podkatalog storage z gotowymi paczkami eksportu (`<root>/exports/<task_id>.wdkb.zip`).
EXPORTS_DIR = "exports"

# Maksymalna długość slugu w nazwie pliku (kontrakt E7-1a §2).
_SLUG_MAX = 64

# Token slugu: ciąg małych liter ASCII i cyfr; myślniki dokładamy sami przy sklejaniu.
_SLUG_WORD = re.compile(r"[a-z0-9]+")


def sign_export(secret: str, task_id: str, exp: int) -> str:
    """Zwraca hex(HMAC-SHA256(secret, ``export:{task_id}:{exp}``)) — podpis linku pobrania."""
    message = f"export:{task_id}:{exp}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify_export(secret: str, task_id: str, exp: int, sig: str) -> bool:
    """Sprawdza podpis linku; zły/pusty/nie-ASCII ``sig`` → ``False`` (bez wyjątku).

    Porównanie przez ``hmac.compare_digest`` na bajtach — długość i znaki nie ujawniają
    informacji o poprawnym podpisie.
    """
    expected = sign_export(secret, task_id, exp)
    return hmac.compare_digest(sig.encode(), expected.encode())


def download_path(task_id: str, exp: int, sig: str) -> str:
    """Ścieżka trasy pobrania z parametrami ``exp`` i ``sig`` (bez domeny)."""
    return f"/api/wd/v1/exports/{task_id}/download?exp={exp}&sig={sig}"


def export_file_name(dataset_name: str) -> str:
    """Nazwa pliku paczki: ``<slug>.wdkb.zip``; slug ASCII (ł→l, bez znaków łączących).

    Slug: NFKD, ``ł``→``l``, bez znaków diakrytycznych (kategoria ``Mn``), tokeny ``[a-z0-9]``
    sklejone myślnikami, obcięte do 64 znaków bez końcowego ``-``; brak tokenów → ``dataset``.
    """
    folded = unicodedata.normalize("NFKD", dataset_name.lower()).replace("ł", "l")
    kept = "".join(ch for ch in folded if unicodedata.category(ch) != "Mn")
    slug = "-".join(_SLUG_WORD.findall(kept))
    if len(slug) > _SLUG_MAX:
        slug = slug[:_SLUG_MAX].rstrip("-")
    return f"{slug or 'dataset'}.wdkb.zip"


def export_package_path(storage_root: str | Path, task_id: str) -> Path:
    """Ścieżka gotowej paczki: ``<storage_root>/exports/<task_id>.wdkb.zip``."""
    return Path(storage_root) / EXPORTS_DIR / f"{task_id}.wdkb.zip"
