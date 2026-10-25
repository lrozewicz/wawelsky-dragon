"""Testy jednostkowe klienta embeddingów (``wdperf.real``) — kontrakt C8.

Bez sieci: ``httpx.MockTransport`` podstawiamy szwem ``transport``. Testy pilnują
licznika tokenów, cache (powtórka nie idzie do HTTP), twardego limitu i szacunku kosztu.
"""

import json
import struct
from pathlib import Path

import httpx
import pytest

from wdperf import real

DIM = 4
# Liczba tokenów raportowana przez atrapę na każdy tekst żądania.
TOKENS_PER_TEXT = 7


def _vector(seed: int) -> list[float]:
    """Deterministyczny wektor o długości ``DIM`` (float, nie int)."""
    return [seed + 0.25 * i for i in range(DIM)]


class _Server:
    """Atrapa API embeddingów: liczy żądania i zwraca wektory z indeksami."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.fail_next: int | None = None

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = json.loads(request.content)
        if self.fail_next is not None:
            status, self.fail_next = self.fail_next, None
            return httpx.Response(status, json={"error": {"message": "atrapa"}})
        texts = body["input"]
        data = [
            {"object": "embedding", "index": index, "embedding": _vector(index)}
            for index in range(len(texts))
        ]
        return httpx.Response(
            200,
            json={
                "object": "list",
                "model": body["model"],
                "data": data,
                "usage": {
                    "prompt_tokens": TOKENS_PER_TEXT * len(texts),
                    "total_tokens": TOKENS_PER_TEXT * len(texts),
                },
            },
        )

    @property
    def inputs(self) -> list[list[str]]:
        """Listy tekstów z kolejnych żądań."""
        return [json.loads(request.content)["input"] for request in self.requests]


def _client(tmp_path: Path, server: _Server, **overrides: object) -> real.EmbeddingClient:
    """Klient na atrapie API (``transport`` to szew testowy z C8)."""
    arguments: dict[str, object] = {
        "base_url": "https://api.example.test/v1",
        "api_key": "test-key",
        "model": "text-embedding-3-large",
        "cache_dir": tmp_path / "cache",
        "transport": server.transport(),
    }
    arguments.update(overrides)
    return real.EmbeddingClient(**arguments)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# estimate_cost
# ---------------------------------------------------------------------------


def test_estimate_cost_of_ten_thousand_chunks() -> None:
    # 10 000 chunków x 150 tokenów x 0.13 USD / 1M = 0.195 USD.
    assert real.estimate_cost(10_000, 150.0, 0.13) == pytest.approx(0.195)


def test_estimate_cost_is_linear_and_zero_for_no_chunks() -> None:
    assert real.estimate_cost(0, 150.0, 0.13) == 0.0
    assert real.estimate_cost(2_000, 150.0, 0.13) * 5 == pytest.approx(
        real.estimate_cost(10_000, 150.0, 0.13)
    )


def test_token_hard_limit_matches_contract() -> None:
    assert real.TOKEN_HARD_LIMIT == 30_000_000


# ---------------------------------------------------------------------------
# Licznik tokenów i kształt odpowiedzi
# ---------------------------------------------------------------------------


async def test_embed_returns_vectors_in_input_order(tmp_path: Path) -> None:
    server = _Server()
    async with _client(tmp_path, server) as client:
        vectors = await client.embed(["a", "b", "c"])
    assert vectors == [_vector(0), _vector(1), _vector(2)]
    assert all(isinstance(value, float) for vector in vectors for value in vector)


async def test_embed_request_carries_model_and_texts(tmp_path: Path) -> None:
    server = _Server()
    async with _client(tmp_path, server) as client:
        await client.embed(["a", "b"])
    body = json.loads(server.requests[0].content)
    assert body == {
        "model": "text-embedding-3-large",
        "input": ["a", "b"],
        "encoding_format": "float",
    }
    # Klient wysyła klucz wyłącznie w nagłówku (nigdzie go nie loguje).
    assert server.requests[0].headers["Authorization"] == "Bearer test-key"


async def test_embed_counts_usage_tokens_across_requests(tmp_path: Path) -> None:
    server = _Server()
    async with _client(tmp_path, server) as client:
        await client.embed(["a", "b", "c"])
        assert client.tokens_used == 3 * TOKENS_PER_TEXT
        await client.embed(["d"])
        assert client.tokens_used == 4 * TOKENS_PER_TEXT


async def test_embed_empty_list_makes_no_request(tmp_path: Path) -> None:
    server = _Server()
    async with _client(tmp_path, server) as client:
        assert await client.embed([]) == []
        assert client.tokens_used == 0
    assert server.requests == []


async def test_embed_splits_into_batches_of_64(tmp_path: Path) -> None:
    server = _Server()
    async with _client(tmp_path, server) as client:
        vectors = await client.embed([f"t{i}" for i in range(130)])
    assert [len(batch) for batch in server.inputs] == [64, 64, 2]
    assert len(vectors) == 130
    assert vectors[129] == _vector(1)


# ---------------------------------------------------------------------------
# Cache plikowy
# ---------------------------------------------------------------------------


async def test_second_identical_embed_uses_cache_and_makes_no_request(tmp_path: Path) -> None:
    server = _Server()
    async with _client(tmp_path, server) as client:
        first = await client.embed(["a", "b"])
        requests_after_first = len(server.requests)
        second = await client.embed(["a", "b"])
        tokens_after_second = client.tokens_used
    assert first == second
    assert len(server.requests) == requests_after_first
    assert tokens_after_second == 2 * TOKENS_PER_TEXT  # powtórka = 0 tokenów


async def test_cache_file_holds_float32_little_endian(tmp_path: Path) -> None:
    server = _Server()
    cache_dir = tmp_path / "cache"
    async with _client(tmp_path, server) as client:
        vectors = await client.embed(["a"])
    files = list(cache_dir.glob("*.f32"))
    assert len(files) == 1
    blob = files[0].read_bytes()
    assert len(blob) == 4 * DIM
    assert list(struct.unpack(f"<{DIM}f", blob)) == [pytest.approx(v) for v in vectors[0]]


async def test_cache_serves_only_missing_texts(tmp_path: Path) -> None:
    server = _Server()
    async with _client(tmp_path, server) as client:
        await client.embed(["a", "b"])
        requests_after_first = len(server.requests)
        vectors = await client.embed(["a", "c", "b"])
    assert server.inputs[requests_after_first:] == [["c"]]
    assert vectors == [_vector(0), _vector(0), _vector(1)]


async def test_client_creates_nested_cache_dir(tmp_path: Path) -> None:
    server = _Server()
    cache_dir = tmp_path / "nested" / "cache"
    _client(tmp_path, server, cache_dir=cache_dir)
    assert cache_dir.is_dir()


async def test_cache_is_keyed_by_model(tmp_path: Path) -> None:
    server = _Server()
    async with _client(tmp_path, server) as client:
        await client.embed(["a"])
        other = _client(tmp_path, server, model="text-embedding-3-small")
        async with other:
            await other.embed(["a"])
    assert [len(batch) for batch in server.inputs] == [1, 1]


async def test_http_error_propagates(tmp_path: Path) -> None:
    server = _Server()
    server.fail_next = 500
    async with _client(tmp_path, server) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await client.embed(["a"])


# ---------------------------------------------------------------------------
# Twardy limit tokenów
# ---------------------------------------------------------------------------


async def test_token_budget_exceeded_when_counter_passes_limit(tmp_path: Path) -> None:
    server = _Server()
    # limit 10 < 2 x 7 tokenów — druga porcja przekracza budżet.
    async with _client(tmp_path, server, limit=10) as client:
        with pytest.raises(real.TokenBudgetExceeded) as error:
            await client.embed(["a", "b"])
        assert client.tokens_used == 2 * TOKENS_PER_TEXT
    assert error.value.tokens_used == 2 * TOKENS_PER_TEXT
    assert error.value.limit == 10
    assert isinstance(error.value, RuntimeError)


async def test_token_budget_raises_only_above_limit(tmp_path: Path) -> None:
    server = _Server()
    # limit dokładnie równy zużyciu nie jest przekroczeniem (C8: „po przekroczeniu”).
    async with _client(tmp_path, server, limit=TOKENS_PER_TEXT) as client:
        assert len(await client.embed(["a"])) == 1
        assert client.tokens_used == TOKENS_PER_TEXT
