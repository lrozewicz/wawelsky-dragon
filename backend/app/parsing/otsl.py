"""Konwerter OTSL (Xiaomi-OCR-0) na tabele HTML z colspan/rowspan (CONTRACT WP E5-H4a §1).

OTSL (Open Table Structure Language) to reprezentacja tabel w wyjściu modelu OCR: tokeny
``<fcel>``/``<ecel>``/``<ched>``/``<rhed>``/``<srow>`` rozdzielają komórki, ``<nl>`` kończy wiersz,
a ``<lcel>``/``<ucel>``/``<xcel>`` opisują scalenia (colspan/rowspan). Moduł zamienia segmenty OTSL
w tekście (Markdown z modelu) na ``<table>``, a tekst poza segmentami zostawia bez zmian.
"""

from __future__ import annotations

import html
import re

_DataCell = tuple[str, str]  # (typ tokenu OTSL, treść komórki)
_Row = list[_DataCell]

# Tokeny OTSL: początki komórek, wskaźniki scalenia i koniec wiersza.
_TOKEN = re.compile(r"<(fcel|ecel|lcel|ucel|xcel|nl|ched|rhed|srow)>")

# Komórki danych emitowane jako <th>/<td>; pozostałe typy to wskaźniki scalenia.
_DATA_TOKENS = frozenset({"fcel", "ecel", "ched", "rhed", "srow"})
_COLSPAN_TOKENS = frozenset({"lcel", "xcel"})
_ROWSPAN_TOKENS = frozenset({"ucel", "xcel"})
_HEADER_TOKENS = frozenset({"ched", "rhed"})

_TRUNCATED_WARNING = "OTSL truncated: closed last row"
_EMPTY_WARNING = "OTSL segment without cells: left as text"

# Minimalny colspan/rowspan wymagany do emisji atrybutu.
_MIN_SPAN = 2
# Poniżej dwóch wierszy nie ma czego dzielić na <thead>/<tbody> — wiersz idzie do <tbody> jako <td>.
_MIN_ROWS_FOR_HEADER = 2

_TABLE_START = "<table>"


def otsl_to_html(text: str) -> tuple[str, list[str]]:
    """Zamienia segmenty OTSL w tekście na tabele HTML, resztę tekstu zostawia bez zmian.

    Zwraca ``(tekst_z_tabelami, ostrzeżenia)``. Nigdy nie rzuca wyjątku: uszkodzone/obcięte OTSL
    domyka ostatni wiersz i zgłasza ostrzeżenie.
    """
    matches = list(_TOKEN.finditer(text))
    if not matches:
        return text, []
    out: list[str] = []
    warnings: list[str] = []
    pos = 0
    for group in _group_matches(text, matches):
        start, end, tail_truncated = _segment_span(text, group)
        rows, parse_truncated = _parse_rows(text[start:end])
        if not any(kind in _DATA_TOKENS for row in rows for kind, _ in row):
            out.append(text[pos:end])
            warnings.append(_EMPTY_WARNING)
            pos = end
            continue
        out.append(text[pos:start])
        out.append(_render_table(rows))
        pos = end
        if tail_truncated or parse_truncated:
            warnings.append(_TRUNCATED_WARNING)
    out.append(text[pos:])
    return "".join(out), warnings


def _group_matches(text: str, matches: list[re.Match[str]]) -> list[list[re.Match[str]]]:
    """Grupuje kolejne tokeny w segmenty; granicą segmentu (tabeli) jest linia pusta."""
    groups: list[list[re.Match[str]]] = []
    current: list[re.Match[str]] = []
    for match in matches:
        if current and "\n\n" in text[current[-1].end() : match.start()]:
            groups.append(current)
            current = []
        current.append(match)
    if current:
        groups.append(current)
    return groups


def _segment_span(text: str, group: list[re.Match[str]]) -> tuple[int, int, bool]:
    """Zwraca ``(start, end, truncated)`` segmentu; ``truncated`` = niepusty ogon po tokenach."""
    start = group[0].start()
    last_end = group[-1].end()
    boundary = text.find("\n\n", last_end)
    if boundary < 0:
        boundary = len(text)
    return start, boundary, bool(text[last_end:boundary].strip())


def _parse_rows(segment: str) -> tuple[list[_Row], bool]:
    """Rozbija segment OTSL na wiersze komórek; ``truncated`` = wiersz bez kończącego ``<nl>``."""
    parts = _TOKEN.split(segment)
    rows: list[_Row] = []
    row: _Row = []
    index = 1
    while index < len(parts):
        kind = parts[index]
        content = parts[index + 1] if index + 1 < len(parts) else ""
        if kind == "nl":
            rows.append(row)
            row = []
        else:
            row.append((kind, content.strip()))
        index += 2
    if row:
        rows.append(row)
        return rows, True
    return rows, False


def _colspan(row: _Row, x: int, width: int) -> int:
    """Colspan komórki w (wiersz dopełniony do ``width``)."""
    span = 1
    while x + span < width and row[x + span][0] in _COLSPAN_TOKENS:
        span += 1
    return span


def _rowspan(grid: list[_Row], x: int, y: int) -> int:
    """Rowspan komórki w (siatka dopełniona do prostokąta)."""
    span = 1
    while y + span < len(grid) and grid[y + span][x][0] in _ROWSPAN_TOKENS:
        span += 1
    return span


def _has_partial_colspan(row: _Row, width: int) -> bool:
    """Czy wiersz ma komórkę z colspan>1 węższą niż pełna szerokość (heurystyka H)."""
    for x, (kind, _) in enumerate(row):
        if kind in _DATA_TOKENS and _MIN_SPAN <= _colspan(row, x, width) < width:
            return True
    return False


def _header_rows(grid: list[_Row], width: int) -> set[int]:
    """Indeksy wierszy nagłówka: jawne ``ched``/``rhed`` albo heurystyka H."""
    explicit = {y for y, row in enumerate(grid) if any(t in _HEADER_TOKENS for t, _ in row)}
    if explicit:
        return explicit
    headers = {0}
    for y in range(len(grid) - 1):
        if y == 0 and _has_partial_colspan(grid[0], width):
            headers.add(y + 1)
        if any(t in _ROWSPAN_TOKENS for t, _ in grid[y + 1]):
            headers.add(y + 1)
    return headers


def _render_row(row: _Row, grid: list[_Row], y: int, width: int, tag: str) -> str:
    """Serializuje jeden wiersz; komórki zajęte przez scalenie pomija."""
    cells: list[str] = []
    for x in range(width):
        kind, content = row[x]
        if kind not in _DATA_TOKENS:
            continue
        attrs = ""
        colspan = _colspan(row, x, width)
        if colspan >= _MIN_SPAN:
            attrs += f' colspan="{colspan}"'
        rowspan = _rowspan(grid, x, y)
        if rowspan >= _MIN_SPAN:
            attrs += f' rowspan="{rowspan}"'
        cells.append(f"<{tag}{attrs}>{html.escape(content)}</{tag}>")
    return "<tr>" + "".join(cells) + "</tr>"


def _render_table(rows: list[_Row]) -> str:
    """Buduje ``<table>`` z podziałem na ``<thead>`` (nagłówki) i ``<tbody>``."""
    width = max(len(row) for row in rows)
    grid = [row + [("ecel", "")] * (width - len(row)) for row in rows]
    header = _header_rows(grid, width) if len(grid) >= _MIN_ROWS_FOR_HEADER else set()
    head = [y for y in range(len(grid)) if y in header]
    body = [y for y in range(len(grid)) if y not in header]
    parts = [_TABLE_START]
    if head:
        parts.append("<thead>")
        parts.extend(_render_row(grid[y], grid, y, width, "th") for y in head)
        parts.append("</thead>")
    if body:
        parts.append("<tbody>")
        parts.extend(_render_row(grid[y], grid, y, width, "td") for y in body)
        parts.append("</tbody>")
    parts.append("</table>")
    return "".join(parts)
