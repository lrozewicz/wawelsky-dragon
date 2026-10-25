"""Testy układu strony PDF (C7): tabele, klucze linii, powtórzenia, nagłówki, akapity."""

import io
import re

import pdfplumber
import pypdfium2
import pytest

from app.parsing.converters.pdf_layout import (
    TextLine,
    line_key,
    looks_like_table,
    page_lines,
    render_text_page,
    repeated_lines,
)
from tests.unit.parsing.factories import PdfPage, PdfText, body_text, make_pdf


def _line(text: str, top: float, bottom: float) -> TextLine:
    """Zwięzły konstruktor linii do testów powtórzeń (tylko pola używane przez repeated_lines)."""
    return TextLine(text=text, x0=0.0, top=top, x1=10.0, bottom=bottom, size=11.0)


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        ([["a", "b"], ["c", "d"]], True),  # 2x2 pełna
        ([["a", "b", "c", "d", "e"]], False),  # 1 wiersz
        ([["a"], ["b"], ["c"]], False),  # 1 kolumna
        ([["a", "b"], ["c", ""]], False),  # 3 niepuste komórki
        (
            [
                ["a", "", "", ""],
                ["", "", "", ""],
                ["", "", "", ""],
                ["b", "", "c", "d"],
            ],
            True,
        ),  # 4 niepuste na 16 komórek = 25%
        ([["a", "b", None], ["c", None, None]], False),  # 3 niepuste, reszta None
    ],
)
def test_looks_like_table(rows: list[list[str | None]], expected: bool) -> None:
    assert looks_like_table(rows) is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Strona 12  z 30", "strona # z #"),
        ("Raport roczny 2024", "raport roczny #"),
    ],
)
def test_line_key(text: str, expected: str) -> None:
    assert line_key(text) == expected


def test_repeated_lines_three_pages_same_header() -> None:
    pages = [(842.0, [_line("Raport roczny", 20.0, 31.0)]) for _ in range(3)]
    assert repeated_lines(pages) == frozenset({"raport roczny"})


def test_repeated_lines_two_pages_below_threshold() -> None:
    pages = [(842.0, [_line("Raport roczny", 20.0, 31.0)]) for _ in range(2)]
    assert repeated_lines(pages) == frozenset()


def test_repeated_lines_single_page_line_ignored() -> None:
    pages = [
        (842.0, [_line("Raport roczny", 20.0, 31.0)]),
        (842.0, [_line("Inny naglowek", 20.0, 31.0)]),
        (842.0, [_line("Trzeci naglowek", 20.0, 31.0)]),
    ]
    assert repeated_lines(pages) == frozenset()


def test_repeated_lines_middle_of_page_ignored() -> None:
    pages = [(842.0, [_line("Raport roczny", 400.0, 411.0)]) for _ in range(3)]
    assert repeated_lines(pages) == frozenset()


def test_repeated_lines_counts_pages_not_occurrences() -> None:
    # ten sam nagłówek dwa razy w strefie na JEDNEJ stronie nie jest powtarzalny
    pages = [
        (842.0, [_line("Raport roczny", 20.0, 31.0), _line("Raport roczny", 40.0, 51.0)]),
        (842.0, [_line("Inny tekst", 20.0, 31.0)]),
        (842.0, [_line("Jeszcze inny tekst", 20.0, 31.0)]),
    ]
    assert repeated_lines(pages) == frozenset()


def test_factories_pdf_opens_in_pdfium_and_pdfplumber() -> None:
    data = make_pdf(
        [
            PdfPage(texts=[PdfText(72, 72, 11, "Ala ma kota")]),
            PdfPage(texts=[PdfText(72, 72, 11, "Druga strona")]),
        ]
    )
    pdf = pypdfium2.PdfDocument(io.BytesIO(data))
    try:
        assert len(pdf) == 2  # noqa: PLR2004 — wartość konstruowana w teście
    finally:
        pdf.close()
    with pdfplumber.open(io.BytesIO(data)) as document:
        assert len(document.pages) == 2  # noqa: PLR2004 — wartość konstruowana w teście
        assert "Ala ma kota" in document.pages[0].extract_text()


def _render(page: PdfPage) -> str:
    """page_lines + render_text_page na stronie z factories (bez drop)."""
    data = make_pdf([page])
    with pdfplumber.open(io.BytesIO(data)) as document:
        plumber_page = document.pages[0]
        return render_text_page(plumber_page, page_lines(plumber_page), frozenset())


def test_page_lines_sizes_and_geometry() -> None:
    data = make_pdf(
        [PdfPage(texts=[PdfText(72, 72, 24, "Wstep"), PdfText(72, 150, 11, body_text(3))])]
    )
    with pdfplumber.open(io.BytesIO(data)) as document:
        lines = page_lines(document.pages[0])
    assert [line.size for line in lines] == [24.0, 11.0]
    assert [line.text for line in lines] == ["Wstep", "lorem0 lorem1 lorem2"]
    assert lines[0].x0 == 72.0  # noqa: PLR2004 — wartość konstruowana w teście
    assert lines[0].top < lines[0].bottom


@pytest.mark.parametrize(("heading_size", "tag"), [(24, "h2"), (15, "h3")])
def test_render_heading_from_font_size(heading_size: float, tag: str) -> None:
    html = _render(
        PdfPage(
            texts=[
                PdfText(72, 72, heading_size, "Wstep"),
                PdfText(72, 150, 11, body_text(10)),
                PdfText(72, 400, 11, body_text(10)),
            ]
        )
    )
    assert html.startswith(f"<{tag}>Wstep</{tag}>")
    other = "h3" if tag == "h2" else "h2"
    assert f"<{other}>" not in html  # nagłówek dokładnie jednego poziomu


def test_render_two_paragraphs_with_gap() -> None:
    html = _render(
        PdfPage(
            texts=[
                PdfText(72, 100, 11, body_text(10)),
                PdfText(72, 400, 11, body_text(10)),
            ]
        )
    )
    assert len(re.findall(r"<p ", html)) == 2  # noqa: PLR2004 — wartość konstruowana w teście
    for bbox in re.findall(r'data-bbox="([^"]+)"', html):
        values = bbox.split(",")
        assert len(values) == 4  # noqa: PLR2004 — cztery liczby całkowite w bbox
        assert all(value.lstrip("-").isdigit() for value in values)


def test_render_table_grid_with_theadead() -> None:
    grid = (50.0, 100.0, 350.0, 300.0, 3, 3)
    labels = [["A", "B", "C"], ["D", "E", "F"], ["G", "H", "I"]]
    cell_w, cell_h = (350.0 - 50.0) / 3, (300.0 - 100.0) / 3
    texts = [
        PdfText(50.0 + (j + 0.5) * cell_w - 5, 100.0 + (i + 0.5) * cell_h - 5, 11, labels[i][j])
        for i in range(3)
        for j in range(3)
    ]
    html = _render(PdfPage(texts=texts, grid=grid))
    assert '<table data-bbox="50,100,350,300">' in html
    assert "<thead><tr><th>A</th><th>B</th><th>C</th></tr></thead>" in html
    assert "<td>D</td><td>E</td><td>F</td>" in html
    assert "<p" not in html  # tekst komórek nie powtarza się w akapitach


def test_render_heading_median_counts_all_lines() -> None:
    # mediana z WSZYSTKICH linii strony (też komórek tabeli), nie tylko z linii poza tabelą
    grid = (50.0, 100.0, 350.0, 200.0, 3, 3)
    labels = [["A", "B", "C"], ["D", "E", "F"], ["G", "H", "I"]]
    cell_w, cell_h = (350.0 - 50.0) / 3, (200.0 - 100.0) / 3
    texts = [
        PdfText(50.0 + (j + 0.5) * cell_w - 5, 100.0 + (i + 0.5) * cell_h - 5, 11, labels[i][j])
        for i in range(3)
        for j in range(3)
    ]
    texts.append(PdfText(72, 400, 20, "Podsumowanie"))
    html = _render(PdfPage(texts=texts, grid=grid))
    assert "<h2>Podsumowanie</h2>" in html  # 20 pt >= 1.6 * 11 pt


def test_render_block_order_by_top() -> None:
    html = _render(
        PdfPage(
            texts=[
                PdfText(72, 400, 11, body_text(5)),
                PdfText(72, 72, 24, "Wstep"),
                PdfText(72, 500, 11, body_text(5)),
            ]
        )
    )
    assert html.index("<h2>Wstep</h2>") < html.index("<p ")
