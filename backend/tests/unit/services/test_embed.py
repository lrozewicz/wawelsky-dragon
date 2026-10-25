"""Testy app.services.embed — mieszanie wektorów i embeddingi partiami (brief T5)."""

import asyncio
import math
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.core.container import Container
from app.llm.types import ModelRef
from app.services.embed import combine, embed_texts
from app.services.ingest_pipeline import _embed_all
from app.worker.errors import PermanentError, TaskCancelled

MODEL = ModelRef(None, "fake-embed", "embedding", dimension=3)


class FakeEmbedder:
    """Atrapa LLMGateway.embed: zapis partii w kolejności, wektory zerowe o zadanym wymiarze."""

    def __init__(self, dim: int = 3) -> None:
        self.dim = dim
        self.batches: list[list[str]] = []

    async def embed(self, model: ModelRef, texts: list[str]) -> list[list[float]]:
        self.batches.append(list(texts))
        return [[0.0] * self.dim for _ in texts]


# --- combine (przykłady z briefu T5) ---


def test_combine_mixture_normalized_to_l2() -> None:
    result = combine([1, 0], [0, 1], 0.1)
    norm = math.sqrt(0.82)
    assert result == pytest.approx([0.1 / norm, 0.9 / norm])


def test_combine_zero_norm_returns_unnormalized() -> None:
    assert combine([0, 0], [0, 0], 0.5) == [0.0, 0.0]


def test_combine_length_mismatch_raises() -> None:
    with pytest.raises(ValueError):
        combine([1, 0], [1], 0.5)


# --- embed_texts (przykłady z briefu T5) ---


async def test_embed_texts_batches_and_on_batch() -> None:
    llm = FakeEmbedder()
    progress: list[tuple[int, int]] = []

    async def on_batch(done: int, total: int) -> None:
        progress.append((done, total))

    vectors = await embed_texts(
        llm, MODEL, ["a", "b", "c", "d", "e"], batch_size=2, expected_dim=3, on_batch=on_batch
    )
    assert llm.batches == [["a", "b"], ["c", "d"], ["e"]]
    assert progress == [(2, 5), (4, 5), (5, 5)]
    assert len(vectors) == 5  # noqa: PLR2004 — jeden wektor na tekst
    assert vectors[0] == [0.0, 0.0, 0.0]


async def test_embed_texts_empty_list_makes_no_calls() -> None:
    llm = FakeEmbedder()
    assert await embed_texts(llm, MODEL, [], batch_size=2, expected_dim=3) == []
    assert llm.batches == []


async def test_embed_texts_batch_size_below_one_raises() -> None:
    llm = FakeEmbedder()
    with pytest.raises(ValueError):
        await embed_texts(llm, MODEL, ["a"], batch_size=0, expected_dim=3)


async def test_embed_texts_wrong_dimension_raises_permanent() -> None:
    llm = FakeEmbedder(dim=4)
    with pytest.raises(
        PermanentError,
        match="embedding dimension 4 does not match dataset embedding_dim 3",
    ):
        await embed_texts(llm, MODEL, ["a"], batch_size=2, expected_dim=3)


# --- etap embeddingu w pipeline (Stop po partii, MINOR T7/T10) ---


class _Reporter:
    """Reporter bez zapisu do bazy — zbiera komunikaty."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    async def report(self, progress: float, msg: str | None = None) -> None:
        self.messages.append(msg or "")


class _ConcurrencyEmbedder:
    """Atrapa LLMGateway.embed z licznikiem maks. partii w locie (opóźnienie per partia)."""

    def __init__(self, dim: int = 3, *, delay: float = 0.02) -> None:
        self.dim = dim
        self.delay = delay
        self.inflight = 0
        self.max_inflight = 0

    async def embed(self, model: ModelRef, texts: list[str]) -> list[list[float]]:
        self.inflight += 1
        self.max_inflight = max(self.max_inflight, self.inflight)
        try:
            await asyncio.sleep(self.delay)
            return [[0.0] * self.dim for _ in texts]
        finally:
            self.inflight -= 1


INGEST_CONCURRENCY = 3


async def test_embed_all_forwards_concurrency_to_embed_texts() -> None:
    """`_embed_all` przekazuje `concurrency` do fazy chunków (kontrakt C3).

    Partia tytułu zostaje przy `concurrency=1`; równoległość widać dopiero na chunkach.
    Domyka weryfikację E2E, która przez wspólny licznik fake-llm sprawdza tylko `>=`.
    """
    llm = _ConcurrencyEmbedder()
    container = Container(Settings(env="test", embed_batch_size=1))
    ds = SimpleNamespace(embedding_dim=3)
    prepared = [SimpleNamespace(embed_text=f"t{i}") for i in range(9)]

    async def check_cancel() -> None:
        return None

    await _embed_all(
        container,
        _Reporter(),
        SimpleNamespace(check_cancel=check_cancel),
        llm,
        MODEL,
        ds,
        {},
        "doc",
        prepared,
        INGEST_CONCURRENCY,
    )
    assert llm.max_inflight == INGEST_CONCURRENCY


async def test_embedding_stage_stops_after_cancelled_batch() -> None:
    """SC-E5-H8a-02: Stop przed partią embeddingu przerywa pipeline (kontrakt C3).

    ``embed_texts`` woła ``check_cancel`` przed startem KAŻDEJ partii. Wyjątek anulowania
    (druga partia) przerywa pętlę, więc bramka nie dostaje kolejnych partii — żadne dalsze
    wektory nie powstają.
    """
    llm = FakeEmbedder()
    container = Container(Settings(env="test", embed_batch_size=2))
    ds = SimpleNamespace(embedding_dim=3)
    prepared = [SimpleNamespace(embed_text=f"t{i}") for i in range(5)]
    checks = {"n": 0}

    async def check_cancel() -> None:
        checks["n"] += 1
        if checks["n"] >= 2:  # noqa: PLR2004 — Stop zgłoszony przed drugą partią chunków
            raise TaskCancelled(1)

    with pytest.raises(TaskCancelled):
        await _embed_all(
            container,
            _Reporter(),
            SimpleNamespace(check_cancel=check_cancel),
            llm,
            MODEL,
            ds,
            {},
            "doc",
            prepared,
        )

    # Partia tytułu + pierwsza partia chunków; po niej Stop — żadnych dalszych partii.
    assert llm.batches == [["doc"], ["t0", "t1"]]
