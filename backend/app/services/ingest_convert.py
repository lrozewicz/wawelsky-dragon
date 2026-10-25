"""Konwersja dokumentów (kontrakt C6) — opcje z parser_config, pula procesów, OCR/VLM.

Konwersja PDF idzie partiami jako osobne zadania puli (E5-H8a): faza A partii
(routing stron + render PNG stron pending) równolegle w puli, faza B w procesie
głównym (linie powtarzane zależą od całego dokumentu), faza C partii (sekcje HTML
stron ``text``) równolegle w puli. Po każdej partii `report("Converting pages d/N")`
i `check_cancel()`. Strony pending partii idą do potokowego rozpoznawania od razu
(`ingest_ocr_pipeline.py`). Zadania partii idą przez `_pdfium` — zamek `threading.Lock`
wokół pracy PDFium (pypdfium2 „PDFium is inherently not thread-safe”): przy puli wątkowej
(`executor=None`) partie serializują się, a w puli procesów każdy proces ma własny zamek,
więc render nadal idzie na wielu rdzeniach. Formaty nie-PDF: jedno wywołanie konwertera.
"""

from __future__ import annotations

import asyncio
import functools
import threading
from collections.abc import Awaitable, Callable, Mapping
from concurrent.futures import Executor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.domain.chunking.types import ChunkConfig
from app.llm.tokens import count_tokens
from app.parsing.converters.pdf import (
    PdfPlan,
    RenderedBatch,
    RoutedBatch,
    _RoutedPage,
    pdf_assemble,
    pdf_plan,
    pdf_render_batch,
    pdf_repeated,
    pdf_route_batch,
)
from app.parsing.diacritics_stage import DiacriticsCorrector
from app.parsing.errors import parse_timeout
from app.parsing.html import section_html
from app.parsing.recognizers import PageRecognizer, complete_pages, self_check
from app.parsing.registry import convert, detect_format
from app.parsing.types import ConvertedDocument, ConvertOptions, PdfStrategy
from app.services.ingest_ocr_pipeline import convert_pdf_pipelined, report_converted
from app.worker.errors import POOL_BROKEN_MESSAGE, TransientError

VLM_CONCURRENCY = 3
PROGRESS_START = 0.01  # początek przedziału konwersji (kontrakt C1)
PROGRESS_CONVERT = 0.30  # koniec przedziału konwersji (kontrakt C1)
CONVERT = PROGRESS_CONVERT - PROGRESS_START


@functools.cache
def tesseract_available() -> bool:
    """Czy tesseract jest dostępny na hoście (self-check raz na proces)."""
    return bool(self_check()["tesseract"])


def convert_options(
    parser_config: Mapping[str, Any],
    settings: Settings,
    *,
    layout_vision: bool,
    vision_available: bool,
    ocr_available: bool,
) -> ConvertOptions:
    """Buduje ConvertOptions z parser_config dokumentu (05 §6.1: strategia PDF)."""
    strategy: PdfStrategy
    if layout_vision:
        strategy = "vision"
    elif parser_config.get("layout_recognize") == "Plain Text":
        strategy = "fast"
    else:
        strategy = "auto"
    pages = tuple((int(a), int(b)) for a, b in (parser_config.get("pages") or [[1, 1_000_000]]))
    return ConvertOptions(
        pdf_strategy=strategy,
        pages=pages,
        vision_available=vision_available,
        ocr_available=ocr_available,
        ocr_langs=settings.ocr_langs,
        max_uncompressed_bytes=settings.max_uncompressed_mb * 1024 * 1024,
        max_archive_ratio=settings.max_archive_ratio,
    )


def _value(parser_config: Mapping[str, Any], key: str, default: Any) -> Any:
    """parser_config.get traktujący wartość None jak brak klucza."""
    value = parser_config.get(key)
    return default if value is None else value


def chunk_config(parser_config: Mapping[str, Any]) -> ChunkConfig:
    """Buduje ChunkConfig z parser_config dokumentu; wartości None jak brak klucza."""
    return ChunkConfig(
        count_tokens=count_tokens,
        chunk_token_num=int(_value(parser_config, "chunk_token_num", 512)),
        delimiter=str(_value(parser_config, "delimiter", "\n")),
        overlapped_percent=int(_value(parser_config, "overlapped_percent", 0)),
        html4excel=bool(_value(parser_config, "html4excel", False)),
        table_column_mode=_value(parser_config, "table_column_mode", "auto"),
        table_column_roles=dict(_value(parser_config, "table_column_roles", {}) or {}),
    )


async def convert_document(  # noqa: PLR0913 — sygnatura z kontraktu C2/C6
    path: Path,
    suffix: str,
    opts: ConvertOptions,
    *,
    executor: Executor | None,
    ocr: PageRecognizer | None,
    vision: PageRecognizer | None,
    timeout_s: float | None = None,
    diacritics: DiacriticsCorrector | None = None,
    vision_concurrency: int = VLM_CONCURRENCY,
    check_cancel: Callable[[], Awaitable[None]] | None = None,
    report: Callable[[float, str], Awaitable[None]] | None = None,
) -> ConvertedDocument:
    """Wykrywa format, konwertuje w puli (None → pula wątków pętli) i dopełnia strony OCR/VLM.

    PDF: partiami z postępem i Stop po każdej partii (kontrakt C1/C3). `timeout_s`
    ogranicza CAŁĄ konwersję (None = bez limitu); przekroczenie podnosi `ParseTimeout`
    (trwały → worker `fail_permanent` → dokument FAIL). `wait_for` nie zabija
    wątku/procesu konwersji (DEC-212). `check_cancel` (TaskContext.check_cancel) rzuca
    `TaskCancelled`; partie niewystartowane są wtedy anulowane.
    """
    fmt = detect_format(path, suffix)
    if fmt == "pdf" and (ocr is not None or vision is not None):
        return await convert_pdf_pipelined(
            functools.partial(_convert_pdf, path, opts, executor, check_cancel, report),
            timeout_s=timeout_s,
            ocr=ocr,
            vision=vision,
            vision_concurrency=vision_concurrency,
            diacritics=diacritics,
            check_cancel=check_cancel,
            report=report,
        )
    try:
        if fmt == "pdf":
            doc = await asyncio.wait_for(
                _convert_pdf(path, opts, executor, check_cancel, report),
                timeout=timeout_s,
            )
        else:
            loop = asyncio.get_running_loop()
            doc = await asyncio.wait_for(
                loop.run_in_executor(executor, convert, path, fmt, opts), timeout=timeout_s
            )
    except TimeoutError:
        seconds = int(timeout_s) if timeout_s is not None else 0
        raise parse_timeout(seconds) from None
    except BrokenProcessPool:
        # Proces potomny padł (OOM) — błąd przejściowy; kolejka zdecyduje o ponowieniu/dead.
        raise TransientError(POOL_BROKEN_MESSAGE) from None
    await report_converted(report, doc, fmt)
    if doc.pending_pages:
        doc = await complete_pages(
            doc,
            ocr=ocr,
            vision=vision,
            vision_concurrency=vision_concurrency,
            diacritics=diacritics,
        )
    return doc


class _ConversionProgress:
    """Licznik postępu konwersji PDF partiami (kontrakt C1).

    Jednostka = strona w fazie A oraz strona ``text`` w fazie C. Liczby stron ``text``
    nie znamy przed fazą A, więc mianownik rośnie razem z odkrywaniem partii; postęp
    pozostaje monotoniczny, a ostatni wpis to ``total/total``.
    """

    def __init__(self, total: int) -> None:
        self.total = total
        self.units_done = 0
        self.units_total = total

    def add_routed(self, batch: RoutedBatch) -> None:
        """Po partii fazy A: +liczba stron partii, +strony ``text`` do mianownika."""
        self.units_done += len(batch.routed)
        self.units_total += sum(1 for page in batch.routed if page.mode == "text")

    def add_rendered(self, pages: int) -> None:
        """Po partii fazy C: +liczba stron ``text`` partii."""
        self.units_done += pages

    @property
    def done(self) -> int:
        return self.total * self.units_done // self.units_total if self.units_total else 0

    @property
    def percent(self) -> float:
        return PROGRESS_START + CONVERT * self.done / self.total if self.total else PROGRESS_START


def _submit[T](
    loop: asyncio.AbstractEventLoop, executor: Executor | None, fn: Callable[..., T], *args: Any
) -> asyncio.Future[T]:
    """Zleca zadanie puli, zachowując ``cancel()`` dla partii jeszcze niewystartowanych."""
    if executor is None:
        return loop.run_in_executor(None, fn, *args)
    return asyncio.wrap_future(executor.submit(fn, *args), loop=loop)


_PDFIUM_LOCK = threading.Lock()
"""Serializuje pracę PDFium w obrębie procesu (pypdfium2 nie jest wątkobezpieczne)."""


def plan_pdf(path: Path, opts: ConvertOptions) -> PdfPlan:
    """`pdf_plan` pod zamkiem PDFium (modułowa — picklowalna do puli procesów)."""
    with _PDFIUM_LOCK:
        return pdf_plan(path, opts)


def route_pdf_batch(path: Path, pages: tuple[int, ...], opts: ConvertOptions) -> RoutedBatch:
    """Faza A partii pod zamkiem PDFium (modułowa — picklowalna do puli procesów)."""
    with _PDFIUM_LOCK:
        return pdf_route_batch(path, pages, opts)


def render_pdf_batch(
    path: Path, routed: tuple[_RoutedPage, ...], drop: frozenset[str], opts: ConvertOptions
) -> RenderedBatch:
    """Faza C partii pod zamkiem PDFium (modułowa — picklowalna do puli procesów)."""
    with _PDFIUM_LOCK:
        return pdf_render_batch(path, routed, drop, opts)


def _outcome[T](future: asyncio.Future[T]) -> T:
    """Wynik zadania puli; wyjątek (np. ``BrokenProcessPool``) propaguje dalej."""
    if future.cancelled():
        raise asyncio.CancelledError
    error = future.exception()
    if error is not None:
        raise error
    return future.result()


async def _report_batch(
    report: Callable[[float, str], Awaitable[None]] | None, progress: _ConversionProgress
) -> None:
    """Wpis ``Converting pages d/N`` po ukończonej partii (kontrakt C1)."""
    if report is not None:
        await report(progress.percent, f"Converting pages {progress.done}/{progress.total}")


async def _drain[T](
    futures: list[asyncio.Future[T]],
    *,
    progress: _ConversionProgress,
    report: Callable[[float, str], Awaitable[None]] | None,
    check_cancel: Callable[[], Awaitable[None]] | None,
    on_done: Callable[[int, T], None] | None = None,
) -> list[T | None]:
    """Czeka na partie (FIRST_COMPLETED); po każdej raport postępu i Stop (kontrakt C1/C2)."""
    outcomes: list[T | None] = [None] * len(futures)
    index_of = {future: index for index, future in enumerate(futures)}
    pending: set[asyncio.Future[T]] = set(futures)
    while pending:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        for future in done:
            index = index_of[future]
            value = _outcome(future)
            outcomes[index] = value
            if on_done is not None:
                on_done(index, value)
            await _report_batch(report, progress)
            if check_cancel is not None:
                await check_cancel()
    return outcomes


def _text_pages(batch: RoutedBatch) -> int:
    """Liczba stron ``text`` partii (jednostki fazy C, kontrakt C1)."""
    return sum(1 for page in batch.routed if page.mode == "text")


async def _convert_pdf(  # noqa: PLR0913, PLR0917 — sygnatura T4 + on_pending (potok OCR)
    path: Path,
    opts: ConvertOptions,
    executor: Executor | None,
    check_cancel: Callable[[], Awaitable[None]] | None,
    report: Callable[[float, str], Awaitable[None]] | None,
    on_pending: Callable[[RoutedBatch], None] | None = None,
) -> ConvertedDocument:
    """Konwersja PDF partiami: faza A → B → C, wynik identyczny jak sekwencyjnie (C3)."""
    loop = asyncio.get_running_loop()
    plan = await loop.run_in_executor(executor, plan_pdf, path, opts)
    progress = _ConversionProgress(sum(len(batch) for batch in plan.batches))
    running: list[asyncio.Future[Any]] = []
    try:
        routed = await _phase_a(
            loop, executor, path, opts, plan, progress, running, report, check_cancel, on_pending
        )
        drop = pdf_repeated([page for batch in routed for page in batch.routed])
        rendered = await _phase_c(
            loop, executor, path, opts, routed, drop, progress, running, report, check_cancel
        )
    except BaseException:
        # Anulowanie (Stop/timeout/`BrokenProcessPool`): partie niewystartowane się nie
        # uruchomią, wykonywanych nie zabijamy (kontrakt C3, DEC-212).
        for future in running:
            future.cancel()
        raise
    pending = [page for batch in routed for page in batch.pending]
    return pdf_assemble(plan, pending, rendered)


async def _phase_a(  # noqa: PLR0913, PLR0917 — kształt fazy z kontraktu C3
    loop: asyncio.AbstractEventLoop,
    executor: Executor | None,
    path: Path,
    opts: ConvertOptions,
    plan: PdfPlan,
    progress: _ConversionProgress,
    running: list[asyncio.Future[Any]],
    report: Callable[[float, str], Awaitable[None]] | None,
    check_cancel: Callable[[], Awaitable[None]] | None,
    on_pending: Callable[[RoutedBatch], None] | None = None,
) -> list[RoutedBatch]:
    """Faza A: routing + render stron pending każdej partii jako osobne zadania puli."""
    futures = [
        _submit(loop, executor, route_pdf_batch, path, pages, opts) for pages in plan.batches
    ]
    running.extend(futures)

    def on_done(_index: int, batch: RoutedBatch) -> None:
        progress.add_routed(batch)
        if on_pending is not None:  # strony pending partii idą do rozpoznawania od razu (C3)
            on_pending(batch)

    outcomes = await _drain(
        futures,
        progress=progress,
        report=report,
        check_cancel=check_cancel,
        on_done=on_done,
    )
    return [batch for batch in outcomes if batch is not None]


async def _phase_c(  # noqa: PLR0913, PLR0917 — kształt fazy z kontraktu C3
    loop: asyncio.AbstractEventLoop,
    executor: Executor | None,
    path: Path,
    opts: ConvertOptions,
    routed: list[RoutedBatch],
    drop: frozenset[str],
    progress: _ConversionProgress,
    running: list[asyncio.Future[Any]],
    report: Callable[[float, str], Awaitable[None]] | None,
    check_cancel: Callable[[], Awaitable[None]] | None,
) -> list[RenderedBatch]:
    """Faza C: sekcje HTML partii ze stronami ``text``; partie bez nich buduje lokalnie."""
    text_batches = [batch for batch in routed if _text_pages(batch)]
    futures = [
        _submit(loop, executor, render_pdf_batch, path, batch.routed, drop, opts)
        for batch in text_batches
    ]
    running.extend(futures)
    outcomes = await _drain(
        futures,
        progress=progress,
        report=report,
        check_cancel=check_cancel,
        on_done=lambda index, _batch: progress.add_rendered(_text_pages(text_batches[index])),
    )
    # `pdf_assemble` sortuje partie po numerze pierwszej strony, więc kolejność listy nie gra roli.
    rendered = [batch for batch in outcomes if batch is not None]
    rendered.extend(_empty_batch(batch) for batch in routed if not _text_pages(batch))
    return rendered


def _empty_batch(batch: RoutedBatch) -> RenderedBatch:
    """Wynik fazy C partii bez stron ``text``: puste sekcje + statystyki (kontrakt C3)."""
    stats = {"pages_text": 0, "pages_ocr": 0, "pages_vision": 0}
    for page in batch.routed:
        stats["pages_ocr" if page.mode == "ocr" else "pages_vision"] += 1
    sections = tuple((page.number, section_html("page", page.number, "")) for page in batch.routed)
    return RenderedBatch(sections, (), stats)
