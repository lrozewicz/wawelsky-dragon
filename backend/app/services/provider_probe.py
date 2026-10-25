"""Sonda listy modeli dostawcy: ``GET {base_url}/models`` (K13 §4 p. 4-5).

Żądanie po sieci klientem ``httpx2`` (K10 §1) z limitem 10 s. Sukces = HTTP 200 i JSON
z listą ``data``; każda inna odpowiedź albo błąd transportu → 102 z komunikatem, który
**nie zawiera** klucza ani treści odpowiedzi bramki. Transport jest wstrzykiwalny
(``httpx2.MockTransport`` w testach jednostkowych).
"""

from __future__ import annotations

import httpx2

from app.core.errors import Conflict

# Limit czasu żądania i ścieżka listy modeli bramki zgodnej z OpenAI (K13 §4 p. 4).
TIMEOUT_S = 10.0
MODELS_PATH = "/models"
HTTP_OK = 200

# Transport podstawiany w testach (``httpx2.MockTransport``); ``None`` = realna sieć.
_transport: httpx2.AsyncBaseTransport | None = None


def _headers(api_key: str | None) -> dict[str, str]:
    """Nagłówek ``Authorization`` tylko gdy klucz niepusty (K13 §4 p. 4)."""
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


async def probe_models(base_url: str, api_key: str | None) -> list[str]:
    """Identyfikatory modeli wystawionych przez bramkę ``base_url`` (K13 §4 p. 4).

    Porażka → 102 ``Connection failed: HTTP <status>`` albo
    ``Connection failed: <nazwa klasy wyjątku>``.
    """
    async with httpx2.AsyncClient(timeout=TIMEOUT_S, transport=_transport) as client:
        try:
            response = await client.get(f"{base_url}{MODELS_PATH}", headers=_headers(api_key))
        except (httpx2.HTTPError, UnicodeEncodeError) as exc:
            # UnicodeEncodeError: httpx2 koduje nagłówki jako ASCII, więc klucz spoza ASCII
            # (np. twarda spacja z wklejenia) też jest porażką połączenia, nie błędem serwera.
            raise Conflict(f"Connection failed: {type(exc).__name__}") from exc
    if response.status_code != HTTP_OK:
        raise Conflict(f"Connection failed: HTTP {response.status_code}")
    try:
        payload = response.json()
        return sorted(str(item["id"]) for item in payload["data"])
    except (TypeError, ValueError, KeyError) as exc:
        raise Conflict(f"Connection failed: {type(exc).__name__}") from exc
