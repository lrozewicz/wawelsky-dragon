"""Rozpoznawanie stron OCR/VLM (kontrakt C10, K5 §4.2) — wypełnianie pustych sekcji."""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from io import BytesIO
from typing import Literal, Protocol

import pytesseract
from markdown_it import MarkdownIt
from PIL import Image

from app.core.errors import WDError
from app.llm.gateway import LLMGateway
from app.llm.types import ModelRef
from app.parsing.cancel_watch import run_with_cancel_watch
from app.parsing.diacritics_stage import DiacriticsCorrector
from app.parsing.errors import binary_missing, empty_document
from app.parsing.html import paragraphs_html, sanitize_html, section_html, text_chars
from app.parsing.otsl import otsl_to_html
from app.parsing.types import ConvertedDocument, PendingPage

VLM_MAX_TOKENS: int = 4096

VLM_PROMPT: str = (
    "Przepisz treść strony z obrazu do kodu HTML: nagłówki h1-h6, akapity jako p, "
    "listy jako ul/ol, tabele jako <table> z <thead>, a wykresy i infografiki opisz "
    "w <figure><figcaption> z odczytanymi z nich liczbami. "
    "Zwróć wyłącznie HTML, bez komentarzy."
)

# Profil OTSL (Xiaomi-OCR-0): prompt i limit z benchu ../ocr-bench/xiaomi-ocr-0 (CONTRACT §3).
OTSL_MAX_TOKENS: int = 8192

OTSL_PROMPT: str = (
    "Extract all information from the main body of the document image and represent it "
    "in markdown format, ignoring headers and footers. Tables should be expressed in OTSL "
    "format, formulas in the document should be represented using LATEX format, and the "
    "parsing should be organized according to the reading order."
)

VisionProfile = Literal["html", "otsl"]

# Renderer Markdown→HTML OTSL; HTML bloków <table> przechodzi (commonmark: html=True).
_OTSL_MD = MarkdownIt("commonmark").enable("table")


def vision_profile(model_name: str) -> VisionProfile:
    """Profil wizji wg nazwy modelu: modele OTSL (Xiaomi-OCR-0) → "otsl", reszta → "html"."""
    lowered = model_name.lower()
    if "xiaomi-ocr" in lowered or "fake-ocr" in lowered:
        return "otsl"
    return "html"


# Porażka próby: RuntimeError obejmuje pytesseract.TesseractError, OSError — NotFoundError.
_RECOGNIZE_ERRORS = (WDError, TimeoutError, RuntimeError, OSError)
_EMPTY_RESPONSE = "EmptyResponse"  # nazwa porażki, gdy odpowiedź nie zawiera tekstu

_FENCE_RE = re.compile(r"```[^\n]*\n(.*)\n```", re.DOTALL)
_BODY_OPEN_RE = re.compile(r"<body[^>]*>", re.IGNORECASE)


class PageRecognizer(Protocol):
    """Port rozpoznawacza strony: PNG → fragment HTML."""

    name: str

    async def recognize(
        self, image_png: bytes, *, page: int, hint: str | None = None, use_cache: bool = True
    ) -> str: ...


def extract_body(raw: str) -> str:
    """Zdejmuje otaczający blok ``` i wrappery <html>/<body> — zostawia sam fragment."""
    text = raw.strip()
    fence = _FENCE_RE.fullmatch(text)
    if fence:
        text = fence.group(1)
    body = _BODY_OPEN_RE.search(text)
    if body:
        start = body.end()
        end = text.lower().find("</body>")
        text = text[start:] if end == -1 else text[start:end]
    return text.strip()


class TesseractRecognizer:
    """OCR przez pytesseract (blokujący — wywołanie przenoszone do wątku)."""

    name = "tesseract"

    def __init__(self, langs: str = "pol+eng", *, timeout_s: float = 120.0) -> None:
        if shutil.which("tesseract") is None:
            raise binary_missing("tesseract")
        self._langs = langs
        self._timeout_s = timeout_s

    async def recognize(
        self, image_png: bytes, *, page: int, hint: str | None = None, use_cache: bool = True
    ) -> str:
        text = await asyncio.to_thread(
            pytesseract.image_to_string,
            Image.open(BytesIO(image_png)),
            lang=self._langs,
            timeout=self._timeout_s,
        )
        return paragraphs_html(text)


class VlmRecognizer:
    """Wizja przez LLMGateway.vision; odpowiedź obcinana do zawartości <body>."""

    name = "vlm"

    def __init__(self, llm: LLMGateway, model: ModelRef, *, timeout_s: float = 120.0) -> None:
        self._llm = llm
        self._model = model
        self._timeout_s = timeout_s
        self._profile = vision_profile(model.name)
        self.warnings: list[str] = []
        # Nazwa w logach to nazwa modelu (kontrakt C1 WP E5-H8a); klasowe "vlm" zostaje fallbackiem.
        if model.name:
            self.name = model.name

    async def recognize(
        self, image_png: bytes, *, page: int, hint: str | None = None, use_cache: bool = True
    ) -> str:
        if self._profile == "otsl":
            return await self._recognize_otsl(image_png, page, use_cache=use_cache)
        prompt = f"{VLM_PROMPT}\n\n{hint}" if hint else VLM_PROMPT
        raw = await asyncio.wait_for(
            self._llm.vision(
                self._model, prompt, image_png, max_tokens=VLM_MAX_TOKENS, cache=use_cache
            ),
            self._timeout_s,
        )
        return extract_body(raw)

    async def _recognize_otsl(self, image_png: bytes, page: int, *, use_cache: bool = True) -> str:
        """Profil OTSL: prompt bez hintu, temperature=0, odpowiedź Markdown → HTML z tabelami."""
        raw = await asyncio.wait_for(
            self._llm.vision(
                self._model,
                OTSL_PROMPT,
                image_png,
                max_tokens=OTSL_MAX_TOKENS,
                temperature=0.0,
                cache=use_cache,
            ),
            self._timeout_s,
        )
        markdown, warns = otsl_to_html(extract_body(raw))
        self.warnings.extend(f"page {page}: {w}" for w in warns)
        return str(_OTSL_MD.render(markdown))


async def _attempt(
    rec: PageRecognizer, png: bytes, page_no: int, hint: str | None, *, use_cache: bool
) -> tuple[str | None, str | None]:
    """Jedna próba: (fragment, None) przy sukcesie, (None, nazwa porażki) w przeciwnym razie."""
    try:
        fragment = await rec.recognize(png, page=page_no, hint=hint, use_cache=use_cache)
    except _RECOGNIZE_ERRORS as exc:
        return None, type(exc).__name__
    if text_chars(sanitize_html(fragment)) > 0:
        return fragment, None
    return None, _EMPTY_RESPONSE


async def _recognize_page(
    pending: PendingPage,
    ocr: PageRecognizer | None,
    vision: PageRecognizer | None,
    sem: asyncio.Semaphore,
    diacritics: DiacriticsCorrector | None,
) -> tuple[PendingPage, str | None, PageRecognizer | None, list[str]]:
    """Łańcuch prób strony: (pending, fragment, rozpoznawacz, warningi); korekta diakrytyków
    tylko z wizji, pod wspólnym semaforem (DEC-249 p. 7)."""
    chain: list[tuple[PageRecognizer | None, int]] = (
        [(vision, 2), (ocr, 1)] if pending.mode == "vision" else [(ocr, 1), (vision, 2)]
    )
    warnings: list[str] = []
    async with sem:
        for rec, tries in chain:
            if rec is None:
                continue
            failure: str | None = _EMPTY_RESPONSE
            for attempt in range(tries):
                # Spłata długu E1-4: reason nie trafia już do promptu jako hint (None).
                # Pierwsza próba strony z cache wizji, ponowienie bez (DEC-293 p.1).
                fragment, failure = await _attempt(
                    rec, pending.image_png, pending.page, None, use_cache=attempt == 0
                )
                if fragment is not None:
                    if diacritics is not None and rec is vision:
                        fragment, correction = await diacritics.correct(
                            fragment, layer_text=pending.text_layer, page=pending.page
                        )
                        warnings.extend(correction)
                    return pending, fragment, rec, warnings
            warnings.append(f"page {pending.page}: {rec.name} failed ({failure})")
    return pending, None, None, warnings


def _insert_fragment(html: str, page_no: int, fragment: str) -> str:
    """Wstawia fragment do sekcji strony/slajdu (przed `</section>`) albo dopisuje nową na końcu."""
    for attr in ("data-page", "data-slide"):
        start_marker = f'<section {attr}="{page_no}">'
        start = html.find(start_marker)
        if start == -1:
            continue
        end = html.find("</section>", start + len(start_marker))
        if end == -1:
            continue
        return html[:end] + fragment + html[end:]
    return html + section_html("page", page_no, fragment)


ProgressFn = Callable[[int, int, str], Awaitable[None]]
"""`on_progress(done, total, recognizer_name)` — po każdej rozpoznanej stronie (kontrakt C2)."""
CancelFn = Callable[[], Awaitable[None]]
"""`check_cancel` — wołany przed rozpoznaniem każdej strony; wyjątek przerywa rozpoznawanie."""

PageOutcome = tuple[PendingPage, str | None, PageRecognizer | None, list[str]]


@dataclass
class RecognitionResult:
    """Wynik rozpoznawania stron: wpisy ``(pending, fragment, rozpoznawacz, warningi)`` (C2);
    ``fragment`` jest ``None``, gdy żaden rozpoznawacz nie dał tekstu."""

    outcomes: list[PageOutcome]


def _recognizer_name(vision: PageRecognizer | None, ocr: PageRecognizer | None) -> str:
    """Domyślna nazwa modelu do postępu OCR, gdy żadna strona nie została jeszcze rozpoznana."""
    if vision is not None:
        return vision.name
    return ocr.name if ocr is not None else ""


def apply_recognition(
    doc: ConvertedDocument, outcomes: Sequence[PageOutcome], vision: PageRecognizer | None
) -> ConvertedDocument:
    """Wstawia fragmenty do HTML i domyka statystyki (wspólne dla potoku i ``complete_pages``)."""
    if not doc.pending_pages:
        return doc
    html = doc.html
    warnings = list(doc.warnings)
    # Ostrzeżenia rozpoznawacza wizji (OTSL): pobrane raz, bez duplikatów retry.
    warnings.extend(getattr(vision, "warnings", []))
    pages_ocr = 0
    pages_vision = 0
    empty_pages = 0
    for pending, fragment, rec, page_warnings in outcomes:
        warnings.extend(page_warnings)
        if fragment is None:
            empty_pages += 1
            warnings.append(f"page {pending.page}: no text recognized ({pending.reason})")
            continue
        html = _insert_fragment(html, pending.page, fragment)
        if rec is vision:
            pages_vision += 1
        else:
            pages_ocr += 1
    total = len(doc.pending_pages)
    if empty_pages * 2 >= total:
        warnings.append(f"{empty_pages} of {total} pages have no text after OCR/VLM")
    clean = sanitize_html(html)
    if text_chars(clean) == 0:
        raise empty_document("no text recognized by OCR/VLM")
    stats = dict(doc.stats)
    stats["chars"] = text_chars(clean)
    # Jedna prawda o licznikach (CONTRACT WP E5-H6d §3): ostateczna wartość to strony
    # faktycznie rozpoznane przez dany rozpoznawacz. Konwersja PDF liczy wstępnie strony
    # pending (podgląd przed rozpoznaniem), więc nadpisujemy, a nie dodajemy.
    stats["pages_ocr"] = pages_ocr
    stats["pages_vision"] = pages_vision
    return ConvertedDocument(clean, doc.pages, [], dict(doc.metadata), warnings, stats)


async def _pending_iter(pages: Sequence[PendingPage]) -> AsyncIterator[PendingPage]:
    """Strumień stron dla ``recognize_stream`` z gotowej listy (``complete_pages``)."""
    for page in pages:
        yield page


async def recognize_stream(  # noqa: PLR0913 — sygnatura z kontraktu C2
    pending_iter: AsyncIterator[PendingPage],
    *,
    ocr: PageRecognizer | None,
    vision: PageRecognizer | None,
    vision_concurrency: int = 3,
    diacritics: DiacriticsCorrector | None = None,
    check_cancel: CancelFn | None = None,
    on_progress: ProgressFn | None = None,
) -> RecognitionResult:
    """Rozpoznaje strony z kolejki (``vision_concurrency`` workerów); ``total`` rośnie z napływem.

    ``check_cancel`` (przed stroną i w tle) anuluje; ``vision_concurrency < 1`` → ValueError."""
    if vision_concurrency < 1:
        raise ValueError("vision_concurrency must be >= 1")
    queue: asyncio.Queue[PendingPage | None] = asyncio.Queue(maxsize=vision_concurrency * 2)
    sem = asyncio.Semaphore(vision_concurrency)
    outcomes: list[PageOutcome] = []
    counter = {"total": 0, "done": 0}  # total = strony pobrane z wejścia, done = ukończone
    last_name = _recognizer_name(vision, ocr)
    lock = asyncio.Lock()

    async def producer() -> None:
        async for page in pending_iter:
            counter["total"] += 1
            await queue.put(page)
        for _ in range(vision_concurrency):
            await queue.put(None)

    async def worker() -> None:
        nonlocal last_name
        while True:
            page = await queue.get()
            if page is None:
                return
            if check_cancel is not None:
                await check_cancel()
            outcome = await _recognize_page(page, ocr, vision, sem, diacritics)
            outcomes.append((replace(outcome[0], image_png=b""), *outcome[1:]))  # bez PNG
            if on_progress is not None:
                async with lock:  # emisja w kolejności ukończeń (rosnące `done`)
                    counter["done"] += 1
                    rec = outcome[2]
                    if rec is not None:
                        last_name = rec.name
                    await on_progress(counter["done"], counter["total"], last_name)

    tasks = [asyncio.create_task(producer(), name="ocr-producer")]
    tasks += [
        asyncio.create_task(worker(), name=f"ocr-worker-{index}")
        for index in range(vision_concurrency)
    ]
    try:
        await run_with_cancel_watch(asyncio.gather(*tasks), check_cancel)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    return RecognitionResult(outcomes)


async def complete_pages(  # noqa: PLR0913 — sygnatura z kontraktu C2
    doc: ConvertedDocument,
    *,
    ocr: PageRecognizer | None,
    vision: PageRecognizer | None,
    vision_concurrency: int = 3,
    diacritics: DiacriticsCorrector | None = None,
    check_cancel: CancelFn | None = None,
    on_progress: ProgressFn | None = None,
) -> ConvertedDocument:
    """Wypełnia sekcje z pending_pages (vision: 2 próby, ocr: 1); wejście pozostaje niezmienione."""
    if vision_concurrency < 1:
        raise ValueError("vision_concurrency must be >= 1")
    if not doc.pending_pages:
        return doc
    result = await recognize_stream(
        _pending_iter(doc.pending_pages),
        ocr=ocr,
        vision=vision,
        vision_concurrency=vision_concurrency,
        diacritics=diacritics,
        check_cancel=check_cancel,
        on_progress=on_progress,
    )
    return apply_recognition(doc, result.outcomes, vision)


def _probe(binary: str, args: list[str]) -> bool:
    """Sprawdza obecność binarki i jej reakcję na --version (dowolny kod wyjścia)."""
    if shutil.which(binary) is None:
        return False
    try:
        subprocess.run([binary, *args], capture_output=True, timeout=5, check=False)  # noqa: S603 — lista argumentów bez powłoki, binarki z self-check
    except (OSError, subprocess.TimeoutExpired):
        return False
    return True


def self_check() -> dict[str, bool]:
    """Dostępność narzędzi OCR/konwersji na tym hoście (bez logowania)."""
    return {
        "tesseract": _probe("tesseract", ["--version"]),
        "wvHtml": _probe("wvHtml", ["--version"]),
        "catppt": _probe("catppt", ["-V"]),
    }
