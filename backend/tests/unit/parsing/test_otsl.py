"""Testy konwertera OTSL → HTML na prawdziwych wyjściach Xiaomi-OCR-0 (CONTRACT WP E5-H4a §1)."""

import re
from pathlib import Path

import pytest

from app.parsing.otsl import otsl_to_html

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ocr"
_T17 = "crop_t17_200_table.raw.md"

_T17_ROWS = 20
_T17_COLUMNS = 10
_TWO_ROWS = 2
_ONE_TABLE = 1
_TWO_TABLES = 2

_TABLE_RE = re.compile(r"<table>(.*?)</table>", re.S)
_TR_RE = re.compile(r"<tr>(.*?)</tr>", re.S)
_CELL_RE = re.compile(r'<t([dh])((?: (?:colspan|rowspan)="\d+")*)>(.*?)</t[dh]>', re.S)
_ATTR_RE = re.compile(r'(colspan|rowspan)="(\d+)"')

_RAW_TOKENS = (
    "<fcel>",
    "<ecel>",
    "<lcel>",
    "<ucel>",
    "<xcel>",
    "<nl>",
    "<ched>",
    "<rhed>",
    "<srow>",
)


def _read(name: str) -> str:
    """Treść fixture z OCR."""
    return (_FIXTURES / name).read_text(encoding="utf-8")


def _only_table(text: str) -> str:
    """Wnętrze pierwszej (jedynej) tabeli w wyniku."""
    match = _TABLE_RE.search(text)
    assert match is not None, "brak <table> w wyniku"
    return match.group(1)


def _section(table: str, name: str) -> str:
    """Zawartość ``<thead>``/``<tbody>`` pierwszej tabeli (pusto, gdy brak sekcji)."""
    match = re.search(rf"<{name}>(.*?)</{name}>", table, re.S)
    return match.group(1) if match else ""


def _cells(table: str) -> list[list[tuple[str, int, int]]]:
    """Wiersze tabeli jako ``(treść, colspan, rowspan)``."""
    rows: list[list[tuple[str, int, int]]] = []
    for row_html in _TR_RE.findall(table):
        row: list[tuple[str, int, int]] = []
        for cell in _CELL_RE.finditer(row_html):
            attrs = dict(_ATTR_RE.findall(cell.group(2)))
            colspan = int(attrs.get("colspan", "1"))
            rowspan = int(attrs.get("rowspan", "1"))
            row.append((cell.group(3), colspan, rowspan))
        rows.append(row)
    return rows


def _grid(table: str) -> tuple[list[list[str]], int]:
    """Rozwija ``colspan``/``rowspan`` do prostokątnej siatki; zwraca ``(siatka, szerokość)``."""
    occupancy: dict[tuple[int, int], str] = {}
    for y, row in enumerate(_cells(table)):
        x = 0
        for content, colspan, rowspan in row:
            while (y, x) in occupancy:
                x += 1
            for dy in range(rowspan):
                for dx in range(colspan):
                    occupancy[(y + dy, x + dx)] = content
            x += colspan
    if not occupancy:
        return [], 0
    height = max(py for py, _ in occupancy) + 1
    width = max(px for _, px in occupancy) + 1
    return [[occupancy.get((py, px), "") for px in range(width)] for py in range(height)], width


def _column_with(header: list[list[str]], width: int, *needles: str) -> int:
    """Indeks kolumny, której nagłówki (z góry na dół) zawierają wszystkie ``needles``."""
    for x in range(width):
        column = [header[y][x] for y in range(len(header))]
        if all(any(needle in cell for cell in column) for needle in needles):
            return x
    raise AssertionError(f"brak kolumny dla {needles}")


def test_contract_example() -> None:
    """Przykład dosłownie z briefu/kontraktu."""
    wejscie = "<fcel>A<fcel>2019<lcel><nl><ucel><fcel>x<fcel>y<nl><fcel>w<fcel>1<fcel>2<nl>"
    oczekiwane = (
        '<table><thead><tr><th rowspan="2">A</th><th colspan="2">2019</th></tr>'
        "<tr><th>x</th><th>y</th></tr></thead><tbody><tr><td>w</td><td>1</td><td>2</td></tr>"
        "</tbody></table>"
    )
    assert otsl_to_html(wejscie) == (oczekiwane, [])


def test_plain_text_untouched() -> None:
    assert otsl_to_html("zwykły tekst") == ("zwykły tekst", [])


def test_no_sensible_row_left_as_text() -> None:
    """Segment OTSL bez żadnej komórki danych: tekst bez zmian + ostrzeżenie (CONTRACT §1)."""
    wejscie = "Text\n\n<nl><nl>\n\nMore"
    wynik, ostrzezenia = otsl_to_html(wejscie)
    assert wynik == wejscie
    assert ostrzezenia == ["OTSL segment without cells: left as text"]


def test_plain_text_around_single_row_table() -> None:
    wejscie = "Tytuł\n\n<fcel>x<nl>\n\nkoniec"
    wynik, ostrzezenia = otsl_to_html(wejscie)
    assert wynik.startswith("Tytuł\n\n")
    assert wynik.endswith("\n\nkoniec")
    assert "<table><tbody><tr><td>x</td></tr></tbody></table>" in wynik
    assert ostrzezenia == []


def test_truncated_closes_row_with_warning() -> None:
    wynik, ostrzezenia = otsl_to_html("<fcel>a<fcel>b<nl><fcel>1<fcel>2")
    assert ostrzezenia == ["OTSL truncated: closed last row"]
    assert wynik.count("<tr>") == _TWO_ROWS
    assert "<td>1</td><td>2</td>" in wynik


def test_ched_rhed_become_th() -> None:
    wynik, _ = otsl_to_html("<ched>H1<rhed>H2<nl><fcel>a<fcel>b<nl>")
    assert "<thead><tr><th>H1</th><th>H2</th></tr></thead>" in wynik
    assert "<tbody><tr><td>a</td><td>b</td></tr></tbody>" in wynik


def test_srow() -> None:
    wynik, _ = otsl_to_html("<fcel>Kolumna<nl><srow>SEKCJA<nl><fcel>a<nl>")
    assert "<td>SEKCJA</td>" in wynik
    assert "<th>SEKCJA</th>" not in wynik


def test_empty_cells_ecel() -> None:
    wynik, _ = otsl_to_html("<fcel>h<nl><fcel>1<ecel><nl>")
    assert "<th>h</th>" in wynik
    assert "<td>1</td><td></td>" in wynik


def test_t17_header_colspan() -> None:
    wynik, _ = otsl_to_html(_read(_T17))
    thead = _section(_only_table(wynik), "thead")
    for rok in ("2019", "2020", "2022", "2023"):
        assert f'<th colspan="2">{rok}</th>' in thead


def test_t17_value_columns() -> None:
    wynik, _ = otsl_to_html(_read(_T17))
    table = _only_table(wynik)
    header, width = _grid(_section(table, "thead"))
    body, body_width = _grid(_section(table, "tbody"))
    assert width == _T17_COLUMNS
    assert body_width == _T17_COLUMNS
    wiersz = next(row for row in body if row[0].startswith("15"))
    assert wiersz[_column_with(header, width, "2019", "ogólem total")] == "9,9"
    assert wiersz[_column_with(header, width, "2022", "ogólem total")] == "10,8"
    assert wiersz[_column_with(header, width, "2022", "w tym kobiety")] == "11,3"
    assert wiersz[_column_with(header, width, "2023", "ogólem total")] == "11,3"


def test_row_and_column_counts() -> None:
    raw = _read(_T17)
    wynik, _ = otsl_to_html(raw)
    assert wynik.count("<tr>") == raw.count("<nl>") == _T17_ROWS
    grid, width = _grid(_only_table(wynik))
    assert width == _T17_COLUMNS
    assert len(grid) == _T17_ROWS


@pytest.mark.parametrize("name", ["crop_t14_200_table.raw.md", "crop_t08_200_table.raw.md"])
def test_t14_and_t08_no_exception(name: str) -> None:
    wynik, _ = otsl_to_html(_read(name))
    assert "<table>" in wynik
    for token in _RAW_TOKENS:
        assert token not in wynik


def test_p241_doc_keeps_markdown_around_table() -> None:
    wynik, _ = otsl_to_html(_read("p241_doc.raw.md"))
    assert "TABL. 17" in wynik
    assert "<table>" in wynik
    for token in _RAW_TOKENS:
        assert token not in wynik


@pytest.mark.parametrize(
    ("name", "tables"),
    [("p238_doc.raw.md", _ONE_TABLE), ("p232_doc.raw.md", _TWO_TABLES)],
)
def test_p238_p232_no_raw_tokens(name: str, tables: int) -> None:
    wynik, _ = otsl_to_html(_read(name))
    assert wynik.count("<table>") == tables
    for token in _RAW_TOKENS:
        assert token not in wynik
