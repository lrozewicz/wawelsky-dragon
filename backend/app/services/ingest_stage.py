"""Kroki 5-6 pipeline'u parsowania (kontrakt C7): rozpoznawacze stron i konwersja w puli.

Wydzielone z ``ingest_pipeline`` (DEC-099: limit 400 linii), wołane wyłącznie przez
``run_parse``. Krok 5 (recognizery) i krok 6 (konwersja) nie dotykają bazy — poza
raportem postępu i Stopem przekazywanymi do ``convert_document`` (kontrakt C1/C2).
"""

from __future__ import annotations

from concurrent.futures import Executor
from typing import TYPE_CHECKING, Any

from app.core.errors import NotFound
from app.llm.types import ModelRef
from app.parsing.diacritics_stage import DiacriticsCorrector
from app.parsing.recognizers import PageRecognizer, TesseractRecognizer, VlmRecognizer
from app.parsing.types import ConvertedDocument
from app.services.concurrency import resolve_concurrency
from app.services.ingest_convert import (
    PROGRESS_START,
    convert_document,
    convert_options,
    tesseract_available,
)
from app.services.ingest_diacritics import build_diacritics
from app.services.runpod.guard import ensure_pod_ready
from app.storage.keys import validate_key
from app.worker.errors import PermanentError

if TYPE_CHECKING:
    from app.core.container import Container
    from app.db.repositories.documents import DocumentRow
    from app.llm.gateway import LLMGateway
    from app.llm.registry import ModelRegistry
    from app.services.ingest_progress import ProgressReporter
    from app.worker.context import TaskContext


async def _recognizers(
    container: Container,
    models: ModelRegistry,
    llm: LLMGateway,
    pc: dict[str, Any],
    *,
    layout_vision: bool,
) -> tuple[
    PageRecognizer | None, PageRecognizer | None, DiacriticsCorrector | None, ModelRef | None
]:
    """Krok 5: wizja wg layout_recognize / ocr_engine="vlm", OCR wg dostępności tesseracta.

    Zwraca też rozpoznany ``vision_model`` (``ModelRef``), żeby krok 6 rozwiązał z niego
    ``vision_concurrency`` (``extra.max_concurrency``, kontrakt C2 WP E5-H8b).
    """
    settings = container.settings
    lr = pc.get("layout_recognize")
    vision_model: ModelRef | None = None
    if layout_vision:
        await ensure_pod_ready(container, lr)
        try:
            vision_model = await models.resolve(lr, "image2text")
        except NotFound as exc:
            raise PermanentError(f"image2text model not found: {lr}") from exc
    elif settings.ocr_engine == "vlm":
        try:
            vision_model = await models.resolve(None, "image2text")
        except NotFound:
            vision_model = None  # brak modelu wizji → działamy bez VLM
    vision = VlmRecognizer(llm, vision_model) if vision_model else None
    ocr_ready = settings.ocr_engine != "none" and tesseract_available()
    ocr = TesseractRecognizer(settings.ocr_langs) if ocr_ready else None
    return vision, ocr, await build_diacritics(models, llm, pc), vision_model


async def _convert(  # noqa: PLR0913, PLR0917 — kształt kroku 6 z kontraktu C7
    container: Container,
    rep: ProgressReporter,
    ctx: TaskContext,
    doc: DocumentRow,
    vision: PageRecognizer | None,
    ocr: PageRecognizer | None,
    diacritics: DiacriticsCorrector | None,
    layout_vision: bool,
    vision_model: ModelRef | None,
    *,
    executor: Executor | None,
) -> ConvertedDocument:
    """Krok 6: konwersja w puli (postęp i Stop po partii, kontrakt C1/C2) + ostrzeżenia (max 20)."""
    # Równoległość wizji z ``extra.max_concurrency`` modelu (kontrakt C2 WP E5-H8b): walidacja
    # i log PRZED konwersją — błędna wartość daje czytelny błąd bez wpisu ``Converting pages``,
    # a ``OCR concurrency`` trafia do logu raz, tuż przed konwersją (bez zmiany procentu).
    vision_concurrency = resolve_concurrency(vision_model, container.settings.vlm_concurrency)
    if vision_model is not None:
        await rep.report(
            PROGRESS_START, f"OCR concurrency: {vision_concurrency} ({vision_model.name})"
        )
    pc = doc.parser_config
    path = container.storage.local_path(validate_key(doc.location))
    opts = convert_options(
        pc,
        container.settings,
        layout_vision=layout_vision,
        vision_available=vision is not None,
        ocr_available=ocr is not None,
    )
    converted = await convert_document(
        path,
        doc.suffix,
        opts,
        executor=executor,
        ocr=ocr,
        vision=vision,
        timeout_s=container.settings.parse_timeout_s,
        diacritics=diacritics,
        vision_concurrency=vision_concurrency,
        check_cancel=ctx.check_cancel,
        report=rep.report,
    )
    for warning in converted.warnings[:20]:
        await rep.report(0.40, f"[WARNING] {warning}")
    return converted
