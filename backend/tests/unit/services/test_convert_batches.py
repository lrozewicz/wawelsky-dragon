"""Testy zachowań konwersji E5-H8a (brief T2/T5): Stop, postęp, partie, potokowość.

Zielone po T5: Stop między partiami, komunikaty postępu i etapu (`Converting pages`,
`Converted N pages (text layer)`), potokowość OCR (`pipelines_ocr` — pierwsze `recognize`
przed `Converting pages N/N`), komunikaty postępu OCR z nazwą modelu
(`ocr_progress_and_names_model`) oraz Stop w trakcie OCR (`stops_before_each_ocr_page`).
Straż regresji `test_batched_result_equals_sequential`.
"""

from __future__ import annotations

import itertools
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.llm.hooks import TaskLlmHooks, install_hooks, reset_hooks
from app.parsing.converters.pdf import PAGE_BATCH
from app.parsing.registry import convert
from app.parsing.types import ConvertOptions
from app.services.ingest_convert import convert_document
from app.services.ingest_ocr_pipeline import OcrProgress
from app.worker.errors import TaskCancelled
from tests.unit.services.factories import document_pdf, scan_pdf, text_pdf

_CONVERTING = re.compile(r"^Converting pages (\d+)/(\d+)$")
_EPS = 1e-9

TOTAL_PAGES = 80  # 4 partie po 25 stron → 25/25/25/5
MIN_BATCH_ENTRIES = 4  # liczba partii = minimalna liczba wpisów konwersji
VISION_CONCURRENCY = 2  # wartość z briefu T2 poz. 6
STOP_AT_CALL = 2  # check_cancel w teście Stop między partiami rzuca przy 2. wywołaniu
CANCEL_AFTER_RECOGNIZES = 10  # Stop w OCR: check_cancel rzuca po tylu rozpoznanych stronach
PAGE_BATCH_SIZE = 25  # kontrakt C3: rozmiar partii stron PDF
SCAN_PAGES = 30  # liczba stron-skanów w teście postępu OCR
OCR_REPORT_STEP = 10  # kontrakt C1: raport OCR co stronę lub co ≤ 10 stron


def test_page_batch_is_25() -> None:
    """Kontrakt C3: PAGE_BATCH = 25 stron — pin rozmiaru partii (poza listą xfail)."""
    assert PAGE_BATCH == PAGE_BATCH_SIZE


class _CountingExecutor(ThreadPoolExecutor):
    """Pula wątków licząca wywołania ``submit`` (brief T2 poz. 1)."""

    def __init__(self) -> None:
        super().__init__(max_workers=4)
        self.submits = 0

    def submit(self, fn, /, *args, **kwargs):
        self.submits += 1
        return super().submit(fn, *args, **kwargs)


class _RecordingRecognizer:
    """Fałszywy rozpoznawacz stron: zapisuje zdarzenia i zwraca fragment HTML (poz. 4/5/6)."""

    def __init__(self, name: str, events: list[str]) -> None:
        self.name = name
        self._events = events

    async def recognize(
        self, image_png: bytes, *, page: int, hint: str | None = None, use_cache: bool = True
    ) -> str:
        self._events.append(f"recognize page {page}")
        return f"<p>strona {page}</p>"


async def test_convert_document_stops_between_batches(tmp_path: Path) -> None:
    """SC-E5-H8a-01: Stop między partiami przerywa konwersję przed końcem (kontrakt C2/C3)."""
    path = tmp_path / "big.pdf"
    path.write_bytes(text_pdf(TOTAL_PAGES))
    opts = ConvertOptions()

    full = _CountingExecutor()
    try:
        await convert_document(path, "pdf", opts, executor=full, ocr=None, vision=None)
    finally:
        full.shutdown()
    assert full.submits

    calls = 0

    async def check_cancel() -> None:
        nonlocal calls
        calls += 1
        if calls >= STOP_AT_CALL:
            raise TaskCancelled("stop")

    stopped = _CountingExecutor()
    try:
        with pytest.raises(TaskCancelled):
            await convert_document(
                path,
                "pdf",
                opts,
                executor=stopped,
                ocr=None,
                vision=None,
                check_cancel=check_cancel,
            )
    finally:
        stopped.shutdown()

    assert stopped.submits < full.submits


async def test_convert_document_reports_batches(tmp_path: Path) -> None:
    """SC-E5-H8a-04: komunikaty partii i procenty konwersji (kontrakt C1)."""
    path = tmp_path / "big.pdf"
    path.write_bytes(text_pdf(80))
    reports: list[tuple[float, str]] = []

    async def report(progress: float, msg: str) -> None:
        reports.append((progress, msg))

    await convert_document(
        path, "pdf", ConvertOptions(), executor=None, ocr=None, vision=None, report=report
    )

    converting = [(progress, msg) for progress, msg in reports if msg.startswith("Converting")]
    matched = [_CONVERTING.match(msg) for _, msg in converting]
    assert all(match is not None for match in matched)
    done = [int(match.group(1)) for match in matched if match is not None]
    total = {int(match.group(2)) for match in matched if match is not None}
    assert total == {TOTAL_PAGES}
    assert len(converting) >= MIN_BATCH_ENTRIES
    assert done == sorted(done)
    assert len(set(done)) >= MIN_BATCH_ENTRIES
    assert done[-1] == TOTAL_PAGES
    assert converting[-1][1] == "Converting pages 80/80"
    progress = [value for value, _ in converting]
    assert progress == sorted(progress)
    assert all(0.01 - _EPS <= value <= 0.30 + _EPS for value in progress)
    assert converting[-1][0] == pytest.approx(0.30)


async def test_convert_document_text_layer_message(tmp_path: Path) -> None:
    """SC-E5-H8a-05: brak stron do OCR → komunikat etapu warstwy tekstowej (kontrakt C1)."""
    path = tmp_path / "text.pdf"
    path.write_bytes(text_pdf(80))
    reports: list[tuple[float, str]] = []

    async def report(progress: float, msg: str) -> None:
        reports.append((progress, msg))

    await convert_document(
        path, "pdf", ConvertOptions(), executor=None, ocr=None, vision=None, report=report
    )

    assert reports[-1][1] == "Converted 80 pages (text layer)"
    assert reports[-1][0] == pytest.approx(0.30)


async def test_convert_document_pipelines_ocr(tmp_path: Path) -> None:
    """SC-E5-H8a-06: rozpoznawanie stron startuje przed końcem renderu (kontrakt C3)."""
    path = tmp_path / "scan.pdf"
    path.write_bytes(scan_pdf(80))
    events: list[str] = []
    vision = _RecordingRecognizer("fake-ocr", events)

    async def report(progress: float, msg: str) -> None:
        events.append(msg)

    opts = ConvertOptions(vision_available=True, ocr_available=True)
    pool = ThreadPoolExecutor(max_workers=4)
    try:
        await convert_document(
            path, "pdf", opts, executor=pool, ocr=None, vision=vision, report=report
        )
    finally:
        pool.shutdown()

    recognizes = [index for index, event in enumerate(events) if event.startswith("recognize")]
    last_convert = max(
        index for index, event in enumerate(events) if event == "Converting pages 80/80"
    )
    assert recognizes, "brak zdarzeń rozpoznawania stron"
    assert recognizes[0] < last_convert


async def test_convert_document_ocr_progress_and_names_model(tmp_path: Path) -> None:
    """SC-E5-H8a-02/05: postęp OCR i nazwa modelu w komunikatach (kontrakt C1)."""
    path = tmp_path / "scan30.pdf"
    path.write_bytes(scan_pdf(SCAN_PAGES))
    messages: list[str] = []
    vision = _RecordingRecognizer("fake-ocr", [])

    async def report(progress: float, msg: str) -> None:
        messages.append(msg)

    opts = ConvertOptions(vision_available=True, ocr_available=True)
    await convert_document(path, "pdf", opts, executor=None, ocr=None, vision=vision, report=report)

    page_reports = [msg for msg in messages if msg.startswith("OCR pages ")]
    assert page_reports, "brak komunikatów postępu OCR"
    assert all(
        re.fullmatch(rf"OCR pages \d+/{SCAN_PAGES} \(fake-ocr\)", msg) for msg in page_reports
    )
    done = [int(msg.split()[2].split("/")[0]) for msg in page_reports]
    # Kontrakt C1: raport co stronę albo co ≤ 10 stron (skoki ≤ 10) i kierunek `done` niemalejący
    # („Uwagi po T4” p. 3) — postęp OCR nie może się cofać.
    assert done == sorted(done)
    # Skok dwustronny: `done` nie może maleć (MINOR T2/T10) ani przeskakiwać ponad krok.
    assert all(earlier <= later for earlier, later in itertools.pairwise(done))
    assert all(later - earlier <= OCR_REPORT_STEP for earlier, later in itertools.pairwise(done))
    assert done[-1] == SCAN_PAGES
    assert f"OCR pages {SCAN_PAGES}/{SCAN_PAGES} (fake-ocr)" in messages
    assert f"OCR finished: {SCAN_PAGES} pages (fake-ocr)" in messages
    assert not any("vision finished" in msg for msg in messages)


async def test_convert_document_stops_before_each_ocr_page(tmp_path: Path) -> None:
    """SC-E5-H8a-02: Stop W TRAKCIE OCR (nie w fazie A) ogranicza rozpoznania (kontrakt C2).

    `check_cancel` rzuca, gdy licznik rozpoznanych stron osiąga próg — czyli anulowanie
    pochodzi z kolejki OCR (workerów), nie z fazy A. Po tym momencie `recognize` woła się
    najwyżej `vision_concurrency` razy (strony już wysłane), a część stron zostaje nierozpoznana.
    """
    path = tmp_path / "scan80.pdf"
    path.write_bytes(scan_pdf(TOTAL_PAGES))
    events: list[str] = []
    vision = _RecordingRecognizer("fake-ocr", events)

    async def check_cancel() -> None:
        recognized = sum(1 for event in events if event.startswith("recognize"))
        if recognized >= CANCEL_AFTER_RECOGNIZES:
            events.append("cancel")
            raise TaskCancelled("stop")

    async def report(progress: float, msg: str) -> None:
        events.append(msg)

    opts = ConvertOptions(vision_available=True, ocr_available=True)
    pool = ThreadPoolExecutor(max_workers=4)
    try:
        with pytest.raises(TaskCancelled):
            await convert_document(
                path,
                "pdf",
                opts,
                executor=pool,
                ocr=None,
                vision=vision,
                vision_concurrency=VISION_CONCURRENCY,
                check_cancel=check_cancel,
                report=report,
            )
    finally:
        pool.shutdown()

    assert "cancel" in events, "anulowanie nie nastąpiło w trakcie OCR"
    cancel_index = events.index("cancel")
    after_cancel = [event for event in events[cancel_index + 1 :] if event.startswith("recognize")]
    assert len(after_cancel) <= VISION_CONCURRENCY
    recognized = sum(1 for event in events if event.startswith("recognize"))
    assert recognized  # anulowanie zaszło już po rozpoznaniu co najmniej jednej strony
    assert recognized < TOTAL_PAGES  # część stron została nierozpoznana


async def test_batched_result_equals_sequential(tmp_path: Path) -> None:
    """SC-E5-H8a-06 krok 3: wynik partiowy == sekwencyjny (straż regresji, zielony na bazie)."""
    path = tmp_path / "document.pdf"
    path.write_bytes(document_pdf(80))
    opts = ConvertOptions()

    pool = ThreadPoolExecutor(max_workers=4)
    try:
        batched = await convert_document(path, "pdf", opts, executor=pool, ocr=None, vision=None)
    finally:
        pool.shutdown()
    sequential = convert(path, "pdf", opts)

    assert batched.html == sequential.html


# --- bilans cache wizji w logu zadania (kontrakt E5-H8e §C3) ---


async def test_ocr_finish_logs_cache_balance() -> None:
    """``OcrProgress.finish`` dopisuje raz bilans ``OCR pages: k from cache, n to model``."""
    logs: list[str] = []

    async def log(msg: str) -> None:
        logs.append(msg)

    async def check_cancel() -> None:  # hook wymagany przez dataclass; tu nieużywany
        return None

    hooks = TaskLlmHooks(
        log=log, check_cancel=check_cancel, vision_cache_hits=120, vision_model_calls=0
    )
    token = install_hooks(hooks)
    try:
        await OcrProgress(None).finish(120)
    finally:
        reset_hooks(token)
    assert logs == ["OCR pages: 120 from cache, 0 to model"]


async def test_ocr_finish_without_hooks_and_empty_counters_no_line() -> None:
    """Bez hooków lub przy zerowych licznikach nie ma linii bilansu (kontrakt C3)."""
    logs: list[str] = []

    async def log(msg: str) -> None:
        logs.append(msg)

    async def check_cancel() -> None:
        return None

    await OcrProgress(None).finish(0)  # brak hooków — nic nie pada, brak linii
    hooks = TaskLlmHooks(log=log, check_cancel=check_cancel)
    token = install_hooks(hooks)
    try:
        await OcrProgress(None).finish(0)
    finally:
        reset_hooks(token)
    assert logs == []
