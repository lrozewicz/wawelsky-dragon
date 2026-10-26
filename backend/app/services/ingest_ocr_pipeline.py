"""Potokowe rozpoznawanie stron PDF (kontrakt C1/C3 WP E5-H8a).

Strony ``pending`` z ukończonej partii fazy A trafiają do kolejki ``asyncio.Queue`` od razu,
więc rozpoznawanie (``vision_concurrency`` workerów) biegnie równolegle z fazami A/C pozostałych
partii. Postęp OCR raportujemy jako ``OCR pages {done}/{N} ({model})`` (procent
``0.30 + 0.10*done/N``, bez cofania) i domykamy wpisami ``OCR pages {N}/{N}`` oraz
``OCR finished: {N} pages ({model})`` @ 0.40 (kontrakt C1).

Wydzielone z ``ingest_convert`` (limit 400 linii, DEC-099); wołane wyłącznie przez
``convert_document``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from concurrent.futures.process import BrokenProcessPool
from dataclasses import replace

from app.llm.hooks import current_hooks
from app.parsing.converters.pdf import RoutedBatch
from app.parsing.diacritics_stage import DiacriticsCorrector
from app.parsing.errors import parse_timeout
from app.parsing.recognizers import (
    PageRecognizer,
    RecognitionResult,
    apply_recognition,
    recognize_stream,
)
from app.parsing.types import ConvertedDocument, PendingPage
from app.worker.errors import POOL_BROKEN_MESSAGE, TransientError

ReportFn = Callable[[float, str], Awaitable[None]]

PROGRESS_OCR_START = 0.30  # C1: koniec konwersji
PROGRESS_OCR_END = 0.40  # C1: koniec OCR/wizji
PROGRESS_CONVERT = PROGRESS_OCR_START  # C1: wpis końca konwersji
OCR_STEP_LIMIT = 50  # C1: do 50 stron raport co stronę
OCR_STEP = 10  # C1: powyżej — co ≤ 10 stron
# Partie fazy A liczone naraz, gdy działa potok OCR: obrazy stron (~4 MB) czekają na OCR w pamięci,
# więc renderowanie nie może uciekać rozpoznawaniu (przy 745 stronach worker dostawał OOM).
PHASE_A_LOOKAHEAD = 3


async def report_converted(report: ReportFn | None, doc: ConvertedDocument, fmt: str) -> None:
    """Wpis końca konwersji @ 0.30 (kontrakt C1); formaty nie-PDF bez stron pending pomijamy."""
    if report is None:
        return
    if fmt == "pdf":
        pending = len(doc.pending_pages)
        tail = f"({pending} to recognize)" if pending else "(text layer)"
        await report(PROGRESS_CONVERT, f"Converted {doc.pages or 0} pages {tail}")
    elif not doc.pending_pages:
        await report(PROGRESS_CONVERT, f"Converted {doc.pages or 1} pages (text layer)")


def _default_name(vision: PageRecognizer | None, ocr: PageRecognizer | None) -> str:
    """Nazwa modelu do postępu OCR, gdy żadna strona nie została jeszcze rozpoznana."""
    if vision is not None:
        return vision.name
    return ocr.name if ocr is not None else ""


class OcrProgress:
    """Reporter etapu OCR (kontrakt C1): ``OCR pages {done}/{N} ({model})`` i wpis końcowy.

    ``on_progress`` z ``recognize_stream`` dostaje ``total`` rosnące w trakcie (strony napływają
    partiami — brief T5), ale mianownik ``N`` w komunikacie bierzemy z PEŁNEJ liczby stron do
    rozpoznania: raportujemy dopiero, gdy ``total`` osiąga ``N`` znane z ``input_done`` (koniec
    konwersji), więc mianownik nie skacze. Procent (``done/N``) nie cofa się (``max``), a wpisy
    ``N/N`` i ``OCR finished`` emituje ``finish`` raz, po zakończeniu rozpoznawania.
    """

    def __init__(self, report: ReportFn | None, *, initial_name: str = "") -> None:
        self._report = report
        self.name = initial_name
        self._percent = PROGRESS_OCR_START
        self._final_total: int | None = None

    def input_done(self, total: int) -> None:
        """Po konwersji znamy pełne ``N`` stron do rozpoznania — dopiero teraz raportujemy."""
        self._final_total = total

    async def on_page(self, done: int, total: int, name: str) -> None:
        """Callback ``on_progress`` z ``recognize_stream``: raport co stronę lub co ≤ 10 stron."""
        if name:
            self.name = name
        # Dopóki nie znamy pełnego ``N`` (``total`` rośnie), nie raportujemy — mianownik byłby
        # mylący; ``done == total`` (dogonienie) to jeszcze nie finał — ten emituje ``finish``.
        if (
            self._report is None
            or self._final_total is None
            or total < self._final_total
            or done >= total
        ):
            return
        step = 1 if total <= OCR_STEP_LIMIT else OCR_STEP
        if done % step:
            return
        percent = PROGRESS_OCR_START + (PROGRESS_OCR_END - PROGRESS_OCR_START) * done / total
        self._percent = max(self._percent, percent)
        await self._report(self._percent, f"OCR pages {done}/{total} ({self.name})")

    async def finish(self, total: int) -> None:
        """Wpisy końcowe po rozpoznaniu: ``OCR pages N/N``, ``OCR finished`` i bilans cache (C3)."""
        if self._report is not None and total != 0:
            await self._report(PROGRESS_OCR_END, f"OCR pages {total}/{total} ({self.name})")
            await self._report(PROGRESS_OCR_END, f"OCR finished: {total} pages ({self.name})")
        hooks = current_hooks()
        if hooks is not None and hooks.vision_cache_hits + hooks.vision_model_calls > 0:
            await hooks.log(
                f"OCR pages: {hooks.vision_cache_hits} from cache, "
                f"{hooks.vision_model_calls} to model"
            )


class PdfOcrPipeline:
    """Potok OCR konwersji PDF: kolejka stron pending + zadanie rozpoznawania (kontrakt C3).

    ``convert_document`` tworzy potok przed konwersją, przekazuje ``on_batch`` do ``_convert_pdf``
    (wołane po każdej partii fazy A) i domyka go ``finish`` po zakończeniu konwersji.
    """

    def __init__(  # noqa: PLR0913 — parametry przekazywane wprost z ``convert_document``
        self,
        *,
        ocr: PageRecognizer | None,
        vision: PageRecognizer | None,
        vision_concurrency: int,
        diacritics: DiacriticsCorrector | None,
        check_cancel: Callable[[], Awaitable[None]] | None,
        report: ReportFn | None,
    ) -> None:
        self._vision = vision
        self._ocr = ocr
        self._vision_concurrency = vision_concurrency
        self._diacritics = diacritics
        self._check_cancel = check_cancel
        # Mała kolejka = backpressure na fazę A (patrz PHASE_A_LOOKAHEAD).
        self._queue: asyncio.Queue[PendingPage | None] = asyncio.Queue(
            maxsize=max(2 * vision_concurrency, 8)
        )
        self._progress = OcrProgress(report, initial_name=_default_name(vision, ocr))
        self._task: asyncio.Task[RecognitionResult] = asyncio.create_task(
            self._recognize(), name="ocr-pipeline"
        )

    async def _recognize(self) -> RecognitionResult:
        return await recognize_stream(
            self._pages(),
            ocr=self._ocr,
            vision=self._vision,
            vision_concurrency=self._vision_concurrency,
            diacritics=self._diacritics,
            check_cancel=self._check_cancel,
            on_progress=self._progress.on_page,
        )

    async def _pages(self) -> AsyncIterator[PendingPage]:
        while True:
            page = await self._queue.get()
            if page is None:
                return
            yield page

    async def _put(self, item: PendingPage | None) -> None:
        """``queue.put`` z backpressure; gdy OCR padł, propaguje jego błąd zamiast wisieć."""
        put = asyncio.ensure_future(self._queue.put(item))
        try:
            await asyncio.wait({put, self._task}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            if not put.done():
                put.cancel()
        if not put.done() or put.cancelled():
            await asyncio.gather(put, return_exceptions=True)
            self._task.result()  # rzuca błąd rozpoznawania; wynik oznaczałby przedwczesny koniec
            raise RuntimeError("OCR stopped before all pages were queued")

    async def on_batch(self, batch: RoutedBatch) -> None:
        """Po partii fazy A: strony pending idą do rozpoznawania (czeka, gdy OCR nie nadąża)."""
        for page in batch.pending:
            await self._put(page)

    async def finish(self, doc: ConvertedDocument) -> ConvertedDocument:
        """Zamyka strumień, czeka na rozpoznanie, raportuje finał i wstawia fragmenty."""
        total = len(doc.pending_pages)
        self._progress.input_done(total)
        await self._put(None)
        result = await self._task
        await self._progress.finish(total)
        return apply_recognition(doc, result.outcomes, self._vision)

    async def abort(self) -> None:
        """Anuluje rozpoznawanie (Stop/timeout/pad puli) i czeka na jego zamknięcie."""
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)


async def convert_pdf_pipelined(  # noqa: PLR0913 — parametry przekazywane wprost z ``convert_document``
    convert_batches: Callable[
        [Callable[[RoutedBatch], Awaitable[None]]], Awaitable[ConvertedDocument]
    ],
    *,
    timeout_s: float | None,
    ocr: PageRecognizer | None,
    vision: PageRecognizer | None,
    vision_concurrency: int,
    diacritics: DiacriticsCorrector | None,
    check_cancel: Callable[[], Awaitable[None]] | None,
    report: ReportFn | None,
) -> ConvertedDocument:
    """Konwersja PDF z potokiem OCR (brief T5 poz. 1): rozpoznawanie biegnie z fazami A/C.

    ``convert_batches(on_pending)`` to konwersja partiami (``_convert_pdf``); po jej zakończeniu
    czekamy na dokończenie rozpoznawania i wstawiamy fragmenty. Wpis 0.30 (``Converted N pages``)
    emitujemy między konwersją a wpisami OCR (kontrakt C1).
    """
    pipeline = PdfOcrPipeline(
        ocr=ocr,
        vision=vision,
        vision_concurrency=vision_concurrency,
        diacritics=diacritics,
        check_cancel=check_cancel,
        report=report,
    )
    try:
        doc = await asyncio.wait_for(convert_batches(pipeline.on_batch), timeout=timeout_s)
    except TimeoutError:
        await pipeline.abort()
        seconds = int(timeout_s) if timeout_s is not None else 0
        raise parse_timeout(seconds) from None
    except BrokenProcessPool:
        await pipeline.abort()
        raise TransientError(POOL_BROKEN_MESSAGE) from None
    except BaseException:
        await pipeline.abort()
        raise
    await report_converted(report, doc, "pdf")
    return await pipeline.finish(doc)


def _without_images(batch: RoutedBatch) -> RoutedBatch:
    """Partia bez PNG stron pending: obrazy są w kolejce OCR, dalej potrzebne są metadane."""
    return RoutedBatch(batch.routed, tuple(replace(page, image_png=b"") for page in batch.pending))


async def route_with_lookahead(
    batches: tuple[tuple[int, ...], ...],
    submit: Callable[[tuple[int, ...]], asyncio.Future[RoutedBatch]],
    *,
    on_pending: Callable[[RoutedBatch], Awaitable[None]],
    on_routed: Callable[[RoutedBatch], None],
    after_batch: Callable[[], Awaitable[None]],
) -> list[RoutedBatch]:
    """Faza A potokowo: naraz najwyżej ``PHASE_A_LOOKAHEAD`` partii, kolejna po oddaniu poprzedniej.

    Wynik partii trafia do ``on_pending`` (czeka na wolne miejsce w kolejce OCR), a w zwracanej
    liście zostaje bez obrazów, więc pamięć nie rośnie z liczbą stron dokumentu.
    """
    remaining = iter(batches)
    running: set[asyncio.Future[RoutedBatch]] = set()
    routed: list[RoutedBatch] = []

    def submit_next() -> None:
        pages = next(remaining, None)
        if pages is not None:
            running.add(submit(pages))

    for _ in range(PHASE_A_LOOKAHEAD):
        submit_next()
    try:
        while running:
            done, _ = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
            running.difference_update(done)
            for future in done:
                batch: RoutedBatch = future.result()
                on_routed(batch)
                await on_pending(batch)
                routed.append(_without_images(batch))
                submit_next()
                await after_batch()
    except BaseException:
        for future in running:
            future.cancel()
        raise
    return routed
