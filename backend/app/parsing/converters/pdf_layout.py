"""Układ strony PDF w trybie text (kontrakt C7; 05 §8.3) — tabele, nagłówki, akapity."""

from __future__ import annotations

import re
import statistics
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

import pdfplumber
from pdfplumber.table import Table

from app.parsing.html import esc, table_html

_DIGIT = re.compile(r"\d")
_MIN_TABLE_ROWS = 2
_MIN_TABLE_COLS = 2
_MIN_TABLE_CELLS = 4
_MIN_TABLE_FILL = 0.25
_MIN_REPEAT_PAGES = 3  # poniżej nie ma z czego wyznaczyć powtarzalności
_MIN_REPEAT_COUNT = 2  # klucz musi wystąpić w strefie co najmniej na 2 stronach
_MIN_REPEAT_RATIO = 0.5  # i na co najmniej 50% stron
_TOP_ZONE = 0.08  # strefa nagłówka: top < 8% wysokości strony
_BOTTOM_ZONE = 0.92  # strefa stopki: bottom > 92% wysokości strony
_H2_RATIO = 1.6  # size >= 1.6 * median → <h2>
_H3_RATIO = 1.25  # size >= 1.25 * median → <h3>
_PARAGRAPH_GAP = 0.5  # odstęp > 0.5 wysokości poprzedniej linii → nowy akapit
_SPAN_EPS = 1.0  # tolerancja (pt) przy wyznaczaniu zasięgu scalonych komórek
_VALUE = re.compile(r"[-−—]?\s?\d[\d\s]*(?:[.,]\d+)?\s?[a-z%]?")  # noqa: RUF001 — minus z PDF
_HEADER_NUMBER = re.compile(r"(?:1[89]|20)\d\d(?:[/—-]\d+)?|\d+\s?=\s?\d*")
_LEADER = re.compile(r"\s*(?:\.\s?){3,}\s*")
_SPACED = re.compile(r"\b[^\W\d_](?: [^\W\d_]){2,}\b")


@dataclass(frozen=True)
class TextLine:
    """Linia tekstu strony (konwencja pdfplumber: top/bottom liczone od górnej krawędzi)."""

    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    size: float  # mediana rozmiaru czcionki znaków linii


def looks_like_table(rows: Sequence[Sequence[str | None]]) -> bool:
    """Prawdziwa tabela: ≥2 wiersze, ≥2 kolumny, ≥4 niepuste komórki, wypełnienie ≥25%."""
    if len(rows) < _MIN_TABLE_ROWS:
        return False
    width = max(len(row) for row in rows)
    if width < _MIN_TABLE_COLS:
        return False
    cells = sum(1 for row in rows for cell in row if cell is not None and cell.strip())
    return cells >= _MIN_TABLE_CELLS and cells / (len(rows) * width) >= _MIN_TABLE_FILL


def lost_numbers(rows: Sequence[Sequence[str | None]], words: Sequence[str]) -> int:
    """Ile tokenów z cyframi z obszaru tabeli nie trafiło do jej komórek.

    ``find_tables`` przy niepełnych liniach siatki zwraca ``None`` dla komórek z tekstem
    (rocznik GUS: 3214 z 51486 liczb na 99 stronach), a linie z bbox tabeli są pomijane.
    """
    in_cells = Counter(
        token
        for row in rows
        for cell in row
        if cell
        for token in cell.split()
        if _DIGIT.search(token)
    )
    on_page = Counter(word for word in words if _DIGIT.search(word))
    return sum((on_page - in_cells).values())


def is_value(cell: str | None) -> bool:
    """Komórka z liczbą; rok, baza indeksu i numer kadencji to raczej nagłówek niż dane."""
    text = (cell or "").strip()
    return bool(_VALUE.fullmatch(text)) and not _HEADER_NUMBER.fullmatch(text)


def _first_data_row(rows: Sequence[Sequence[str | None]]) -> int:
    """Indeks pierwszego wiersza z wartościami poza pierwszą kolumną; 0, gdy nagłówka nie ma."""
    for index, row in enumerate(rows):
        if sum(is_value(cell) for cell in row[1:]) >= 1:
            return index
    return 0


def join_label(parts: Sequence[str]) -> str:
    """Części nagłówka kolumny z góry na dół: bez powtórzeń, przeniesienia wyrazów sklejone."""
    out = ""
    for part in parts:
        text = " ".join(part.split())
        if not text or out.endswith(text):
            continue
        if out.endswith("-"):
            out = out[:-1] + text  # przeniesienie wyrazu
        elif out:
            out = f"{out} / {text}"
        else:
            out = text
    return out


def _span_grid(table: Table, rows: Sequence[Sequence[str | None]]) -> list[list[str]]:
    """Tekst komórek powielony na scalone kolumny i wiersze (zasięg z geometrii komórek)."""
    columns = sorted({cell[0] for row in table.rows for cell in row.cells if cell is not None})
    tops = [next(cell[1] for cell in row.cells if cell is not None) for row in table.rows]
    grid = [[""] * len(columns) for _ in rows]
    for r, row in enumerate(table.rows):
        for c, cell in enumerate(row.cells):
            if cell is None or not rows[r][c]:
                continue
            for r2 in range(r, len(rows)):
                if tops[r2] < cell[3] - _SPAN_EPS:
                    for c2 in range(c, len(columns)):
                        if columns[c2] < cell[2] - _SPAN_EPS:
                            grid[r2][c2] = str(rows[r][c])
    return grid


def _merge_cell(first: str, second: str) -> str:
    first, second = first.strip(), second.strip()
    if not second:
        return first
    if first.endswith("-"):
        return first[:-1] + second
    return f"{first} {second}".strip()


def _merge_row(first: Sequence[str], second: Sequence[str]) -> list[str]:
    return [_merge_cell(a, b) for a, b in zip(first, second, strict=True)]


def clean_cell(cell: str | None) -> str:
    """Komórka danych: bez wielokropków prowadzących i rozstrzelenia (``O G Ó Ł E M``)."""
    lines = (" ".join(_LEADER.sub(" ", line).split()) for line in (cell or "").splitlines())
    return " ".join(
        _SPACED.sub(lambda match: match.group(0).replace(" ", ""), line) for line in lines if line
    )


def _unfinished(label: str) -> bool:
    return label.endswith(("-", ","))


def _body_rows(rows: Sequence[Sequence[str | None]]) -> list[list[str]]:
    """Wiersze danych: opis rozbity na kilka wierszy siatki scalony z wierszem wartości.

    Tabele GUS nie mają linii poziomych, więc siatka tnie opis tak, że wartości trafiają na środek:
    ``[ "Rolnictwo i ry-", "" ]``, ``[ "", "145,1" ]``, ``[ "bactwo", "" ]``.
    """
    out: list[list[str]] = []
    pending: list[str] | None = None
    open_label = False  # poprzedni wiersz wartości miał opis tylko z wiersza nad nim
    for raw in rows:
        row = [clean_cell(cell) for cell in raw]
        if not any(row):
            continue
        if not any(row[1:-1]):  # wiersz bez wartości: opis, ciąg dalszy albo nagłówek grupy
            if out and (open_label or _unfinished(out[-1][0])) and row[0]:
                out[-1] = _merge_row(out[-1], row)
                open_label = _unfinished(out[-1][0])
            elif pending is not None and _unfinished(pending[0]):
                pending = _merge_row(pending, row)
            else:
                if pending is not None:
                    out.append(pending)
                pending = row
                open_label = False
            continue
        if pending is not None:
            joins = (
                not row[0]
                or _unfinished(pending[0])
                or (row[0][0].islower() and not pending[0].endswith(":"))
            )
            if joins:
                open_label = not row[0]
                row = _merge_row(pending, row)
            else:
                out.append(pending)
                open_label = False
            pending = None
        else:
            open_label = False
        out.append(row)
    if pending is not None:
        out.append(pending)
    return out


def structured_table(table: Table) -> tuple[list[list[str]], int]:
    """Wiersze tabeli i liczba wierszy nagłówka: nagłówek wielopoziomowy spłaszczony do jednego."""
    rows = table.extract()
    plain = [["" if cell is None else cell for cell in row] for row in rows]
    start = _first_data_row(rows)
    if start == 0:
        return plain, 1
    grid = _span_grid(table, rows)
    width = len(rows[0])
    header = [join_label([grid[r][c] for r in range(start)]) for c in range(width)]
    return [header, *_body_rows(rows[start:])], 1


def page_lines(page: pdfplumber.page.Page) -> list[TextLine]:
    """Linie tekstu strony; puste pomijane, size = mediana rozmiarów czcionek znaków."""
    out: list[TextLine] = []
    for line in page.extract_text_lines(return_chars=True):
        text = str(line["text"])
        if not text.strip():
            continue
        sizes = [float(char["size"]) for char in line.get("chars") or []]
        out.append(
            TextLine(
                text=text,
                x0=float(line["x0"]),
                top=float(line["top"]),
                x1=float(line["x1"]),
                bottom=float(line["bottom"]),
                size=float(statistics.median(sizes)) if sizes else 0.0,
            )
        )
    return out


def line_key(text: str) -> str:
    """Klucz porównywania linii: biały znak zredukowany, cyfry → '#', małe litery."""
    return re.sub(r"\d+", "#", " ".join(text.split())).lower()


def repeated_lines(pages: Sequence[tuple[float, Sequence[TextLine]]]) -> frozenset[str]:
    """Klucze linii powtarzających się w strefach górnej/dolnej na ≥2 stronach i ≥50% stron."""
    if len(pages) < _MIN_REPEAT_PAGES:
        return frozenset()
    counts: Counter[str] = Counter()
    for height, lines in pages:
        counts.update(
            {  # zbiór: liczą się strony z kluczem w strefie, nie łączna liczba wystąpień
                line_key(line.text)
                for line in lines
                if line.top < _TOP_ZONE * height or line.bottom > _BOTTOM_ZONE * height
            }
        )
    return frozenset(
        key
        for key, count in counts.items()
        if count >= _MIN_REPEAT_COUNT and count / len(pages) >= _MIN_REPEAT_RATIO
    )


def _bbox_str(bbox: tuple[float, float, float, float]) -> str:
    """Bbox jako cztery liczby całkowite rozdzielone przecinkiem (punkty, top od góry)."""
    return f"{round(bbox[0])},{round(bbox[1])},{round(bbox[2])},{round(bbox[3])}"


def _heading_tag(size: float, median: float) -> str | None:
    """Nagłówek z rozmiaru czcionki względem mediany strony; None = zwykła linia."""
    if median <= 0:
        return None
    if size >= _H2_RATIO * median:
        return "h2"
    if size >= _H3_RATIO * median:
        return "h3"
    return None


def render_text_page(
    page: pdfplumber.page.Page, lines: Sequence[TextLine], drop: frozenset[str]
) -> str:
    """Wnętrze sekcji strony text: tabele z thead, nagłówki h2/h3, akapity z data-bbox."""

    def _inside(line: TextLine, bbox: tuple[float, float, float, float]) -> bool:
        cx, cy = (line.x0 + line.x1) / 2, (line.top + line.bottom) / 2
        return bbox[0] <= cx <= bbox[2] and bbox[1] <= cy <= bbox[3]

    def _complete(table: Table) -> bool:
        """Prawdziwa tabela zawierająca każdą liczbę linii, które by zastąpiła."""
        rows = table.extract()
        if not looks_like_table(rows):
            return False
        words = [w for line in lines if _inside(line, table.bbox) for w in line.text.split()]
        return lost_numbers(rows, words) == 0

    tables = [table for table in page.find_tables() if _complete(table)]
    bboxes = [table.bbox for table in tables]
    # mediana z WSZYSTKICH linii strony (kontrakt C7 krok 3), przed odfiltrowaniem tabel i drop
    median = statistics.median(line.size for line in lines) if lines else 0.0

    def _in_table(line: TextLine) -> bool:
        return any(_inside(line, bb) for bb in bboxes)

    kept = [line for line in lines if not _in_table(line) and line_key(line.text) not in drop]

    blocks: list[tuple[float, str]] = []
    for table in tables:
        cells, header_rows = structured_table(table)
        blocks.append(
            (
                float(table.bbox[1]),
                table_html(cells, header_rows=header_rows, bbox=_bbox_str(table.bbox)),
            )
        )

    def _flush(paragraph: list[TextLine]) -> None:
        if not paragraph:
            return
        bbox = (
            min(line.x0 for line in paragraph),
            min(line.top for line in paragraph),
            max(line.x1 for line in paragraph),
            max(line.bottom for line in paragraph),
        )
        text = " ".join(line.text for line in paragraph)
        blocks.append((paragraph[0].top, f'<p data-bbox="{_bbox_str(bbox)}">{esc(text)}</p>'))

    paragraph: list[TextLine] = []
    prev: TextLine | None = None
    prev_heading = False
    for line in sorted(kept, key=lambda item: (item.top, item.x0)):
        tag = _heading_tag(line.size, median)
        if tag is not None:
            _flush(paragraph)
            paragraph = []
            blocks.append((line.top, f"<{tag}>{esc(line.text)}</{tag}>"))
        else:
            if (
                paragraph
                and prev is not None
                and (
                    prev_heading
                    or line.top - prev.bottom > _PARAGRAPH_GAP * (prev.bottom - prev.top)
                )
            ):
                _flush(paragraph)
                paragraph = []
            paragraph.append(line)
        prev = line
        prev_heading = tag is not None
    _flush(paragraph)

    blocks.sort(key=lambda block: block[0])
    return "".join(text for _, text in blocks)
