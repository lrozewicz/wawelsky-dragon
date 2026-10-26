"""Backpressure potoku OCR: obrazy stron nie kumulują się w pamięci workera (OOM przy 745 stronach).

Render stron jest szybszy od OCR, a PNG strony waży kilka MB, więc: kolejki są ograniczone,
faza A idzie z oknem, a po rozpoznaniu i w wynikach fazy A zostają strony bez PNG.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from app.parsing import cancel_watch
from app.parsing.converters.pdf import RoutedBatch
from app.parsing.recognizers import recognize_stream
from app.parsing.types import PendingPage
from app.services import ingest_ocr_pipeline as pipeline_mod
from app.services.ingest_ocr_pipeline import PdfOcrPipeline, route_with_lookahead

PNG = b"x" * 1024
PAGES_PER_BATCH = 2


def _page(number: int) -> PendingPage:
    return PendingPage(number, "vision", PNG, "image_cover")


class GateRecognizer:
    """Rozpoznawacz czekający na ``release``: symuluje wolny OCR."""

    name = "gate"

    def __init__(self) -> None:
        self.release = asyncio.Event()

    async def recognize(
        self, image_png: bytes, *, page: int, hint: str | None = None, use_cache: bool = True
    ) -> str:
        await self.release.wait()
        return f"<p>strona {page}</p>"


async def _settle() -> None:
    for _ in range(20):
        await asyncio.sleep(0)


async def test_recognize_stream_does_not_pull_input_faster_than_ocr() -> None:
    """Przy zablokowanym OCR wejście pobrane jest tylko do rozmiaru kolejki + workerów."""
    total, concurrency = 200, 2
    pulled = 0

    async def pages() -> AsyncIterator[PendingPage]:
        nonlocal pulled
        for number in range(1, total + 1):
            pulled += 1
            yield _page(number)

    gate = GateRecognizer()
    task = asyncio.create_task(
        recognize_stream(pages(), ocr=None, vision=gate, vision_concurrency=concurrency)
    )
    await _settle()

    # workery w toku + kolejka (2 * concurrency) + jedna strona czekająca w producencie
    assert pulled <= concurrency + 2 * concurrency + 1
    gate.release.set()
    result = await asyncio.wait_for(task, timeout=5)

    assert pulled == total
    assert len(result.outcomes) == total
    assert all(outcome[0].image_png == b"" for outcome in result.outcomes)  # PNG zwolniony


def _batch(first: int, size: int = PAGES_PER_BATCH) -> RoutedBatch:
    return RoutedBatch((), tuple(_page(n) for n in range(first, first + size)))


async def test_route_with_lookahead_limits_batches_in_flight() -> None:
    """Zlecone jest najwyżej okno partii; reszta dopiero po oddaniu poprzednich do OCR."""
    batches = tuple((n,) for n in range(10))
    submitted: list[int] = []
    handled: list[int] = []
    gate = asyncio.Event()
    routed: list[RoutedBatch] = []

    def submit(pages: tuple[int, ...]) -> asyncio.Future[RoutedBatch]:
        submitted.append(pages[0])
        future: asyncio.Future[RoutedBatch] = asyncio.get_running_loop().create_future()
        future.set_result(_batch(pages[0] * 10))
        return future

    async def on_pending(batch: RoutedBatch) -> None:
        await gate.wait()  # OCR nie nadąża
        handled.append(batch.pending[0].page)

    async def after_batch() -> None:
        return None

    task = asyncio.create_task(
        route_with_lookahead(
            batches, submit, on_pending=on_pending, on_routed=routed.append, after_batch=after_batch
        )
    )
    await _settle()

    assert len(submitted) == pipeline_mod.PHASE_A_LOOKAHEAD  # nie wszystkie 10 naraz
    gate.set()
    result = await asyncio.wait_for(task, timeout=5)

    assert submitted == list(range(10))
    assert len(handled) == len(batches)
    assert len(result) == len(batches)
    assert all(page.image_png == b"" for batch in result for page in batch.pending)
    assert all(len(batch.pending) == PAGES_PER_BATCH for batch in result)  # metadane stron zostają


async def test_on_batch_raises_instead_of_hanging_when_ocr_dies() -> None:
    """Gdy rozpoznawanie padnie, `on_batch` (czekające na miejsce w kolejce) rzuca jego błąd."""

    class Boom(RuntimeError):
        pass

    async def check_cancel() -> None:
        raise Boom

    pipe = PdfOcrPipeline(
        ocr=None,
        vision=GateRecognizer(),
        vision_concurrency=1,
        diacritics=None,
        check_cancel=check_cancel,
        report=None,
    )
    with pytest.raises(Boom):
        await asyncio.wait_for(pipe.on_batch(_batch(1, size=50)), timeout=5)
    await pipe.abort()


class Cancelled(Exception):
    """Odpowiednik TaskCancelled w teście."""


async def test_stop_interrupts_pages_in_flight(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop przerywa strony w toku w ciągu interwału odpytywania, nie po ich zakończeniu."""
    monkeypatch.setattr(cancel_watch, "CANCEL_POLL_S", 0.01)
    stop = asyncio.Event()
    gate = GateRecognizer()  # OCR nigdy nie kończy się sam

    async def check_cancel() -> None:
        if stop.is_set():
            raise Cancelled

    async def pages() -> AsyncIterator[PendingPage]:
        for number in range(1, 40):
            yield _page(number)

    task = asyncio.create_task(
        recognize_stream(
            pages(), ocr=None, vision=gate, vision_concurrency=4, check_cancel=check_cancel
        )
    )
    await _settle()
    assert not task.done()  # strony wiszą w OCR

    stop.set()
    with pytest.raises(Cancelled):
        await asyncio.wait_for(task, timeout=2)


async def test_watch_stops_polling_when_work_finishes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Po zakończeniu pracy obserwator znika (brak wiszącego zadania w tle)."""
    monkeypatch.setattr(cancel_watch, "CANCEL_POLL_S", 0.01)
    polls = 0

    async def check_cancel() -> None:
        nonlocal polls
        polls += 1

    async def work() -> str:
        await asyncio.sleep(0.05)
        return "ok"

    assert await cancel_watch.run_with_cancel_watch(work(), check_cancel) == "ok"
    seen = polls
    await asyncio.sleep(0.05)
    assert polls == seen  # po zakończeniu nikt już nie pyta
    assert not [t for t in asyncio.all_tasks() if t.get_name() == "cancel-watch"]
