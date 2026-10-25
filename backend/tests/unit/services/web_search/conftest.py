"""Pomocniki testów dostawców wyszukiwania (CONTRACT E6-3f §C4, K18 §5).

Testy jadą na nagranych odpowiedziach dostawców (`tests/fixtures/web_search/*.json`) przez
`httpx.MockTransport` — bez sieci (Q19).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

#: Katalog nagranych odpowiedzi dostawców (backend/tests/fixtures/web_search).
FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "web_search"

#: Handler MockTransport: żądanie → odpowiedź (może też rzucić `httpx.HTTPError`).
Handler = Callable[[httpx.Request], httpx.Response]


def load_fixture(name: str) -> Any:
    """Nagrana odpowiedź dostawcy jako obiekt JSON (§C4)."""
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def json_response(payload: Any, *, status: int = 200) -> httpx.Response:
    """Odpowiedź JSON nagranym ciałem (§C4)."""
    return httpx.Response(status, json=payload)


def client_with(handler: Handler) -> httpx.AsyncClient:
    """Klient `httpx` z `MockTransport` — wstrzykiwany do dostawcy (bez sieci)."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))
