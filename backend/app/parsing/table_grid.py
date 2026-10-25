"""Siatka tabel HTML (colspan/rowspan) dla `blocks.py` (CONTRACT WP E5-H4a §2 / DEC-246).

Osobny moduł z powodu limitu 400 linii `blocks.py` (DEC-247). Czyste funkcje, bez stanu
parsera; nie znają `_Parser` ani typu `_Row`.
"""

from collections.abc import Sequence

_Span = tuple[int, int]  # (colspan, rowspan)
GridRow = tuple[Sequence[str], str, Sequence[_Span]]  # struktura wiersza z blocks.py


def parse_span(attrs: Sequence[tuple[str, str | None]], name: str) -> int:
    """colspan/rowspan: brak, wartość nieliczbowa albo <= 0 → 1."""
    for key, value in attrs:
        if key == name:
            if value is None:
                return 1
            try:
                span = int(value)
            except ValueError:
                return 1
            return span if span > 0 else 1
    return 1


def cell_span(attrs: Sequence[tuple[str, str | None]]) -> _Span:
    """(colspan, rowspan) komórki; brak/niepoprawne atrybuty → 1."""
    return (parse_span(attrs, "colspan"), parse_span(attrs, "rowspan"))


def expand_cells(
    rows: Sequence[tuple[Sequence[str], Sequence[_Span]]], *, repeat_colspan: bool
) -> list[list[str]]:
    """Rozwiń colspan w prawo i rowspan w dół do siatki tekstów (szerokość = max wiersza).

    Nagłówek (`repeat_colspan=True`): tekst colspan>1 powtórzony w każdej kolumnie — to ta
    sama nazwa grupy nad kilkoma kolumnami. Wiersze tbody (`repeat_colspan=False`): tekst
    tylko w pierwszej kolumnie, pozostałe "". rowspan>1: tekst powtórzony w kolejnych
    wierszach w tej samej kolumnie. `rows` to pary (komórki, spany) — bez typu `_Row`.
    """
    placed: dict[tuple[int, int], str] = {}
    width = 0
    for r, (cells, spans) in enumerate(rows):
        column = 0
        for text, (colspan, rowspan) in zip(cells, spans, strict=True):
            while (r, column) in placed:
                column += 1
            for dr in range(rowspan):
                for dc in range(colspan):
                    filled = text if (repeat_colspan or dc == 0 or dr > 0) else ""
                    placed[(r + dr, column + dc)] = filled
            column += colspan
            width = max(width, column)
    return [[placed.get((r, column), "") for column in range(width)] for r in range(len(rows))]


def pad_grid(grid: list[list[str]], width: int) -> list[list[str]]:
    """Dopełnij każdy wiersz siatki do wspólnej szerokości pustymi komórkami."""
    return [row + [""] * (width - len(row)) for row in grid]


def column_label(grid: list[list[str]], column: int) -> str:
    """Ścieżka nagłówka kolumny: niepuste teksty z góry na dół, bez sąsiednich powtórzeń, " / "."""
    labels: list[str] = []
    for row in grid:
        text = row[column]
        if text and (not labels or labels[-1] != text):
            labels.append(text)
    return " / ".join(labels)


def linearize(
    header: Sequence[GridRow], body: Sequence[GridRow]
) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
    """Nazwy kolumn nagłówka (ścieżki " / ") i wiersze tbody rozwinięte do wspólnej szerokości."""
    header_grid = expand_cells([(row[0], row[2]) for row in header], repeat_colspan=True)
    body_grid = expand_cells([(row[0], row[2]) for row in body], repeat_colspan=False)
    width = max(
        len(header_grid[0]) if header_grid else 0,
        len(body_grid[0]) if body_grid else 0,
    )
    header_grid = pad_grid(header_grid, width)
    body_grid = pad_grid(body_grid, width)
    labels = tuple(column_label(header_grid, column) for column in range(width))
    return labels, tuple(tuple(row) for row in body_grid)
