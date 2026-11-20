"""Ciąg dalszy tabeli bez nagłówka i tytułu — doklejenie nagłówka i tytułu poprzedniej tabeli.

OCR rozpoznaje stronę po stronie, więc tabela przełamana na kolejną stronę (dokumenty prawne
bez powtórzonego nagłówka, „(dok.)” bez tytułu) albo rozcięta wierszem-sekcją („UCZNIOWIE I
STUDENCI” jako osobny akapit) przychodzi jako nowa tabela: pierwszy wiersz danych awansuje na
nagłówek („Szkoły podstawowe | 240382 | 279550…”), a chunk nie ma tytułu, więc wyszukiwanie go
nie znajduje, a model nie wie, czego dotyczą liczby. Tabela jest ciągiem dalszym poprzedniej,
gdy: nie ma własnego tytułu, jej pierwszy wiersz to dane (albo pusty / numeracja kolumn), ma
tę samą szerokość siatki, a między nimi stoją tylko krótkie akapity (stopki, nagłówek strony).
Wtedy dostaje nagłówek (thead) i tytuł poprzedniej, a krótkie akapity z tej samej strony
(wiersze-sekcje) wchodzą do niej jako wiersze etykiet.
"""

import html
import re
from collections.abc import Callable, Sequence
from dataclasses import replace

from app.domain.chunking.tables import caps_title, table_caption, table_lead
from app.domain.chunking.types import Block

_HEAD_FILL = 0.5  # nagłówek kolumn: wypełniona co najmniej połowa komórek
_GAP_MAX = 100  # dłuższy akapit między tabelami to treść — następna tabela jest osobna
_LOOKBACK = 12  # tyle bloków wstecz szukamy poprzedniej tabeli
_ROW = re.compile(r"<tr\b[^>]*>.*?</tr>", re.S | re.I)
_CELL = re.compile(r"<t([hd])\b([^>]*)>(.*?)</t[hd]>", re.S | re.I)
_SPAN = re.compile(r'colspan\s*=\s*"?(\d+)', re.I)
_TAG = re.compile(r"<[^>]+>")
_THEAD = re.compile(r"<thead\b[^>]*>(.*?)</thead>", re.S | re.I)
_TBODY = re.compile(r"<tbody\b[^>]*>(.*?)</tbody>", re.S | re.I)
_NUMBER = re.compile(r"[\d\s.,()%\-\u2013\u2212+]*\d[\d\s.,()%\-\u2013\u2212+]*")
_YEAR = re.compile(r"(19|20)\d\d(\s*[/\-\u2013]\s*\d{2,4})?\s*[a-z*]?")
_SECTION = re.compile(r"[^\d]+")  # wiersz-sekcja: krótki tekst bez cyfr

Reparse = Callable[[str], list[Block]]


def _cells(row_html: str) -> list[tuple[str, int]]:
    out = []
    for _kind, attrs, inner in _CELL.findall(row_html):
        span = _SPAN.search(attrs)
        out.append(
            (
                " ".join(html.unescape(_TAG.sub(" ", inner)).split()),
                int(span.group(1)) if span else 1,
            )
        )
    return out


def _width(table_html: str) -> int:
    return max((sum(s for _, s in _cells(r)) for r in _ROW.findall(table_html)), default=0)


def _first_row(table_html: str) -> list[str]:
    rows = _ROW.findall(table_html)
    return [t for t, _ in _cells(rows[0])] if rows else []


def _data_like(cells: Sequence[str]) -> bool:
    """Pierwszy wiersz to dane, nie nagłówek.

    Pusty, numeracja kolumn „1 2 3 …” albo co najmniej 2 liczby niebędące latami.
    """
    filled = [c for c in cells if c]
    if not filled:
        return True
    if [c for c in cells] == [str(i) for i in range(1, len(cells) + 1)]:
        return True
    numbers = [c for c in filled if _NUMBER.fullmatch(c) and not _YEAR.fullmatch(c)]
    return len(numbers) >= 2  # noqa: PLR2004


def _column_numbers(cells: Sequence[str]) -> bool:
    return bool(cells) and list(cells) == [str(i) for i in range(1, len(cells) + 1)]


def _page(block: Block) -> int | None:
    return block.positions[0][0] if block.positions else None


def _previous_table(blocks: Sequence[Block], i: int) -> int | None:
    """Indeks poprzedniej tabeli, gdy między nią a ``i`` nie ma nagłówka ani tytułu tabeli."""
    for j in range(i - 1, max(-1, i - 1 - _LOOKBACK), -1):
        b = blocks[j]
        if b.kind == "table":
            return j
        if b.kind == "heading":
            return None
        if b.kind == "paragraph" and table_caption([b]):
            return None
    return None


def _gap_ok(blocks: Sequence[Block], j: int, i: int) -> bool:
    """Między tabelami tylko akapity i listy, krótkie na stronie ``i`` (całe, gdy ta sama)."""
    page = _page(blocks[i])
    for b in blocks[j + 1 : i]:
        if b.kind not in ("paragraph", "list"):
            return False
        if (_page(b) == page or _page(blocks[j]) == page) and len(b.text) > _GAP_MAX:
            return False
    return True


def _section_rows(
    blocks: Sequence[Block], j: int, i: int, width: int
) -> tuple[list[str], set[int]]:
    """Krótkie akapity bez cyfr między tabelami na tej samej stronie — wiersze-sekcje."""
    if _page(blocks[j]) != _page(blocks[i]):
        return [], set()
    rows, used = [], set()
    for k in range(j + 1, i):
        text = " ".join(blocks[k].text.split())
        if blocks[k].kind == "paragraph" and text and _SECTION.fullmatch(text):
            rows.append(f'<tr><td colspan="{width}">{html.escape(text)}</td></tr>')
            used.add(k)
    return rows, used


def _real_head(table_html: str) -> str | None:
    """Wnętrze thead, gdy to nagłówek kolumn: kolumny danych wypełnione co najmniej w połowie.

    Kolumny danych to komórki bez pierwszej (etykieta PL) i ostatniej (etykieta EN), gdy są
    co najmniej 3. Thead tabeli-sekcji „Przestępstwa stwierdzone…: | | | Crimes…” to etykieta
    wiersza — kolumny danych puste. Wiersz danych awansowany na nagłówek też się nie liczy.
    """
    head = _THEAD.search(table_html)
    if head is None:
        return None
    for row in _ROW.findall(head.group(1)):
        cells = [t for t, _ in _cells(row)]
        middle = cells[1:-1] if len(cells) >= 3 else cells[1:]  # noqa: PLR2004
        filled = [c for c in middle if c]
        if filled and len(filled) >= _HEAD_FILL * len(middle) and not _data_like(cells):
            return head.group(1)
    return None


def _head_source(blocks: Sequence[Block], j: int, width: int) -> str | None:
    """Nagłówek kolumn dla ciągu dalszego: z tabeli ``j`` albo wstecz po łańcuchu tabel tej strony.

    Strona „Województwo na tle kraju”: tabela z samym nagłówkiem (WYSZCZEGÓLNIENIE | Polska |
    Województwo…), pod nią tabele-sekcje z etykietą w thead — nagłówek jest w pierwszej.
    """
    k: int | None = j
    while k is not None:
        head = _real_head(blocks[k].html)
        if head is not None:
            return head if _width(blocks[k].html) == width else None
        prev = _previous_table(blocks, k)
        if prev is None or _page(blocks[prev]) != _page(blocks[k]) or not _gap_ok(blocks, prev, k):
            return None
        k = prev
    return None


def _joined_html(head: str, cur: Block, section_rows: list[str]) -> str:
    own_head = _THEAD.search(cur.html)
    body = _TBODY.search(cur.html)
    if body is None and own_head is None:
        rows = _ROW.findall(cur.html)
    else:
        rows = _ROW.findall(own_head.group(1)) if own_head else []
        rows += _ROW.findall(body.group(1)) if body else _ROW.findall(_THEAD.sub("", cur.html))
    kept = []
    for r in rows:
        cells = [t for t, _ in _cells(r)]
        if not any(cells) or _column_numbers(cells):
            continue
        kept.append(re.sub(r"<(/?)th\b", r"<\1td", r, flags=re.I))
    thead = f"<thead>{head}</thead>"
    return "<table>" + thead + "<tbody>" + "".join(section_rows + kept) + "</tbody></table>"


def _years_only(cells: Sequence[str]) -> bool:
    filled = [c for c in cells if c]
    years = all(_YEAR.fullmatch(c) for c in filled)
    return len(filled) >= 2 and years and bool(cells[0])  # noqa: PLR2004


def _side_by_side(prev: Block, cur: Block) -> str:
    """Szeroka tabela rozcięta na dwie (rocznik międzynarodowy: lata 2000-2012 | 2013-2020).

    Prawa część ma w nagłówku same lata i tyle samo wierszy; jej komórki idą na koniec
    wierszy lewej.
    """
    left, right = _ROW.findall(prev.html), _ROW.findall(cur.html)
    rows = []
    for a, b in zip(left, right, strict=True):
        inner = re.sub(r"^<tr\b[^>]*>|</tr>$", "", b.strip(), flags=re.I)
        rows.append(re.sub(r"</tr>\s*$", "", a.strip(), flags=re.I) + inner + "</tr>")
    head = _THEAD.search(prev.html)
    n_head = len(_ROW.findall(head.group(1))) if head else 0
    return (
        "<table><thead>"
        + "".join(rows[:n_head])
        + "</thead><tbody>"
        + "".join(rows[n_head:])
        + "</tbody></table>"
    )


def join_continued_tables(blocks: list[Block], reparse: Reparse) -> list[Block]:
    """Tabele-ciągi dalsze dostają nagłówek i tytuł poprzedniej tabeli (zob. docstring modułu)."""
    out = list(blocks)
    drop: set[int] = set()
    titles: dict[int, str] = {}
    for i, cur in enumerate(out):
        if cur.kind != "table" or cur.table is None or cur.table.title:
            continue
        j = _previous_table(out, i)
        if j is None or out[j].table is None or j in drop:
            continue
        prev = out[j]
        prev_title = prev.table.title if prev.table is not None else ""
        pi, pj = _page(cur), _page(prev)
        if pi is None or pj is None or not 0 <= pi - pj <= 1:
            continue
        if table_lead(out[i - 1], out[:i]):
            continue
        first = _first_row(cur.html)
        if (
            pi == pj
            and _years_only(first)
            and len(_ROW.findall(prev.html)) == len(_ROW.findall(cur.html))
            and _gap_ok(out, j, i)
        ):
            parsed = [b for b in reparse(_side_by_side(prev, cur)) if b.kind == "table"]
            if len(parsed) == 1 and parsed[0].table is not None:
                out[j] = replace(
                    prev,
                    text=parsed[0].text,
                    html=parsed[0].html,
                    table=replace(parsed[0].table, title=prev_title),
                )
                drop.add(i)
            continue
        if not _data_like(first):
            continue
        width = _width(prev.html)
        if width < 2 or width != _width(cur.html) or not _gap_ok(out, j, i):  # noqa: PLR2004
            continue
        title = titles.get(j) or prev_title
        if not title and j:
            title = table_lead(out[j - 1], out[:j]) or caps_title(out[j - 1])
        head = _head_source(out, j, width)
        if head is None:
            continue
        rows, used = _section_rows(out, j, i, width)
        parsed = [b for b in reparse(_joined_html(head, cur, rows)) if b.kind == "table"]
        if len(parsed) != 1 or parsed[0].table is None:
            continue
        table = replace(parsed[0].table, title=title)
        out[i] = replace(
            cur,
            text=parsed[0].text,
            html=parsed[0].html,
            heading_path=prev.heading_path,
            table=table,
        )
        titles[i] = title
        drop |= used
    return [b for k, b in enumerate(out) if k not in drop]
