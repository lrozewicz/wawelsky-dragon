"""Układ strony PDF w trybie text (kontrakt C7; 05 §8.3) — tabele, nagłówki, akapity."""

from __future__ import annotations

import re
import statistics
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

import pdfplumber

from app.parsing.html import esc, table_html

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
    tables = [table for table in page.find_tables() if looks_like_table(table.extract())]
    bboxes = [table.bbox for table in tables]
    # mediana z WSZYSTKICH linii strony (kontrakt C7 krok 3), przed odfiltrowaniem tabel i drop
    median = statistics.median(line.size for line in lines) if lines else 0.0

    def _in_table(line: TextLine) -> bool:
        cx, cy = (line.x0 + line.x1) / 2, (line.top + line.bottom) / 2
        return any(bb[0] <= cx <= bb[2] and bb[1] <= cy <= bb[3] for bb in bboxes)

    kept = [line for line in lines if not _in_table(line) and line_key(line.text) not in drop]

    blocks: list[tuple[float, str]] = []
    for table in tables:
        rows = table.extract()
        cells = [["" if cell is None else cell for cell in row] for row in rows]
        blocks.append(
            (
                float(table.bbox[1]),
                table_html(cells, header_rows=1, bbox=_bbox_str(table.bbox)),
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
