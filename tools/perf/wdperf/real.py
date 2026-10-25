"""Klient embeddingów z twardym limitem tokenów i cache plikowym (kontrakt C8, WP E5-1 T5).

Moduł jest jedynym miejscem, które dotyka prawdziwego API embeddingów OpenAI
(``POST {base}/embeddings``). Klucz bierze wyłącznie z argumentu (nigdy z pliku
ani logu), a każdy wektor trafia do cache na dysku, więc powtórny bieg nie płaci
za te same teksty. Uruchamiane tylko przez test z markerem ``live``.
"""

from __future__ import annotations

import hashlib
import sys
from array import array
from pathlib import Path
from typing import Any, cast

import httpx

# Twardy limit tokenów jednego biegu (C8) — przekroczenie przerywa pracę wyjątkiem.
TOKEN_HARD_LIMIT: int = 30_000_000
# Maksymalna liczba tekstów w jednym żądaniu do API (C8: wsady po 64).
BATCH_SIZE: int = 64


class TokenBudgetExceeded(RuntimeError):
    """Licznik tokenów przekroczył twardy limit (C8)."""

    def __init__(self, tokens_used: int, limit: int) -> None:
        super().__init__(f"token budget exceeded: {tokens_used} > {limit}")
        self.tokens_used = tokens_used
        self.limit = limit


def estimate_cost(n_chunks: int, avg_tokens: float, usd_per_million: float) -> float:
    """Szacowany koszt embeddingu `n_chunks` tekstów po `avg_tokens` tokenów (C8)."""
    return n_chunks * avg_tokens / 1_000_000 * usd_per_million


def _cache_key(model: str, text: str) -> str:
    """Nazwa pliku cache: sha256 z ``model\\x1ftext`` (jak ``app.llm.cache_keys``)."""
    return hashlib.sha256(f"{model}\x1f{text}".encode()).hexdigest()


def _pack(vector: list[float]) -> bytes:
    """Wektor float32 little-endian (byteswap na maszynach big-endian)."""
    data = array("f", vector)
    if sys.byteorder == "big":
        data.byteswap()
    return data.tobytes()


def _unpack(blob: bytes) -> list[float]:
    """Odwrotność ``_pack``."""
    data = array("f", blob)
    if sys.byteorder == "big":
        data.byteswap()
    return list(data)


class EmbeddingClient:
    """Klient ``POST {base_url}/embeddings`` z licznikiem tokenów i cache plikowym.

    ``transport`` to szew testowy (``httpx.MockTransport``) — produkcyjnie ``None``.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        cache_dir: str | Path,
        limit: int = TOKEN_HARD_LIMIT,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._model = model
        self._limit = limit
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=120.0,
            transport=transport,
        )
        self.tokens_used: int = 0

    async def aclose(self) -> None:
        """Zamyka pulę połączeń HTTP."""
        await self._http.aclose()

    async def __aenter__(self) -> EmbeddingClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    def _read_cache(self, text: str) -> bytes | None:
        """Bajty wektora z cache albo ``None`` przy braku pliku."""
        path = self._cache_dir / f"{_cache_key(self._model, text)}.f32"
        return path.read_bytes() if path.is_file() else None

    def _write_cache(self, text: str, blob: bytes) -> None:
        """Zapisuje wektor do cache (nadpisanie jest bezpieczne — klucz to treść)."""
        (self._cache_dir / f"{_cache_key(self._model, text)}.f32").write_bytes(blob)

    async def _request(self, texts: list[str]) -> list[list[float]]:
        """Jedno żądanie do API; dolicza tokeny i pilnuje limitu (C8)."""
        response = await self._http.post(
            "/embeddings",
            json={"model": self._model, "input": texts, "encoding_format": "float"},
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        self.tokens_used += int(payload["usage"]["total_tokens"])
        if self.tokens_used > self._limit:
            raise TokenBudgetExceeded(self.tokens_used, self._limit)
        ordered = sorted(payload["data"], key=lambda item: item["index"])
        return [list(item["embedding"]) for item in ordered]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Wektory dla `texts` — wsadami po ``BATCH_SIZE``, z cache, w kolejności wejścia."""
        if not texts:
            return []
        result: list[list[float] | None] = [None] * len(texts)
        pending: list[int] = []
        for index, text in enumerate(texts):
            cached = self._read_cache(text)
            if cached is None:
                pending.append(index)
            else:
                result[index] = _unpack(cached)
        for start in range(0, len(pending), BATCH_SIZE):
            batch = pending[start : start + BATCH_SIZE]
            vectors = await self._request([texts[index] for index in batch])
            for index, vector in zip(batch, vectors, strict=True):
                self._write_cache(texts[index], _pack(vector))
                result[index] = vector
        # Każdy indeks jest wypełniony w pętli powyżej (cache albo żądanie).
        return cast("list[list[float]]", result)
