"""SC-E5-H8a-05: log etapu konwersji nazywa etap warstwy tekstowej (brief T2, kontrakt C1).

Test jednostkowy kroku 6 pipeline'u (``_convert``). Odtworzenie pełnej ścieżki integracyjnej
(``run_parse`` z fake-llm i zapisem ``progress_msg``) to >40 linii szkieletu, więc zgodnie
z briefem ograniczamy się do ``_convert`` zbierającego komunikaty (powód w raporcie).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.core.config import Settings
from app.core.container import Container
from app.services.ingest_pipeline import _convert
from tests.unit.services.factories import text_pdf

PAGES = 3  # liczba stron fixture'u (komunikat `Converted 3 pages (text layer)`)


class _Collector:
    """Reporter zbierający komunikaty (zamiast ProgressReporter zapisującego do DB)."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    async def report(self, progress: float, msg: str | None = None) -> None:
        self.messages.append(msg or "")


class _Ctx:
    """Kontekst zadania w minimalnym zakresie: ``check_cancel`` bez anulowania (krok 6)."""

    async def check_cancel(self) -> None:
        return None


async def _run_convert(tmp_path: Path) -> _Collector:
    """Konwersja 3-stronicowego PDF bez wizji/OCR (krok 6) i zebrane komunikaty."""
    key = "files/ds/doc/original.pdf"
    path = tmp_path / key
    path.parent.mkdir(parents=True)
    path.write_bytes(text_pdf(PAGES))
    container = Container(Settings(env="test", storage_root=str(tmp_path)))
    doc = SimpleNamespace(parser_config={}, suffix="pdf", location=key)
    rep = _Collector()

    converted = await _convert(
        container, rep, _Ctx(), doc, None, None, None, False, None, executor=None
    )

    assert converted.pages == PAGES
    return rep


async def test_pipeline_logs_text_layer_stage(tmp_path: Path) -> None:
    """SC-E5-H8a-05: krok konwersji raportuje `Converted 3 pages (text layer)` (kontrakt C1)."""
    rep = await _run_convert(tmp_path)

    assert any("Converted 3 pages (text layer)" in msg for msg in rep.messages)
    assert not any("Page(1~" in msg for msg in rep.messages)


async def test_pipeline_omits_ocr_concurrency_without_vision_model(tmp_path: Path) -> None:
    """Brak modelu wizji (`vision_model=None`) → w logu brak wpisu `OCR concurrency:`.

    Wpis emituje ``ingest_stage._convert`` tylko gdy ``vision_model is not None``
    (kontrakt C2 WP E5-H8b); wariant negatywny do ``test_concurrency`` (SC-E5-H8b-01).
    """
    rep = await _run_convert(tmp_path)

    assert not any("OCR concurrency" in msg for msg in rep.messages)
