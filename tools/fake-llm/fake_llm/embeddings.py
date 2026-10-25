"""Deterministyczne embeddingi i endpoint `POST /v1/embeddings` (K10 §3, C4)."""

import asyncio
import base64
import hashlib
import math
import random
import struct
from functools import cache
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel

from fake_llm import stats
from fake_llm.errors import OpenAIError, model_not_found
from fake_llm.models import EMBED_DIMS, base_model
from fake_llm.tokens import tokenize

# Błąd 429 wstrzykiwany przez `POST /v1/fake/embed-429` (C6), format OpenAI.
_ERROR_429: dict[str, object] = {"message": "rate limited", "type": "rate_limit_error"}


class EmbeddingRequest(BaseModel):
    """Ciało żądania `POST /v1/embeddings` (pola spoza modelu są ignorowane)."""

    model: str
    input: str | list[str]
    dimensions: int | None = None
    encoding_format: Literal["float", "base64"] = "float"


@cache
def _token_vector(model: str, token: str) -> tuple[float, ...]:
    """Wektor tokenu z seeda sha256(model + "\\x1f" + token), cache'owany (C4)."""
    dim = EMBED_DIMS[model]
    digest = hashlib.sha256((model + "\x1f" + token).encode("utf-8")).digest()
    rng = random.Random(int.from_bytes(digest, "big"))  # noqa: S311 - generator z seedem, nie kryptografia
    return tuple(rng.gauss(0.0, 1.0) for _ in range(dim))


def _normalize(vector: list[float]) -> list[float]:
    """Normalizacja L2."""
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector]


def embed(model: str, text: str, dimensions: int | None = None) -> list[float]:
    """Wektor embeddingu: suma wektorów tokenów znormalizowana L2 (bez tokenów: seed z modelu)."""
    dim = EMBED_DIMS[model]
    tokens = tokenize(text)
    if tokens:
        accumulated = [0.0] * dim
        for token in tokens:
            for i, value in enumerate(_token_vector(model, token)):
                accumulated[i] += value
    else:
        digest = hashlib.sha256((model + "\x1f").encode("utf-8")).digest()
        rng = random.Random(int.from_bytes(digest, "big"))  # noqa: S311 - generator z seedem, jak wyżej
        accumulated = [rng.gauss(0.0, 1.0) for _ in range(dim)]
    result = _normalize(accumulated)
    if dimensions is not None:
        result = _normalize(result[:dimensions])
    return result


def _encode(vector: list[float], encoding_format: Literal["float", "base64"]) -> object:
    """`float` → lista; `base64` → float32 little-endian zakodowany base64 (jak OpenAI, [R-4])."""
    if encoding_format == "base64":
        return base64.b64encode(struct.pack(f"<{len(vector)}f", *vector)).decode("ascii")
    return vector


router = APIRouter()


@router.post("/v1/embeddings")
async def create_embeddings(body: EmbeddingRequest) -> dict[str, Any]:
    """`POST /v1/embeddings` w formacie OpenAI; sterowalne opóźnienie i wstrzykiwanie 429 (C6).

    Alias `<model>~<scope>` jest akceptowany jak baza; liczniki/reguły zawężone idą po pełnej
    nazwie, a treść odpowiedzi liczymy z nazwy bazowej (C8).
    """
    base = base_model(body.model)
    if base not in EMBED_DIMS:
        raise model_not_found(body.model)
    # Licznik współbieżności modelu (C6): od wejścia do wyjścia z handlera, razem z opóźnieniem.
    stats.enter_model(body.model)
    try:
        stats.record_embed_request(body.model)
        if stats.should_reject_embed(body.model):
            stats.record_rejected_429()
            raise OpenAIError(429, _ERROR_429, headers=stats.retry_after_header(body.model))
        # Wstrzykiwanie 5xx (C7): po zliczeniu żądania, przed opóźnieniem; `embed-429` ma
        # pierwszeństwo, więc ta kontrola następuje po nim. Reguła zawężona po `body.model` (C8).
        upstream_error = stats.upstream_error_for("embeddings", body.model)
        if upstream_error is not None:
            raise upstream_error
        # Opóźnienie odpowiedzi (C6): po zliczeniu żądania, przed odpowiedzią;
        # odrzuconego 429 nie dotyczy. Reguła zawężona po `body.model` (C8).
        delay_ms = stats.embed_delay_ms(body.model)
        if delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000)
        dim = EMBED_DIMS[base]
        if body.dimensions is not None and not 1 <= body.dimensions <= dim:
            raise OpenAIError(
                400,
                {
                    "message": f"dimensions must be between 1 and {dim}",
                    "type": "invalid_request_error",
                    "param": "dimensions",
                    "code": None,
                },
            )
        inputs = [body.input] if isinstance(body.input, str) else body.input
        total_tokens = sum(len(tokenize(text)) for text in inputs)
        data = [
            {
                "object": "embedding",
                "index": index,
                "embedding": _encode(embed(base, text, body.dimensions), body.encoding_format),
            }
            for index, text in enumerate(inputs)
        ]
        return {
            "object": "list",
            "data": data,
            "model": body.model,
            "usage": {"prompt_tokens": total_tokens, "total_tokens": total_tokens},
        }
    finally:
        stats.exit_model(body.model)
