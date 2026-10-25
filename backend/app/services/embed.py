"""Embeddingi: mieszanie wektora tytułu z treścią i liczenie partiami (kontrakt C5).

Moduł czysty — bez bazy; portem jest ``LLMGateway.embed`` (K5 §3.3).
"""

import asyncio
import math
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from app.llm.gateway import LLMGateway
from app.llm.types import ModelRef
from app.worker.errors import PermanentError

# Waga nazwy pliku w mieszaniu wektora, gdy parser_config jej nie podaje (krok 10 ingestu).
DEFAULT_FILENAME_EMBD_WEIGHT = 0.1
# Poniżej tej normy wektor uznajemy za zerowy (jak upstream ``eps=1e-12`` w ``_cos_sim``).
_ZERO_NORM = 1e-12


def recipe_text(content: str, questions: Sequence[str]) -> str:
    """Tekst poddawany embeddingowi: pytania, a gdy ich brak — treść (kroki 9-11 ingestu).

    Przepis obowiązujący też przy re-embeddingu w ``embedding/check`` (DEC-033 p. 4):
    wektor zapisany i wektor przeliczony muszą pochodzić z tego samego tekstu.
    """
    return "\n".join(questions) if questions else content


def filename_weight(parser_config: Mapping[str, Any]) -> float:
    """Waga wektora tytułu w mieszaniu (``parser_config.filename_embd_weight``, domyślnie 0.1)."""
    raw = parser_config.get("filename_embd_weight")
    return DEFAULT_FILENAME_EMBD_WEIGHT if raw is None else float(raw)


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Cosinus dwóch wektorów; zerowa norma którejkolwiek strony → 0.0 (jak upstream)."""
    if len(left) != len(right):
        raise ValueError(f"vector length {len(left)} does not match {len(right)}")
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    if norm_left < _ZERO_NORM or norm_right < _ZERO_NORM:
        return 0.0
    return dot / (norm_left * norm_right)


def combine(title_vec: Sequence[float], content_vec: Sequence[float], weight: float) -> list[float]:
    """Miesza wektor tytułu (waga ``weight``) z treścią (``1-weight``) i normalizuje do L2.

    Norma zero (wektor zerowy) → wynik bez dzielenia. Różne długości → ``ValueError``.
    """
    if len(title_vec) != len(content_vec):
        raise ValueError(
            f"title_vec length {len(title_vec)} "
            f"does not match content_vec length {len(content_vec)}"
        )
    mixed = [weight * t + (1.0 - weight) * c for t, c in zip(title_vec, content_vec, strict=True)]
    norm = math.sqrt(sum(x * x for x in mixed))
    if norm == 0:
        return mixed
    return [x / norm for x in mixed]


async def embed_texts(  # noqa: PLR0912, PLR0913 — sygnatura z kontraktu C3
    llm: LLMGateway,
    model: ModelRef,
    texts: Sequence[str],
    *,
    batch_size: int,
    expected_dim: int,
    concurrency: int = 1,
    on_batch: Callable[[int, int], Awaitable[None]] | None = None,
    check_cancel: Callable[[], Awaitable[None]] | None = None,
) -> list[list[float]]:
    """Liczy embeddingi partiami po ``batch_size``, najwyżej ``concurrency`` partii w locie.

    Wynik w kolejności ``texts`` (partie składane po indeksie, niezależnie od kolejności
    ukończeń). ``check_cancel`` (jeśli podane) wołane przed startem KAŻDEJ partii; jego wyjątek
    przerywa — żadne nowe partie nie startują, trwające są anulowane, wyjątek propaguje.
    ``on_batch(done, total)`` wołane z jednego miejsca po każdej ukończonej partii; ``done``
    rośnie ściśle, ostatnie wywołanie ma ``done == total``. Wektor o długości różnej od
    ``expected_dim`` → ``PermanentError``. Pusta lista → ``[]`` bez wywołań;
    ``batch_size < 1`` lub ``concurrency < 1`` → ``ValueError``.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    if not texts:
        return []
    batches = [
        list(texts[start : start + batch_size]) for start in range(0, len(texts), batch_size)
    ]
    total = len(texts)
    results: list[list[list[float]]] = [[] for _ in batches]
    done = 0
    running: dict[asyncio.Task[list[list[float]]], int] = {}
    next_index = 0
    try:
        while next_index < len(batches) or running:
            while next_index < len(batches) and len(running) < concurrency:
                if check_cancel is not None:
                    await check_cancel()
                task = asyncio.create_task(llm.embed(model, batches[next_index]))
                running[task] = next_index
                next_index += 1
            if not running:
                break
            completed, _ = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
            for task in completed:
                index = running.pop(task)
                vectors = task.result()
                for vector in vectors:
                    if len(vector) != expected_dim:
                        raise PermanentError(
                            f"embedding dimension {len(vector)} "
                            f"does not match dataset embedding_dim {expected_dim}"
                        )
                results[index] = vectors
                done += len(batches[index])
                if on_batch is not None:
                    await on_batch(done, total)
    finally:
        for task in running:
            task.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)
    return [vector for batch in results for vector in batch]
