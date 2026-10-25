"""Testy wyznaczania spisu treści (K21 §2 p. 2-3; brief V13-1/T3).

Zakładki PDF (reportlab → pypdfium2), nagłówki bloków konwersji, kanonizacja pozycji
i linia logu. Testy korpusowe (marker ``corpus``) czytają PDF-y Codex obok głównego
checkoutu i są pomijane z jawnym komunikatem, gdy korpusu brak (10-testy-jakosc.md §12.3).
"""

import subprocess
import time
from pathlib import Path

import pytest

from app.parsing.blocks import html_to_blocks
from app.parsing.outline import (
    SOURCE_HEADINGS,
    SOURCE_NONE,
    SOURCE_PDF,
    normalize_outline,
    outline_from_blocks,
    outline_from_pdf,
    outline_log_line,
)
from tests.unit.parsing.factories import PdfPage, PdfText, make_pdf
from tests.unit.parsing.outline_pdf import make_outlined_pdf

TITLE_MAX = 300  # K21 §1 — wartości kontraktu wpisane wprost (nie stałe modułu)
ITEMS_MAX = 2000
CORPUS_GUS = "gus_rocznik_statystyczny_rp_2024.pdf"
CORPUS_USTAWA = "projekt_ustawy_o_systemach_ai_2026.pdf"
CORPUS_RAPORT = "raport_o_stanie_zapewnienia_dostepnosci.pdf"
GUS_ENTRIES = 678  # liczby z briefu V13-1/T3 (tabela przykładów)
GUS_LEVELS = {0: 38, 1: 355, 2: 285}
USTAWA_ENTRIES = 15
OUTLINE_TIME_BUDGET_S = 10.0  # budżet K21 (GUS ≤ 5 s) z zapasem na flakowanie
_GIT_COMMON_DIR = ("git", "rev-parse", "--path-format=absolute", "--git-common-dir")


def _corpus_pdf(name: str) -> Path:
    """PDF korpusu Codex obok głównego checkoutu, albo ``pytest.skip`` z komunikatem."""
    common_dir = subprocess.run(  # noqa: S603 - stałe argumenty, bez shell
        _GIT_COMMON_DIR,
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    path = Path(common_dir).parent.parent / "dataset/documents/pl/pdf" / name
    if not path.exists():
        pytest.skip(f"corpus: brak pliku korpusu {path}")
    return path


def test_normalize_outline_trims_collapses_and_skips_empty() -> None:
    """Tytuły: zwinięte białe znaki, przycięte do 300 znaków, puste pominięte (K21 §1)."""
    items = normalize_outline(
        [
            (0, "  Rocznik\n\tstatystyczny   RP  ", 6),
            (1, "   ", 7),
            (2, "x" * (TITLE_MAX + 100), None),
        ]
    )
    assert items == [
        {"level": 0, "title": "Rocznik statystyczny RP", "page": 6},
        {"level": 2, "title": "x" * TITLE_MAX, "page": None},
    ]


def test_normalize_outline_caps_items_at_2000() -> None:
    """Nadmiar pozycji odrzucany od końca; limit wg K21 §1."""
    items = normalize_outline((0, f"dzial-{i}", i + 1) for i in range(ITEMS_MAX + 500))
    assert len(items) == ITEMS_MAX
    assert items[-1]["title"] == f"dzial-{ITEMS_MAX - 1}"


def test_outline_from_pdf_bookmarks_with_page_numbers(tmp_path: Path) -> None:
    """Zakładki PDF: poziom z pypdfium2 bez zmian, strona = indeks celu + 1 (K21 §2 p. 2a)."""
    data = make_outlined_pdf([("Rozdzial I", 0), ("Podrozdzial", 1), ("Dzial", 2)])
    expected = [
        {"level": 0, "title": "Rozdzial I", "page": 1},
        {"level": 1, "title": "Podrozdzial", "page": 2},
        {"level": 2, "title": "Dzial", "page": 3},
    ]
    assert outline_from_pdf(data) == expected
    path = tmp_path / "zakladki.pdf"
    path.write_bytes(data)
    assert outline_from_pdf(path) == expected


def test_outline_from_pdf_without_bookmarks_is_empty() -> None:
    """PDF bez zakładek → pusta lista (źródłem zostaną nagłówki albo ``none``)."""
    data = make_pdf([PdfPage(texts=[PdfText(50, 50, 12, "Akapit bez naglowka")])])
    assert outline_from_pdf(data) == []


def test_outline_from_blocks_headings_with_pages() -> None:
    """Nagłówki bloków: h1 → 0, h2 → 1; strona z ``data-page`` konwersji (K21 §2 p. 2b)."""
    html = (
        "<section data-page='3'><h1>Rozdzial</h1><p>Tekst.</p>"
        "<h2>Podrozdzial</h2><p>Tekst.</p></section>"
    )
    assert outline_from_blocks(html_to_blocks(html)) == [
        {"level": 0, "title": "Rozdzial", "page": 3},
        {"level": 1, "title": "Podrozdzial", "page": 3},
    ]


def test_outline_from_blocks_levels_relative_to_highest() -> None:
    """Bez h1 najwyższy nagłówek dostaje poziom 0; formaty bez stron → ``page=None``."""
    blocks = html_to_blocks("<h2>Rozdzial</h2><p>Tekst.</p><h3>Podrozdzial</h3>")
    assert outline_from_blocks(blocks) == [
        {"level": 0, "title": "Rozdzial", "page": None},
        {"level": 1, "title": "Podrozdzial", "page": None},
    ]


def test_outline_from_blocks_without_headings_is_empty() -> None:
    """Blok bez nagłówków → pusta lista (źródło ``none``)."""
    assert outline_from_blocks(html_to_blocks("<p>Sam tekst.</p>")) == []


def test_outline_log_line_is_literal() -> None:
    """Linia logu dokładnie wg K21 §2 p. 3 (po angielsku, z liczbą pozycji)."""
    assert outline_log_line(SOURCE_PDF, 678) == "Outline: 678 entries (PDF bookmarks)"
    assert outline_log_line(SOURCE_HEADINGS, 4) == "Outline: 4 entries (headings)"
    assert outline_log_line(SOURCE_NONE, 0) == "Outline: none (no bookmarks or headings)"


@pytest.mark.corpus
def test_corpus_gus_outline_matches_contract_and_budget() -> None:
    """Rocznik GUS: 678 pozycji (0: 38, 1: 355, 2: 285), pierwsza bez celu, budżet czasu."""
    path = _corpus_pdf(CORPUS_GUS)
    started = time.monotonic()
    items = outline_from_pdf(path)
    elapsed = time.monotonic() - started
    assert len(items) == GUS_ENTRIES
    assert {
        level: sum(1 for item in items if item["level"] == level) for level in GUS_LEVELS
    } == GUS_LEVELS
    assert items[0] == {
        "level": 0,
        "title": "Rocznik Statystyczny Rzeczypospolitej Polskiej 2024",
        "page": None,
    }
    assert outline_log_line(SOURCE_PDF, len(items)) == "Outline: 678 entries (PDF bookmarks)"
    assert elapsed < OUTLINE_TIME_BUDGET_S, f"spis GUS {elapsed:.2f}s > {OUTLINE_TIME_BUDGET_S}s"


@pytest.mark.corpus
def test_corpus_ustawa_and_raport() -> None:
    """Projekt ustawy ma 15 zakładek, raport dostępności nie ma żadnej (K21 §2 p. 2)."""
    assert len(outline_from_pdf(_corpus_pdf(CORPUS_USTAWA))) == USTAWA_ENTRIES
    assert outline_from_pdf(_corpus_pdf(CORPUS_RAPORT)) == []
