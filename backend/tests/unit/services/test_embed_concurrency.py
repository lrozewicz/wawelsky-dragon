"""Testy `embed_texts(concurrency=…)` i `resolve_concurrency` (E5-H8b T5)."""

import asyncio

import pytest

from app.llm.types import ModelRef

MODEL = ModelRef(None, "fake-embed", "embedding", dimension=3)
DIM_3 = 3
LIMIT_2 = 2
CONCURRENCY_4 = 4


class _StubGateway:
    """Atrapa ``LLMGateway.embed``: partie, maks. liczba w locie i opóźnienia per partia.

    Wektor tekstu ``"<i>"`` to ``[float(i)] * dim`` — pozwala sprawdzić kolejność wyniku.
    Opóźnienie partii bierzemy z ``delays[int(tekst[0])]`` (klucz = wartość pierwszego tekstu).
    """

    def __init__(self, *, dim: int = DIM_3, delays: dict[int, float] | None = None) -> None:
        self.dim = dim
        self.delays = delays or {}
        self.batches: list[list[str]] = []
        self.inflight = 0
        self.max_inflight = 0

    async def embed(self, model: ModelRef, texts: list[str]) -> list[list[float]]:
        batch = list(texts)
        self.batches.append(batch)
        self.inflight += 1
        self.max_inflight = max(self.max_inflight, self.inflight)
        try:
            delay = self.delays.get(int(batch[0]), 0.0)
            if delay:
                await asyncio.sleep(delay)
            return [[float(text)] * self.dim for text in batch]
        finally:
            self.inflight -= 1


async def test_embed_texts_result_in_texts_order_despite_random_completion() -> None:
    """Wynik w kolejności `texts`, choć partie kończą się w innej kolejności (opóźnienia)."""
    from app.services.embed import embed_texts  # noqa: PLC0415 — brak symbolu nie psuje kolekcji

    texts = [str(i) for i in range(12)]
    delays = {i: 0.03 * ((i * 5) % 4) for i in range(12)}
    llm = _StubGateway(delays=delays)
    vectors = await embed_texts(
        llm, MODEL, texts, batch_size=3, expected_dim=DIM_3, concurrency=CONCURRENCY_4
    )
    assert [vector[0] for vector in vectors] == [float(i) for i in range(12)]


async def test_embed_texts_on_batch_strictly_increasing_and_final_done_equals_total() -> None:
    """`on_batch(done, total)`: ściśle rosnące `done`, ostatnie wywołanie `done == total`."""
    from app.services.embed import embed_texts  # noqa: PLC0415

    calls: list[tuple[int, int]] = []

    async def on_batch(done: int, total: int) -> None:
        calls.append((done, total))

    llm = _StubGateway()
    texts = [str(i) for i in range(10)]
    await embed_texts(
        llm, MODEL, texts, batch_size=2, expected_dim=DIM_3, concurrency=3, on_batch=on_batch
    )
    dones = [done for done, _total in calls]
    assert dones == sorted(dones), "done musi rosnąć"
    assert len(set(dones)) == len(dones), "done musi być ściśle rosnące (bez powtórzeń)"
    assert calls[-1] == (10, 10)


async def test_embed_texts_check_cancel_before_batch_three_stops_further_batches() -> None:
    """`check_cancel` rzuca w trzeciej partii → partie ≥ 4 nie startują (kolejno, concurrency=1)."""
    from app.services.embed import embed_texts  # noqa: PLC0415
    from app.worker.errors import TaskCancelled  # noqa: PLC0415

    checks = {"n": 0}

    async def check_cancel() -> None:
        checks["n"] += 1
        if checks["n"] >= LIMIT_2 + 1:
            raise TaskCancelled(1)

    llm = _StubGateway()
    with pytest.raises(TaskCancelled):
        await embed_texts(
            llm,
            MODEL,
            [str(i) for i in range(10)],
            batch_size=1,
            expected_dim=DIM_3,
            concurrency=1,
            check_cancel=check_cancel,
        )
    # Partie 1-2 wystartowały; trzecie wywołanie `check_cancel` przerwało przed startem partii 3.
    assert len(llm.batches) == LIMIT_2


async def test_embed_texts_caps_inflight_at_concurrency() -> None:
    """Maks. liczba partii w locie == `concurrency` (Semaphore/TaskGroup)."""
    from app.services.embed import embed_texts  # noqa: PLC0415

    llm = _StubGateway(delays={i: 0.02 for i in range(20)})
    await embed_texts(
        llm,
        MODEL,
        [str(i) for i in range(20)],
        batch_size=1,
        expected_dim=DIM_3,
        concurrency=CONCURRENCY_4,
    )
    assert llm.max_inflight == CONCURRENCY_4


async def test_embed_texts_concurrency_one_is_sequential() -> None:
    """`concurrency=1` zachowuje się jak dotąd: partie po kolei, najwyżej jedna w locie."""
    from app.services.embed import embed_texts  # noqa: PLC0415

    llm = _StubGateway(delays={i: 0.01 for i in range(6)})
    texts = [str(i) for i in range(6)]
    await embed_texts(llm, MODEL, texts, batch_size=2, expected_dim=DIM_3, concurrency=1)
    assert llm.max_inflight == 1
    assert llm.batches == [["0", "1"], ["2", "3"], ["4", "5"]]


async def test_embed_texts_concurrency_below_one_raises_value_error() -> None:
    """`concurrency=0` → `ValueError` (kontrakt C3)."""
    from app.services.embed import embed_texts  # noqa: PLC0415

    llm = _StubGateway()
    with pytest.raises(ValueError):
        await embed_texts(llm, MODEL, ["0"], batch_size=1, expected_dim=DIM_3, concurrency=0)


# --- resolve_concurrency (kontrakt C2) ---


def _model(extra: dict[str, object]) -> ModelRef:
    return ModelRef("i" * 32, "fake-ocr", "image2text", extra=extra)


def test_resolve_concurrency_uses_extra_when_key_present() -> None:
    """`extra["max_concurrency"]` gdy klucz jest — wartość z rejestru modelu."""
    from app.services.concurrency import resolve_concurrency  # noqa: PLC0415

    assert resolve_concurrency(_model({"max_concurrency": 8}), 3) == 8  # noqa: PLR2004


def test_resolve_concurrency_falls_back_to_default_when_key_missing() -> None:
    """Brak klucza → wartość domyślna (WD_VLM_CONCURRENCY / WD_EMBED_CONCURRENCY)."""
    from app.services.concurrency import resolve_concurrency  # noqa: PLC0415

    assert resolve_concurrency(_model({}), 4) == 4  # noqa: PLR2004
    assert resolve_concurrency(None, 3) == 3  # noqa: PLR2004


def test_settings_concurrency_defaults() -> None:
    """Domyślne `WD_VLM_CONCURRENCY=3` / `WD_EMBED_CONCURRENCY=4` (kontrakt C1).

    E2E test równoległości fake-llm sprawdza tylko `>=` (wspólny licznik), więc domyślne
    wartości przypinamy tutaj — razem z pułapem z ``test_embed_texts_caps_inflight_at_concurrency``
    domykają zakres bez zależności od współdzielonego stanu usługi.
    """
    from app.core.config import Settings  # noqa: PLC0415

    settings = Settings(env="test")
    assert settings.vlm_concurrency == 3  # noqa: PLR2004
    assert settings.embed_concurrency == 4  # noqa: PLR2004


@pytest.mark.parametrize("bad", [0, 33, True, False, 1.0, "8", None])
def test_resolve_concurrency_rejects_invalid_value(bad: object) -> None:
    """Wartość spoza `int` 1..32 (bool, float, str, None) → `PermanentError` (kontrakt C2)."""
    from app.services.concurrency import resolve_concurrency  # noqa: PLC0415
    from app.worker.errors import PermanentError  # noqa: PLC0415

    with pytest.raises(
        PermanentError,
        match=r"extra\.max_concurrency must be an integer between 1 and 32 \(model fake-ocr\)",
    ):
        resolve_concurrency(_model({"max_concurrency": bad}), 3)
