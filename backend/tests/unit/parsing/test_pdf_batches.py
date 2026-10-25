"""Testy partii PDF: wynik niezależny od PAGE_BATCH (T2) i API faz A/B/C (E5-H8a T3)."""

import pickle
from pathlib import Path

import pytest

from app.parsing.converters import pdf as pdf_module
from app.parsing.converters.pdf import (
    convert_pdf,
    pdf_assemble,
    pdf_plan,
    pdf_render_batch,
    pdf_repeated,
    pdf_route_batch,
)
from app.parsing.types import ConvertOptions
from tests.unit.parsing.factories import PdfPage, PdfText, body_text, make_pdf

LONG_PAGES = 60  # > 2x PAGE_BATCH (25), żeby wynik zależał od granic partii

BATCHES = (1, 7, 1000)


def _write_pdf(tmp_path: Path, pages: list[PdfPage]) -> Path:
    path = tmp_path / "long.pdf"
    path.write_bytes(make_pdf(pages))
    return path


def _document_pages(count: int) -> list[PdfPage]:
    """Strony z powtarzanym nagłówkiem i stopką oraz treścią — do wyznaczenia powtórzeń."""
    return [
        PdfPage(
            texts=[
                PdfText(72, 20, 11, "Rocznik statystyczny"),
                PdfText(72, 100, 11, body_text(40)),
                PdfText(72, 820, 11, f"Strona {number}"),
            ]
        )
        for number in range(1, count + 1)
    ]


def test_batch_size_does_not_change_html(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _write_pdf(tmp_path, _document_pages(LONG_PAGES))
    documents = []
    for batch in BATCHES:
        monkeypatch.setattr(pdf_module, "PAGE_BATCH", batch)
        documents.append(convert_pdf(path, ConvertOptions()))

    reference = documents[0]
    assert (
        "Rocznik statystyczny" not in reference.html
    )  # nagłówek powtórzony na wszystkich stronach
    assert "Strona" not in reference.html  # stopka powtórzona na wszystkich stronach
    assert "lorem0" in reference.html  # treść stron zostaje
    assert reference.stats["pages_text"] == LONG_PAGES
    for other in documents[1:]:
        assert other.html == reference.html
        assert other.stats == reference.stats
        assert other.warnings == reference.warnings
        assert other.pending_pages == reference.pending_pages
        assert other.metadata == reference.metadata


def test_batch_size_does_not_change_pending_render(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    count = 12  # > 2x kilku partii przy PAGE_BATCH=7
    path = _write_pdf(tmp_path, _document_pages(count))
    opts = ConvertOptions(pdf_strategy="vision", vision_available=True)
    documents = []
    for batch in (1, 1000):
        monkeypatch.setattr(pdf_module, "PAGE_BATCH", batch)
        documents.append(convert_pdf(path, opts))

    reference = documents[0]
    assert [pending.page for pending in reference.pending_pages] == list(range(1, count + 1))
    assert all(pending.image_png.startswith(b"\x89PNG") for pending in reference.pending_pages)
    for other in documents[1:]:
        assert other.html == reference.html
        assert other.pending_pages == reference.pending_pages


def test_pdf_plan_batches_selected_pages(tmp_path: Path) -> None:
    """(a) PdfPlan: 60 stron → partie 25/25/10 (numery 1-based), metadane puste."""
    path = _write_pdf(tmp_path, _document_pages(60))
    plan = pdf_plan(path, ConvertOptions())
    assert plan.total == 60  # noqa: PLR2004 — liczba stron konstruowana w teście
    assert plan.batches == (tuple(range(1, 26)), tuple(range(26, 51)), tuple(range(51, 61)))
    assert plan.metadata == {}


def test_pdf_plan_respects_pages_filter(tmp_path: Path) -> None:
    """(a) opts.pages=((3,30),) → partie po 25 z wybranych stron (3..30 = 28 stron)."""
    path = _write_pdf(tmp_path, _document_pages(60))
    plan = pdf_plan(path, ConvertOptions(pages=((3, 30),)))
    assert plan.batches == (tuple(range(3, 28)), tuple(range(28, 31)))


def test_assemble_is_independent_of_batch_order(tmp_path: Path) -> None:
    """(b) faza C partii w kolejności 3,1,2 → pdf_assemble daje HTML jak convert_pdf."""
    path = _write_pdf(tmp_path, _document_pages(60))
    opts = ConvertOptions()
    plan = pdf_plan(path, opts)
    routed = [pdf_route_batch(path, pages, opts) for pages in plan.batches]
    drop = pdf_repeated([page for batch in routed for page in batch.routed])
    rendered = [pdf_render_batch(path, routed[index].routed, drop, opts) for index in (2, 0, 1)]
    pending = [page for batch in routed for page in batch.pending]

    reference = convert_pdf(path, opts)
    shuffled = pdf_assemble(plan, pending, rendered)
    assert shuffled.html == reference.html
    assert shuffled.stats == reference.stats


def test_batch_results_are_picklable(tmp_path: Path) -> None:
    """(c) PdfPlan/RoutedBatch/RenderedBatch przechodzą pickle.dumps/loads (pula forkserver)."""
    path = _write_pdf(tmp_path, _document_pages(30))
    opts = ConvertOptions(pdf_strategy="vision", vision_available=True)
    plan = pdf_plan(path, opts)
    routed = pdf_route_batch(path, plan.batches[0], opts)
    drop = pdf_repeated(routed.routed)
    rendered = pdf_render_batch(path, routed.routed, drop, opts)

    assert len(routed.pending) == 25  # noqa: PLR2004 — cała partia to strony pending (vision)
    assert [page.page for page in routed.pending] == list(range(1, 26))
    for obj in (plan, routed, rendered):
        assert pickle.loads(pickle.dumps(obj)) == obj  # noqa: S301 — pickle własnych obiektów


def test_phase_b_drop_matches_convert_pdf(tmp_path: Path) -> None:
    """(d) ręczne A→B→C usuwa nagłówek/stopkę z HTML tak samo jak convert_pdf."""
    path = _write_pdf(tmp_path, _document_pages(60))
    opts = ConvertOptions()
    plan = pdf_plan(path, opts)
    routed = [pdf_route_batch(path, pages, opts) for pages in plan.batches]
    drop = pdf_repeated([page for batch in routed for page in batch.routed])
    rendered = [pdf_render_batch(path, batch.routed, drop, opts) for batch in routed]
    pending = [page for batch in routed for page in batch.pending]

    manual = pdf_assemble(plan, pending, rendered)
    assert "Rocznik statystyczny" not in manual.html  # nagłówek na każdej stronie → drop
    assert "Strona 5" not in manual.html  # stopka na każdej stronie → drop
    assert "lorem0" in manual.html  # treść stron zostaje
    assert manual.html == convert_pdf(path, opts).html
