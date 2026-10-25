"""Klucze cache modułu LLM (kontrakt C10) — czyste funkcje, bez I/O."""

import hashlib
import json
import sys
from array import array
from collections.abc import Mapping, Sequence
from typing import Any

from app.llm.types import ChatMessage

CACHE_TTL_MS = 30 * 24 * 3600 * 1000


def chat_cache_key(  # noqa: PLR0913, PLR0917 — sygnatura z kontraktu C10
    model: str,
    messages: Sequence[ChatMessage],
    temperature: float | None,
    top_p: float | None,
    max_tokens: int | None,
    extra: Mapping[str, Any] | None,
) -> str:
    """Klucz cache odpowiedzi czatu — sha256 z kanonicznego JSON-a argumentów."""
    payload = json.dumps(
        {
            "model": model,
            "messages": [dict(message) for message in messages],
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
            "extra": dict(extra) if extra is not None else None,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def vision_cache_key(  # noqa: PLR0913 — sygnatura z kontraktu E5-H8e §C3
    *,
    model: str,
    base_url: str,
    image_sha256: str,
    prompt: str,
    temperature: float | None,
    max_tokens: int | None,
    extra_body: Mapping[str, Any] | None,
) -> str:
    """Klucz cache wizji — sha256 z kanonicznego JSON-a wejścia (kontrakt C3).

    ``base_url`` i ``extra_body`` wchodzą do klucza (ta sama nazwa modelu na różnych
    endpointach nie dzieli wpisów); ``api_key`` i odrzucone parametry (``_dropped``) — nie.
    """
    payload = json.dumps(
        {
            "kind": "vision",
            "model": model,
            "base_url": base_url,
            "image_sha256": image_sha256,
            "prompt": prompt,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "extra_body": dict(extra_body) if extra_body is not None else None,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def embedding_cache_key(model: str, dim: int, text: str) -> str:
    """Klucz cache wektora — sha256 z ``model\x1fdim\x1ftext``."""
    return hashlib.sha256(f"{model}\x1f{dim}\x1f{text}".encode()).hexdigest()


def pack_vector(vector: Sequence[float]) -> bytes:
    """Wektor float32 little-endian (byteswap na maszynach big-endian)."""
    data = array("f", vector)
    if sys.byteorder == "big":
        data.byteswap()
    return data.tobytes()


def unpack_vector(blob: bytes) -> list[float]:
    """Odwrotność ``pack_vector``."""
    data = array("f", blob)
    if sys.byteorder == "big":
        data.byteswap()
    return list(data)
