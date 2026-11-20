"""Rok w osobnej komórce za etykietą wiersza, gdy nagłówek ma boczek o jedną kolumnę węższy.

Rozpoznanie struktury tabel (OCR skanów, tabele PDF) często daje wiersz
``<td>OGÓŁEM</td><td>2008</td><td>31109</td>…`` (albo ``<td></td><td>2008</td>…``) pod
nagłówkiem ``WYSZCZEGÓLNIENIE | Małżeństwa ogółem | …``, w którym boczek ma jedną kolumnę.
Rok stoi wtedy pod nazwą pierwszej kolumny wartości, a każda wartość pod nazwą kolejnej:
model czyta „zawarto 2008 małżeństw”, a rekordy przypisują wartości złym kolumnom.

`merge_period_cells` dokleja taki rok do etykiety wiersza (``OGÓŁEM 2008``), więc wartości
wracają pod właściwe nagłówki; brakująca w wierszu ostatnia wartość zostaje pusta.
Czysta funkcja na wierszach z `blocks.py` (komórki, ``<tr>``, spany).
"""

import re
from collections.abc import Sequence
from html import escape

from app.parsing.table_grid import GridRow, expand_cells
from app.parsing.table_structure import SUBORDINATE

# Rok okresu: 1950-2030, z odnośnikiem („2020b”, „2015*”). Liczby spoza zakresu
# (1809, 2050) w kolumnach wartości to zwykle dane, nie lata.
_PERIOD = re.compile(r"^(19[5-9]\d|20[0-2]\d|2030)\s*[a-z*]?\)?$")
# Nagłówek kolumny, w której rok jest na swoim miejscu: okres, lata, sam rok.
_PERIOD_HEAD = re.compile(
    r"(?i)\b(rok\w*|lat|lata|years?|okres\w*|periods?|miesi\w*|months?|kwarta\w*|quarters?)\b"
    r"|\b(1[89]|20)\d\d\b"
)
_MIN_PERIOD_ROWS = 2  # pojedynczy „rok” w kolumnie to raczej wartość
_LETTER = re.compile(r"[^\W\d_]")
_VALUE = re.compile(r"^[-\u2013\u2212]?\s*\d[\d\s\u00a0]*([.,]\d+)?\s*[a-z*%]?$")
_CELL_HTML = re.compile(r"<t([dh])\b([^>]*)>(.*?)</t\1\s*>", re.S | re.I)
_TR_OPEN = re.compile(r"^\s*<tr\b[^>]*>", re.I)
_TRAILING_YEAR = re.compile(r"\s*\b(19|20)\d\d\s*[a-z*]?$")
_ROWSPAN = re.compile(r"""\s+rowspan\s*=\s*["']?\d*["']?""", re.I)


def _starts(
    spans: Sequence[tuple[int, int]], row: int, occupied: set[tuple[int, int]]
) -> list[int]:
    """Kolumna startowa każdej komórki wiersza; zajmuje pola w ``occupied`` (rowspan w dół)."""
    column = 0
    starts: list[int] = []
    for colspan, rowspan in spans:
        while (row, column) in occupied:
            column += 1
        for dr in range(rowspan):
            for dc in range(colspan):
                occupied.add((row + dr, column + dc))
        starts.append(column)
        column += colspan
    return starts


def _header_at(head: Sequence[GridRow], column: int) -> str:
    grid = expand_cells([(cells, spans) for cells, _, spans in head], repeat_colspan=True)
    names = [row[column] for row in grid if column < len(row) and row[column]]
    return " ".join(dict.fromkeys(names))


def _period_index(  # noqa: PLR0913
    cells: Sequence[str],
    spans: Sequence[tuple[int, int]],
    starts: list[int],
    stub: int,
    *,
    all_years: bool,
    lead: int = 0,
) -> int | None:
    """Indeks komórki-roku w kolumnie ``stub`` tuż za własną etykietą wiersza; inaczej None.

    Gdy w kolumnie ``stub`` tabeli są też inne liczby (OCR raz skleił rok z etykietą, raz nie),
    sklejamy tylko wiersze z pustą etykietą — pusty boczek i rok przed wartościami są jednoznaczne.
    """
    for i, column in enumerate(starts):
        if column != stub:
            continue
        label = i - 1
        if (
            label < 0
            or spans[i] != (1, 1)
            or spans[label][1] != 1
            or starts[label] + spans[label][0] != stub
            or not _PERIOD.match(cells[i].strip())
            or (not all_years and cells[label].strip())
            or any(_VALUE.match(cells[k].strip()) for k in range(i) if starts[k] >= lead)
            or not any(_VALUE.match(cell.strip()) for cell in cells[i + 1 :])
        ):
            return None
        return i
    return None


_WRAP_HYPHEN = re.compile(r"[^\W\d_]-$")  # „opty-”, nie „ - ” ani „2015-”
_LEADERS = re.compile(r"…|\.{3,}")  # kropki wiodące GUS kończą etykietę boczka
_PL_CHARS = re.compile(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")  # wiersz-tłumaczenie EN nie jest początkiem nazwy
_CONTINUES = re.compile(r"(i|oraz|lub|albo|w|we|z|ze|na|do|dla|od|po|przez|pod|nad|bez)\s")
_ORDINAL_HEAD = re.compile(r"(?i)^(lp|l\.\s?p|nr|no)\.?$")


def _wrap_join(name: str, part: str) -> str | None:
    """Nazwa z częścią z następnego wiersza, gdy ta część ją dokończa: przeniesienie wyrazu
    („elek-” + „tryczną”) albo ciąg od spójnika lub przyimka („… ściekami” + „i odpadami”).

    Nie: tłumaczenie EN z małej litery („manufacture of furniture”) ani następna pozycja
    („Industry” + „górnictwo”).
    """
    if not part[:1].islower() or SUBORDINATE.match(part):
        return None
    if _WRAP_HYPHEN.search(name):
        return name[:-1] + part
    return f"{name} {part}" if _CONTINUES.match(part) else None


def _group_names(body: Sequence[GridRow], found: Sequence[int | None]) -> dict[int, str]:
    """Pełna nazwa grupy dla wierszy, na które rozpisano jej części (rok w każdym wierszu).

    Rocznik Przemysłu 2025 (OCR): ``Wytwarzanie i zaopatrywanie w energię elek- | 2010 | …``,
    ``tryczną, gaz, parę wodną i gorącą wodę | 2015 | …``, dalej puste etykiety z latami.
    """
    out: dict[int, str] = {}
    name, parts = "", list[int]()
    for r, ((cells, _, _), i) in enumerate(zip(body, found, strict=True)):
        own = _TRAILING_YEAR.sub("", cells[i - 1].strip()) if i is not None else ""
        if len(cells) < _MIN_PERIOD_ROWS or i is None:
            name, parts = "", []
            continue
        if not own:
            continue
        joined = _wrap_join(name, own) if name else None
        if joined is None:
            name, parts = own, [r]
            continue
        name = joined
        parts.append(r)
        out.update(dict.fromkeys(parts, name))
    return out


def _merged_html(
    tr: str, label: int, year: str, section: str = "", *, replace: bool = False
) -> str | None:
    """``<tr>`` bez komórki-roku, z rokiem doklejonym do etykiety; None, gdy HTML nie pasuje.

    Pusta etykieta dostaje etykietę sekcji z wiersza wyżej (``section``) — samo „2008” w
    tabeli z sekcjami OGÓŁEM / Miasta / Wieś nie mówi, do której sekcji należy wiersz.
    """
    raw = list(_CELL_HTML.finditer(tr))
    opening = _TR_OPEN.match(tr)
    if len(raw) <= label + 1 or opening is None:
        return None
    parts = [m.group(0) for m in raw]
    tag, attrs, inner = raw[label].group(1), raw[label].group(2), raw[label].group(3)
    if inner.strip() and not replace:
        joined = f"{inner} {escape(year)}"
    else:  # pusta etykieta albo część nazwy przełamanej na wiersze lat — pełna nazwa grupy
        joined = escape(f"{section} {year}".strip())
    parts[label] = f"<t{tag}{attrs}>{joined}</t{tag}>"
    del parts[label + 1]
    return opening.group(0) + "".join(parts) + "</tr>"


def merge_period_cells(head: Sequence[GridRow], body: Sequence[GridRow]) -> list[GridRow]:
    """Wiersze ``body`` z rokiem doklejonym do etykiety tam, gdzie rok wypchnął wartości.

    Warunki: boczek nagłówka ma szerokość ``s`` (colspan pierwszej komórki), nagłówek kolumny
    ``s`` to nazwa wartości (litery, nie okres ani rok), w kolumnie ``s`` tabeli stoją
    wyłącznie lata (co najmniej dwa wiersze — inaczej to kolumna wartości, w której zdarza się
    liczba wyglądająca jak rok, np. 1998 zgonów), a wiersz ma tam rok tuż za własną etykietą
    (bez liczb przed nim) i liczby za nim. Pozostałe wiersze bez zmian.
    """
    if not head or not body or not head[0][2]:
        return list(body)
    stub = head[0][2][0][0]
    lead = 0  # szerokość kolumny porządkowej („Lp.”) przed opisem — jej liczby to nie wartości
    if _ORDINAL_HEAD.match(head[0][0][0].strip() if head[0][0] else "") and len(head[0][2]) > 1:
        lead, stub = stub, stub + head[0][2][1][0]
    name = _header_at(head, stub)
    if not name or not _LETTER.search(name) or _PERIOD_HEAD.search(name):
        return list(body)
    original = list(body)
    body = _expand_stub(body, stub)
    occupied: set[tuple[int, int]] = set()
    starts = [_starts(spans, r, occupied) for r, (_, _, spans) in enumerate(body)]
    column = [
        cells[k].strip()
        for (cells, _, _), row_starts in zip(body, starts, strict=True)
        for k, c in enumerate(row_starts)
        if c == stub and cells[k].strip()
    ]
    years = sum(bool(_PERIOD.match(x)) for x in column)
    if years < _MIN_PERIOD_ROWS:
        return original
    all_years = years == len(column)
    found = [
        _period_index(cells, spans, row_starts, stub, all_years=all_years, lead=lead)
        for (cells, _, spans), row_starts in zip(body, starts, strict=True)
    ]
    full = _group_names(body, found)
    out: list[GridRow] = []
    merged = False
    section = ""  # ostatnia niepusta etykieta wiersza (bez roku) — dla wierszy z pustą etykietą
    for r, ((cells, tr, spans), i) in enumerate(zip(body, found, strict=True)):
        own = cells[i - 1].strip() if i is not None else (cells[0].strip() if cells else "")
        if len(cells) < _MIN_PERIOD_ROWS:
            section = ""  # wiersz-sekcja na całą szerokość („W LICZBACH BEZWZGLĘDNYCH”)
        elif own:
            section = full.get(r) or _TRAILING_YEAR.sub("", own)
        html = (
            None
            if i is None
            else _merged_html(tr, i - 1, cells[i].strip(), section, replace=r in full)
        )
        if i is None or html is None:
            out.append((cells, tr, spans))
            continue
        own_label = section if r in full else cells[i - 1].strip()
        label = " ".join(x for x in (own_label or section, cells[i].strip()) if x)
        new_cells = (*cells[: i - 1], label, *cells[i + 1 :])
        out.append((tuple(new_cells), html, tuple((*spans[:i], *spans[i + 1 :]))))
        merged = True
    return out if merged else original


_StubCell = tuple[int, str, tuple[int, int], str]  # kolumna, tekst, (colspan, rowspan), HTML


def _expand_stub(body: Sequence[GridRow], stub: int) -> list[GridRow]:
    """Etykiety boczku z rowspan (``<td rowspan="4">Polish</td>`` nad latami) w każdym wierszu.

    Rok ma się wtedy do czego dokleić. Gdy HTML wiersza nie pasuje do komórek — bez zmian.
    """
    occupied: set[tuple[int, int]] = set()
    starts = [_starts(spans, r, occupied) for r, (_, _, spans) in enumerate(body)]
    raws = [[m.group(0) for m in _CELL_HTML.finditer(tr)] for _, tr, _ in body]
    if any(len(raw) != len(cells) for raw, (cells, _, _) in zip(raws, body, strict=True)):
        return list(body)
    rows: list[tuple[list[_StubCell], str]] = [
        (list(zip(row_starts, cells, spans, raw, strict=True)), tr)
        for (cells, tr, spans), row_starts, raw in zip(body, starts, raws, strict=True)
    ]
    changed = False
    for r, (cells, _) in enumerate(rows):
        for k, (col, text, (colspan, rowspan), raw) in enumerate(cells):
            if col >= stub or rowspan == 1:
                continue
            single = _ROWSPAN.sub("", raw[: raw.index(">")]) + raw[raw.index(">") :]
            cells[k] = (col, text, (colspan, 1), single)
            for below in rows[r + 1 : r + rowspan]:
                below[0].append((col, text, (colspan, 1), single))
                below[0].sort(key=lambda cell: cell[0])
            changed = True
    if not changed:
        return list(body)
    out: list[GridRow] = []
    for cells, tr in rows:
        opening = _TR_OPEN.match(tr)
        html = (opening.group(0) if opening else "<tr>") + "".join(c[3] for c in cells) + "</tr>"
        out.append((tuple(c[1] for c in cells), html, tuple(c[2] for c in cells)))
    return out


_LABEL_RUN = 2  # etykieta dwujęzyczna: „Mężczyźni” w jednym wierszu, „Males” w następnym


def fill_stub_labels(head: Sequence[GridRow], body: Sequence[GridRow]) -> list[GridRow]:
    """Pusta etykieta wiersza w boczku szerszym niż jedna kolumna dostaje etykietę grupy.

    DOCX (komórka scalona w pionie) i część PDF dają ``<td></td><td>2015</td><td>20512</td>…``
    pod wierszami ``Mężczyźni | 2005 …`` i ``Males | 2010 …``: po podziale tabeli na fragmenty
    wiersz 2015 nie mówi, czy to mężczyźni, czy ogółem. Etykieta grupy = ostatnie (najwyżej dwie)
    niepuste etykiety przed pustymi wierszami; wiersz na całą szerokość zeruje grupę.
    """
    if not head or not body or not head[0][2] or head[0][2][0][0] < _LABEL_RUN:
        return list(body)
    out: list[GridRow] = []
    run: list[str] = []
    filled = False
    after_empty = False
    for cells, tr, spans in body:
        own = cells[0].strip() if cells else ""
        if len(cells) < _MIN_PERIOD_ROWS:
            run, after_empty = [], False
        elif own:
            run = [own] if after_empty else [*run, own]
            after_empty = False
        elif run and any(_VALUE.match(c.strip()) for c in cells[1:]):
            label = " ".join(run[-_LABEL_RUN:])
            raw = list(_CELL_HTML.finditer(tr))
            opening = _TR_OPEN.match(tr)
            if raw and opening is not None and not _LETTER.search(raw[0].group(3)):
                first = raw[0]
                parts = [f"<t{first.group(1)}{first.group(2)}>{escape(label)}</t{first.group(1)}>"]
                html = opening.group(0) + "".join(parts + [m.group(0) for m in raw[1:]]) + "</tr>"
                out.append(((label, *cells[1:]), html, spans))
                filled = after_empty = True
                continue
        out.append((cells, tr, spans))
    return out if filled else list(body)


def _continuation(label: str, nxt: str, after: str) -> str | None:
    """Etykieta sklejona z przełamanej na dwa wiersze albo None, gdy to nie przełamanie.

    ``after``: etykieta wiersza za ``nxt``; z małej litery znaczy, że ``nxt`` to pierwszy z kilku
    podwierszy sekcji („Energia pierwotna ogółem”, „w TJ …”, „w % …”), a nie dokończenie nazwy.
    """
    if not nxt[:1].islower():
        return None
    if _WRAP_HYPHEN.search(label):
        return label[:-1] + nxt
    # „Miasta” + „w tym kobiety ……” to sekcja i podwiersz; „ischaemic heart disease” (EN pod
    # wierszem z danymi) + „choroby naczyń mózgowych …” to tłumaczenie i następna pozycja
    if SUBORDINATE.match(nxt) or after[:1].islower():
        return None
    if (
        label[-1:].islower()
        and _PL_CHARS.search(label)
        and not _LEADERS.search(label)
        and _LEADERS.search(nxt)
    ):
        return f"{label} {nxt}"
    return None


def join_wrapped_labels(body: Sequence[GridRow]) -> list[GridRow]:
    """Etykieta wiersza przełamana na dwa wiersze tabeli wraca do jednego wiersza.

    GUS (XLS, PDF) łamie długą nazwę: ``Produkcja komputerów, wyrobów elektronicznych i opty-``
    w wierszu bez liczb, a ``cznych ……`` z liczbami pod spodem. Wiersz bez liczb wyglądał jak
    sekcja i jego tekst trafiał do etykiet wszystkich dalszych wierszy tabeli („opty- /
    Produkcja mebli”), a model widział osobny wiersz „cznych”. Sklejane tylko przeniesienie
    wyrazu („opty-” + „cznych”) albo dokończenie z małej litery z kropkami wiodącymi
    („…surowców” + „niemetalicznych ……”). Pusty po sklejeniu wiersz zostaje jako pusty, żeby
    liczba wierszy się nie zmieniała. Bez sklejania: podwiersze sekcji („w tym kobiety”, kilka
    wierszy z małej litery pod rząd) i tłumaczenia EN.
    """
    out = list(body)
    changed = False
    for i in range(len(out) - 1):
        cells, _tr, spans = out[i]
        nxt_cells, nxt_tr, nxt_spans = out[i + 1]
        if not cells or not nxt_cells or any(c.strip() for c in cells[1:]):
            continue
        label, own = cells[0].strip(), nxt_cells[0].strip()
        if not label or not any(_VALUE.match(c.strip()) for c in nxt_cells[1:]):
            continue
        after = next((r[0][0].strip() for r in out[i + 2 :] if r[0] and r[0][0].strip()), "")
        joined = _continuation(label, own, after)
        raw = list(_CELL_HTML.finditer(nxt_tr))
        opening = _TR_OPEN.match(nxt_tr)
        if joined is None or not raw or opening is None:
            continue
        first = raw[0]
        cell = f"<t{first.group(1)}{first.group(2)}>{escape(joined)}</t{first.group(1)}>"
        html = opening.group(0) + cell + "".join(m.group(0) for m in raw[1:]) + "</tr>"
        out[i + 1] = ((joined, *nxt_cells[1:]), html, nxt_spans)
        out[i] = (tuple("" for _ in cells), "<tr></tr>", spans)
        changed = True
    return out if changed else list(body)


def repair_body(head: Sequence[GridRow], body: Sequence[GridRow]) -> list[GridRow]:
    """Naprawy wierszy tabeli przed linearyzacją: przełamane etykiety, rok w osobnej komórce,
    puste etykiety grup."""
    return fill_stub_labels(head, merge_period_cells(head, join_wrapped_labels(body)))
