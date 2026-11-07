"""Struktura tabeli z siatki komórek: tytuł, nagłówek wielopoziomowy, wiersze danych.

Wszystkie formaty (CSV, XLSX, DOCX, PDF, OCR, HTML) dochodzą do chunkera jako tabela HTML, w której
nagłówek bywa źle oznaczony: CSV ma tytuł i adres nad tabelą i trzy wiersze nagłówka w danych,
DOCX (mammoth) daje do ``<thead>`` tylko pierwszy wiersz, a OCR (OTSL) oznacza jako nagłówek
każdy wiersz ze scaleniem w pionie, także wiersz danych. Bez poprawnych nazw kolumn rekord
„nazwa: wartość” to gołe liczby, a mały model bierze wartość z sąsiedniej kolumny.

``analyze`` czyta całą siatkę (wiersze nagłówka i danych razem) i zwraca:
- tytuł: wiersze nad nagłówkiem z jedną komórką (albo długim opisem i datą w ostatniej kolumnie);
- nazwy kolumn złożone ze wszystkich poziomów nagłówka („Pożar (P) / Ratownicy / Ranni”);
  pusta komórka poziomu nadrzędnego należy do grupy z lewej (scalenie zapisane w CSV/XLSX);
- wiersze danych: bez wiersza numeracji kolumn („1 2 3 4”), bez kolumny liczby porządkowej,
  z opisami scalonymi w pionie, z rodzicem w etykiecie podwiersza („Spokrewnione / dzieci”)
  i z etykietą PL/EN rozpisaną na wiersze lat („Przemysł / Industry”, 2014 i 2015).

Gdy tabela nie ma danych liczbowych z opisem (słownik, tekst w tabeli), ``analyze`` zwraca None
i obowiązuje dotychczasowy podział (thead albo pierwszy wiersz).
"""

from __future__ import annotations

import itertools
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

# Liczba w komórce (także „1 234,5”, „-0,3”, „12%”, „(12)”); rok i baza indeksu to nagłówek.
_VALUE = re.compile(r"\(?[-−–—+]?\s?\d[\d\s ]*(?:[.,]\d+)?\s?[a-z%‰]?\)?\*?")  # noqa: RUF001
_HEADER_NUMBER = re.compile(
    r"(?:1[89]|20)\d\d(?:\s?[/—–-]\s?(?:\d{2}|\d{4}))?(?:\s?[a-z]{1,2}\b|\*{1,2})?|\d+\s?=\s?\d*"  # noqa: RUF001
)
# Znaki umowne GUS i braki danych: liczą się jako wartość, ale nie wystarczą do wiersza danych.
_PLACEHOLDERS = frozenset(
    {"x", "•", ".", "-", "–", "—", "…", "...", "*", "#", "b.d.", "bd", "n/a", "na", "–*"}  # noqa: RUF001
)
_ORDINAL_HEAD = re.compile(r"(?i)^(l\.?\s?p\.?|nr|no\.?|#|lp)$")
_STUB_HEAD = re.compile(
    r"(?i)^(wyszczególnienie|specification|lata|years?|sekcje|sections|wojewódz|"
    r"podregion|powiat|gmin|kraj|countr|nazwa|name|lp\b|l\.p)"
)
_NAVIGATION = re.compile(r"(?i)^(powr[óo]t|wr[óo][ćc]|return|back to|spis tablic|←|<<)")
# Wiersz jednostki („w tys.”, „w zł in zl”, „W TYSIĄCACH TON”, „in %”): opis liczb całej tabeli.
_UNIT_ROW = re.compile(
    r"(?i)^((w|in)\s+(tys|mln|mld|zł|złotych|tysiącach|milionach|miliardach|thous|million|billion|"
    r"%|odsetkach|percent|procentach|szt|tonach|tys\. ton|hektarach|ha\b|km|osobach|pln|eur|usd)"
    r"|(%|‰|tys\.?|mln|mld|zł)$)"
)
_CAPTION = re.compile(r"(?i)^(tabl\.|tablica|tabela|tab\.|table|wykres|zestawienie)\s*\S")
_ALPHA = re.compile(r"[^\W\d_]")
_PL_CHARS = re.compile(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")
# Początek etykiety podwiersza w tabelach statystycznych (pod wierszem z wielkiej litery).
_SUBORDINATE = re.compile(
    r"(?i)^(w tym|z tego|z liczby|of which|in which|including|"
    r"kobiety|mężczyźni|chłopcy|dziewczęta|dzieci|miasta|wieś|wsie|na wsi|w miastach|"
    r"females|males|women|men|children|urban|rural|"
    r"na \d|na 1|per \d|w %|w odsetkach|w tys|w mln|w mld|in %|in thousand|in million|"
    r"udział|dynamika|wskaźnik|przeciętn|średni|mediana)"
)
_TITLE_MIN = 20  # krótszy pojedynczy tekst w 1. kolumnie to raczej opis nagłówka niż tytuł
_MAX_HEADER = 8  # dłuższy „nagłówek” to tekst nad tabelą: wiersze powyżej idą do tytułu
_MIN_NUMBERING = 3
_ORDINAL_SHARE = 0.8
_ORDINAL_START = 2  # liczba porządkowa zaczyna się od 0, 1 albo 2
_VALUE_COLUMN = 0.5  # udział liczb w niepustych komórkach kolumny danych
_PERIOD_SHARE = 0.5
_CASE_SHARE = 0.6
_YEAR_BLOCKS = 3  # najwyżej co trzeci rok w wierszu nagłówka może zaczynać nowy blok
_YEAR_COLUMN = 0.9  # tyle lat w kolumnie: to kolumna okresu, nie wartości
_MIN_WIDE = 4  # od tylu kolumn ostatnia może być tłumaczeniem opisu (tabele GUS PL/EN)


@dataclass(frozen=True)
class TableShape:
    """Wynik ``analyze``: indeksy odnoszą się do wierszy siatki wejściowej."""

    title: tuple[str, ...]  # teksty wierszy tytułowych (z góry na dół)
    header_rows: tuple[int, ...]  # wiersze nagłówka (bez tytułu i numeracji kolumn)
    labels: tuple[str, ...]  # nazwy kolumn po usunięciu ``dropped``
    body: tuple[int, ...]  # wiersze danych w kolejności
    rows: tuple[tuple[str, ...], ...]  # wiersze danych po poprawkach, bez kolumn ``dropped``
    dropped: tuple[int, ...]  # usunięte kolumny (liczba porządkowa, całkiem puste)


def _text(cell: str) -> str:
    return " ".join(cell.split())


def _year(cell: str) -> bool:
    """Liczba, która może być rokiem albo bazą indeksu („2015”, „2015/16”, „2010=100”)."""
    return bool(_HEADER_NUMBER.fullmatch(_text(cell)))


def is_number(cell: str) -> bool:
    """Liczba w komórce — także o wartości roku (1839 dzieci); „2010=100” to nagłówek."""
    text = _text(cell)
    if not text or "=" in text:
        return False
    return bool(_VALUE.fullmatch(text)) or _year(text)


def _datum(cell: str) -> bool:
    text = _text(cell).lower()
    return is_number(text) or text in _PLACEHOLDERS


def _is_label(cell: str) -> bool:
    """Opis wiersza: tekst z literą (nie znak umowny)."""
    text = _text(cell)
    return bool(text) and not _datum(text) and bool(_ALPHA.search(text))


def _ascending_years(cells: Sequence[str]) -> bool:
    """Wiersz lat nagłówka: same lata, rosnąco albo z powtórzeniem („2015 | 2015” nad podziałem)."""
    keys = [_text(c)[:4] for c in cells]
    if len(set(keys)) * 2 <= len(keys):  # tabela „podwójna”: 2010 | 2020 | 2010 | 2020
        return True
    # rosnące bloki lat („2005 2009 2010 | 2005 2010” nad liczbami i wskaźnikami); wiersz danych
    # o wartościach z zakresu lat (1886, 1839, 1804) spada częściej
    drops = sum(b < a for a, b in itertools.pairwise(keys))
    return drops * _YEAR_BLOCKS <= len(keys)


def _int(cell: str) -> int | None:
    text = _text(cell).strip("()")
    return int(text) if text.isdigit() else None


def _numbering(row: Sequence[str]) -> bool:
    """Wiersz numeracji kolumn: same kolejne liczby całkowite („0 1 2 3”, „(1) (2) (3)”)."""
    cells = [c for c in row if _text(c)]
    if len(cells) < _MIN_NUMBERING or len(cells) * 2 < len(row):
        return False
    nums = [_int(c) for c in cells]
    if any(n is None for n in nums):
        return False
    return all(b == a + 1 for a, b in itertools.pairwise(nums))  # type: ignore[operator]


def _data_row(row: Sequence[str]) -> bool:
    """Wiersz danych: co najmniej dwie wartości (jedna w wąskiej tabeli), w tym liczba, i opis.

    Opis wymagany, bo nagłówek z wiekiem („0 | 15 | 30”) albo numeracją też ma same liczby.
    """
    data = [i for i, c in enumerate(row) if _datum(c)]
    numbers = [i for i in data if is_number(row[i])]
    need = 1 if len(row) <= 2 else 2  # noqa: PLR2004
    if len(data) < need or not numbers:
        return False
    years = [i for i in numbers if _year(row[i])]
    plain = [i for i in numbers if i not in years]
    if not plain and len(years) >= need and _ascending_years([row[i] for i in years]):
        return False  # wiersz lat nagłówka („2010 | 2015 | 2020”)
    if any(_is_label(c) for c in row[: data[-1]]):
        return True
    # wiersz z rokiem zamiast opisu: „2015 | 123 | 456”
    return bool(years) and bool(plain) and years[0] == numbers[0] and years[0] < plain[0]


def _first_data(grid: Sequence[Sequence[str]]) -> int | None:
    for index, row in enumerate(grid):
        if not _numbering(row) and _data_row(row):
            return index
    return None


def _is_title(row: Sequence[str], full_width: bool) -> bool:  # noqa: PLR0911
    """Wiersz tytułu/opisu nad nagłówkiem.

    ``full_width``: jedna komórka scalona przez całą szerokość tabeli.
    """
    filled = [(i, _text(c)) for i, c in enumerate(row) if _text(c)]
    if not filled or any(_datum(t) for _, t in filled):
        return False
    if all(_NAVIGATION.match(t) for _, t in filled):
        return True
    filled = [(i, t) for i, t in filled if not _NAVIGATION.match(t)]  # „Powrót do spisu” obok
    first, text = filled[0]
    if _STUB_HEAD.match(text):
        return False
    if len(filled) == 1:  # tytuł, tłumaczenie tytułu, „Stan w dniu…”, jednostka nad tabelą
        return full_width or first <= 1 or len(text) >= _TITLE_MIN or bool(_UNIT_ROW.match(text))
    if len(filled) != 2 or first > 1:  # noqa: PLR2004
        return False
    second = filled[1][1]
    if _STUB_HEAD.match(second):
        return False
    # „TABL. 9 /147/. | ZACHOROWANIA…”, „DZIAŁ XI | CHAPTER XI” (PL i EN obok siebie),
    # „KG PSP Warszawa ul. …” w 1. kolumnie i data wydruku w ostatniej
    return (
        bool(_CAPTION.match(text))
        or (bool(_ALPHA.search(second)) and not _PL_CHARS.search(second) and first == 0)
        or (len(text) >= _TITLE_MIN and filled[1][0] >= len(row) - 2)
    )


def _unit_row(row: Sequence[str]) -> bool:
    """Wiersz z samą jednostką („w tys. in thous.”, „W TYSIĄCACH TON IN THOUSAND TONNES”)."""
    filled = [_text(c) for c in row if _text(c)]
    return (
        len(set(filled)) == 1
        and len(filled[0]) <= _TITLE_MIN * 3
        and bool(_UNIT_ROW.match(filled[0]))
    )


def _section_row(row: Sequence[str], head: Sequence[str]) -> bool:
    """Jeden tekst bez liczb: w kolumnie opisu albo scalony przez większość szerokości tabeli."""
    filled = [i for i, c in enumerate(row) if _text(c)]
    if (
        len(filled) == 2  # noqa: PLR2004
        and len(row) >= _MIN_WIDE
        and filled[0] <= 1
        and filled[1] >= len(row) - 2
        and not _PL_CHARS.search(row[filled[1]])
    ):
        filled = filled[:1]  # „Ziarno zbóż…:” i tłumaczenie EN w ostatniej kolumnie
    if len(filled) != 1 or _datum(row[filled[0]]) or _STUB_HEAD.match(_text(row[filled[0]])):
        return False
    texts = {_text(c) for c in head if _text(c)}
    spanned = sum(1 for c in head if _text(c))
    return filled[0] <= 1 or (len(texts) == 1 and spanned * 2 >= len(head))


def _value_columns(grid: Sequence[Sequence[str]], body: Sequence[int], width: int) -> list[bool]:
    """Kolumny wartości; kolumna samych lat (2014, 2015, 2014…) to opis okresu, nie wartości."""
    out: list[bool] = []
    for c in range(width):
        cells = [_text(grid[r][c]) for r in body if _text(grid[r][c])]
        numeric = sum(_datum(t) for t in cells) >= _VALUE_COLUMN * len(cells)
        periods = sum(_year(t) for t in cells) >= _YEAR_COLUMN * len(cells)
        out.append(bool(cells) and numeric and not periods)
    return out


def _ordinal(grid: Sequence[Sequence[str]], body: Sequence[int], c: int, head: str) -> bool:
    """Kolumna liczby porządkowej („Lp.”: 1, 2, 3…): nic nie mówi, a myli przy odczycie liczb.

    Liczą się tylko wiersze z danymi (stopka „Opracowano: …” stoi w tej samej kolumnie).
    """
    cells = [grid[r][c] for r in body if _text(grid[r][c]) and _data_row(grid[r])]
    nums = [_int(cell) for cell in cells]
    if len(nums) < _MIN_NUMBERING or any(n is None for n in nums):
        return False
    if _ORDINAL_HEAD.match(head):
        return True
    if any(_year(cell) for cell in cells) or nums[0] > _ORDINAL_START:  # type: ignore[operator]
        return False  # kolejne lata (2015, 2016, 2017) to opis okresu, nie liczba porządkowa
    steps = sum(b == a + 1 for a, b in itertools.pairwise(nums))  # type: ignore[operator]
    return steps >= _ORDINAL_SHARE * (len(nums) - 1)


def _fill_groups(rows: list[list[str]], first_value: int) -> None:
    """Puste komórki wyższych poziomów nagłówka należą do grupy z lewej (scalenie w CSV/XLSX).

    Nie przekracza granicy grupy poziomu wyżej ani kolumn opisu (lewa strona tabeli).
    """
    for level, row in enumerate(rows[:-1]):
        parent = rows[level - 1] if level else None
        for c in range(max(1, first_value + 1), len(row)):
            if _text(row[c]) or not _text(row[c - 1]):
                continue
            if parent is not None and parent[c] != parent[c - 1]:
                continue
            row[c] = row[c - 1]
    for level, row in enumerate(rows):
        if level and _span_row(row, rows[level - 1], first_value):
            for c in range(first_value + 1, len(row)):
                if not _text(row[c]):
                    row[c] = row[c - 1]


def _span_row(row: Sequence[str], above: Sequence[str], first_value: int) -> bool:
    """Wiersz grup POD pełnym wierszem (lata, potem „w liczbach bezwzględnych” / „na 100 tys.”).

    Rzadkie komórki, każda otwiera blok pustych, a wiersz wyżej ma podpis w każdej kolumnie:
    podpis obejmuje kolumny do następnego podpisu (scalenie zapisane w XLSX tylko w 1. komórce).
    """
    cells = list(row[first_value:])
    marks = [i for i, c in enumerate(cells) if _text(c)]
    if not marks or marks[0] != 0 or len(marks) * 2 > len(cells):
        return False
    if any(b - a < 2 for a, b in itertools.pairwise([*marks, len(cells)])):  # noqa: PLR2004
        return False
    return all(_text(c) for c in above[first_value:])


def join_label(parts: Sequence[str]) -> str:
    """Części nazwy kolumny z góry na dół: bez powtórzeń, przeniesienia wyrazów sklejone."""
    out = ""
    for part in parts:
        text = _text(part)
        if not text or out == text or out.endswith(f" / {text}"):
            continue
        if out.endswith("-") and not out.endswith(" -"):
            out = out[:-1] + text  # przeniesienie wyrazu
        elif out:
            out = f"{out} / {text}"
        else:
            out = text
    return out


def _periodic(labels: Sequence[str]) -> bool:
    n = len(labels)
    return any(
        n % k == 0 and labels[0] and all(labels[i] == labels[i % k] for i in range(n))
        for k in range(2, n // 2 + 1)
    )


def _unique(labels: list[str], stub: int) -> list[str]:
    """Powtórzona nazwa kolumny (zgubiony poziom nagłówka) dostaje numer kolejny: „… (2)”.

    W kolumnach opisu (pierwsze ``stub``) powtórzenie to jedna komórka scalona nad opisem
    i rokiem („SEKCJE”) — druga kolumna zostaje bez nazwy.
    """
    if _periodic(labels):  # tabela „podwójna” — rozdziela ją chunker po powtórzonym nagłówku
        return labels
    seen: Counter[str] = Counter()
    out: list[str] = []
    for i, label in enumerate(labels):
        seen[label] += 1
        if label and seen[label] > 1:
            label = "" if i < stub else f"{label} ({seen[label]})"  # noqa: PLW2901
        out.append(label)
    return out


def _fill_down(rows: list[list[str]], stub: Sequence[int]) -> None:
    """Opis scalony w pionie (województwo nad powiatami) powielony w wierszach z danymi.

    Ostatnia kolumna opisu nie dziedziczy: pusta to brak podpisu, nie scalenie.
    """
    last: dict[int, str] = {}
    for row in rows:
        has_values = any(_datum(c) for c in row)
        for c in stub[:-1]:
            if _text(row[c]):
                last[c] = row[c]
            elif has_values and c in last:
                row[c] = last[c]


def _period_groups(rows: list[list[str]], stub: Sequence[int]) -> None:
    """Etykieta rozpisana na wiersze lat → wspólna („Przemysł | 2014”, „Industry | 2015”).

    Obie dostają „Przemysł / Industry”.

    DOCX roczników daje nazwę PL w pierwszym wierszu grupy, EN w drugim, a rok w osobnej kolumnie.
    """
    if len(stub) < 2:  # noqa: PLR2004
        return
    label_col, period_col = stub[0], stub[-1]
    periods = [_text(r[period_col]) for r in rows]
    if sum(bool(_HEADER_NUMBER.fullmatch(p)) for p in periods) < _PERIOD_SHARE * len(rows):
        return
    groups: list[list[int]] = []
    previous = ""
    for i, period in enumerate(periods):
        if not any(_datum(c) for c in rows[i]):  # wiersz-sekcja („CZĘŚĆ: PART:”) zamyka grupę
            previous = ""
            groups.append([])
            continue
        if not groups or (period and previous and period <= previous):
            groups.append([])
        groups[-1].append(i)
        previous = period or previous
    for group in groups:
        names: list[str] = []
        for i in group:
            name = _text(rows[i][label_col])
            if _ALPHA.search(name) and name not in names:  # liczba w opisie to nie nazwa
                names.append(name)
        if len(names) > 1:
            for i in group:
                rows[i][label_col] = " / ".join(names)


def _first_alpha(text: str) -> str:
    match = _ALPHA.search(text)
    return match.group(0) if match else ""


def _sub_rows(rows: list[list[str]], label_col: int) -> None:
    """Podwiersz („dzieci”, „w tym kobiety”, „na 1000 ludności”) dostaje rodzica w etykiecie.

    GUS pisze podwiersze małą literą pod wierszem z wielkiej („Spokrewnione”, „dzieci”); bez
    rodzica model bierze liczbę rodzin zamiast dzieci. Tylko etykiety z listy ``_SUBORDINATE``:
    w tabelach administracyjnych mała litera znaczy co innego (powiat nad gminami KG PSP).
    Rodzic to najbliższy wyższy wiersz z danymi z wielkiej litery, a między nim a podwierszem
    mogą stać tylko inne podwiersze; wiersz-sekcja (opis bez danych) przerywa dziedziczenie.
    """
    parent = ""
    previous_data = False
    for row in rows:
        label = _text(row[label_col])
        if not any(_datum(c) for c in row):
            # tłumaczenie EN pod wierszem z danymi („Przemysł”, „Industry”) nie zamyka rodzica
            if not _translation(label, previous_data):
                parent = ""
            previous_data = False
            continue
        previous_data = True
        first = _first_alpha(label)
        if not first:
            continue
        if first.isupper():
            parent = label
        elif parent and " / " not in label and _SUBORDINATE.match(label):
            row[label_col] = f"{parent} / {label}"
        else:
            parent = ""


def _translation(label: str, previous_data: bool) -> bool:
    """Wiersz-tłumaczenie EN bez danych pod wierszem z danymi („Przemysł”, potem „Industry”)."""
    return previous_data and bool(label) and not _PL_CHARS.search(label)


def _nest(rows: list[list[str]], col: int, levels: Sequence[int]) -> bool:
    """Ścieżka etykiety z wcięć (XLSX: ``alignment.indent``, spacje) i z powtórzeń.

    - wiersz wcięty głębiej należy do najbliższego wyższego wiersza z mniejszym wcięciem
      („Spokrewnione”, „   dzieci” → „Spokrewnione / dzieci”);
    - etykieta powtarzana na tym samym poziomie („Miasta”, „Wieś” pod każdą grupą wieku) należy
      do ostatniej niepowtarzanej etykiety tego poziomu („W wieku produkcyjnym / Miasta / kobiety”).
    Wiersz-sekcja (opis bez danych) zaczyna wszystko od nowa. Zwraca, czy coś zmienił.
    """
    data = [i for i, r in enumerate(rows) if any(_datum(c) for c in r) and _ALPHA.search(r[col])]
    # liczą się osobne wystąpienia: ta sama etykieta w kolejnych wierszach (rozpisana na lata)
    # to jeden opis, nie powtórzenie
    repeated = Counter(
        (levels[i], _text(rows[i][col]))
        for n, i in enumerate(data)
        if not n or _text(rows[data[n - 1]][col]) != _text(rows[i][col]) or data[n - 1] != i - 1
    )
    if all(n == 1 for n in repeated.values()) and not any(levels[i] for i in data):
        return False
    stack: list[tuple[int, str]] = []
    unique: dict[int, str] = {}
    previous_data = False
    changed = False
    for i, row in enumerate(rows):
        label = _text(row[col])
        if not any(_datum(c) for c in row):
            if label and not _translation(label, previous_data):
                stack, unique = [], {}
            previous_data = False
            continue
        previous_data = True
        if not _ALPHA.search(label):  # wiek „0”, wartość w kolumnie opisu — nie etykieta
            continue
        level = levels[i]
        stack = [(lvl, path) for lvl, path in stack if lvl < level]
        base = stack[-1][1] if stack else ""
        if repeated[(level, label)] > 1:
            if not stack:  # powtarzana etykieta najwyższego poziomu („Miasta”) — pod grupą
                base = unique.get(level, "")
        else:
            unique = {lvl: path for lvl, path in unique.items() if lvl < level}
        full = join_label([base, label]) if base and not label.startswith(base) else label
        if repeated[(level, label)] == 1:
            unique[level] = full
        stack.append((level, full))
        if full != label:
            row[col] = full
            changed = True
    return changed


def _case(label: str) -> str:
    """Klasa zapisu etykiety: U — wersaliki, l — z małej litery, C — z wielkiej."""
    letters = _ALPHA.findall(label)
    if len(letters) >= 2 and all(ch.isupper() for ch in letters):  # noqa: PLR2004
        return "U"
    return "l" if letters and letters[0].islower() else "C"


def _case_hierarchy(rows: list[list[str]], label_col: int) -> bool:
    """Podział administracyjny zapisany wielkością liter: WOJEWÓDZTWO, powiat, Gmina.

    KG PSP i podobne zestawienia nie mają kolumn poziomów — gmina bez powiatu i województwa
    jest nie do odróżnienia („Bolesławiec” jest i gminą wiejską, i miejską w innym powiecie).
    Wzorzec przyjęty, gdy są wszystkie trzy klasy, po wersalikach zwykle stoi mała litera,
    a po małej literze — wielka. Etykieta dostaje ścieżkę:
    „DOLNOŚLĄSKIE / bolesławiecki / Gromadka”.
    """
    data = [i for i, r in enumerate(rows) if any(_datum(c) for c in r) and _text(r[label_col])]
    kinds = [_case(_text(rows[i][label_col])) for i in data]
    counts = Counter(kinds)
    if min(counts["U"], counts["l"], counts["C"]) < _MIN_NUMBERING:
        return False
    pairs = list(itertools.pairwise(kinds))
    after_u = [b for a, b in pairs if a == "U"]
    after_l = [b for a, b in pairs if a == "l"]
    if after_u.count("l") < _CASE_SHARE * len(after_u) or after_l.count("C") < _CASE_SHARE * len(
        after_l
    ):
        return False
    path = {"U": "", "l": ""}
    for i, kind in zip(data, kinds, strict=True):
        label = _text(rows[i][label_col])
        if kind == "U":
            path = {"U": label, "l": ""}
        elif kind == "l":
            path["l"] = label
            rows[i][label_col] = join_label([path["U"], label])
        else:
            rows[i][label_col] = join_label([path["U"], path["l"], label])
    return True


def analyze(
    grid: Sequence[Sequence[str]],
    head_grid: Sequence[Sequence[str]] | None = None,
    levels: Sequence[int] | None = None,
) -> TableShape | None:
    """Struktura tabeli; None, gdy nie ma wiersza danych z opisem (zostaje podział wejściowy).

    ``grid``: komórki wierszy (scalenia w pionie powielone, w poziomie tylko w 1. kolumnie),
    ``head_grid``: ta sama siatka ze scaleniami w poziomie powielonymi (nazwa grupy nad kolumnami),
    ``levels``: wcięcie opisu każdego wiersza (arkusze), gdy jest znane.
    """
    width = max((len(r) for r in grid), default=0)
    if width < 2 or len(grid) < 2:  # noqa: PLR2004
        return None
    rows = [list(r) + [""] * (width - len(r)) for r in grid]
    heads = [list(r) + [""] * (width - len(r)) for r in (head_grid or grid)]
    first = _first_data(rows)
    if not first:  # brak danych albo dane od 1. wiersza: nagłówek bierze się z thead
        return None
    title_end = 0
    while title_end < first - 1 and _is_title(
        rows[title_end], len({_text(c) for c in heads[title_end]}) == 1
    ):
        title_end += 1
    header = [r for r in range(title_end, first) if not _numbering(rows[r])]
    if len(header) > _MAX_HEADER:  # długi wstęp nad tabelą: do tytułu, nagłówek to ostatnie wiersze
        title_end, header = header[-_MAX_HEADER], header[-_MAX_HEADER:]
    title = tuple(
        " ".join(_text(c) for c in rows[r] if _text(c)) for r in range(title_end) if any(rows[r])
    )
    # Wiersz jednostki w nagłówku („w zł in zl” pod latami) dotyczy całej tabeli: do tytułu.
    units = [r for r in header if _unit_row(rows[r])]
    header = [r for r in header if r not in units]
    title += tuple(" ".join(_text(c) for c in rows[r] if _text(c)) for r in units)
    # Wiersz-sekcja tuż nad danymi („POWIERZCHNIA. TOTAL AREA.”, „Zasoby … na 1000 ludności:”
    # w tabeli-kontynuacji bez nagłówka) należy do danych, nie do nazw kolumn.
    while header and _section_row(rows[header[-1]], heads[header[-1]]):
        first = header.pop()
    lead_units = [r for r in range(first, len(rows)) if r < first + 2 and _unit_row(rows[r])]
    title += tuple(" ".join(_text(c) for c in rows[r] if _text(c)) for r in lead_units)
    body = [
        r for r in range(first, len(rows)) if any(_text(c) for c in rows[r]) and r not in lead_units
    ]
    body = [r for r in body if not _numbering(rows[r])]
    values = _value_columns(rows, body, width)
    head_text = [join_label([heads[r][c] for r in header]) for c in range(width)]
    dropped = [
        c
        for c in range(width)
        if not any(_text(rows[r][c]) for r in body)
        or (c <= 1 and _ordinal(rows, body, c, head_text[c]))
    ]
    kept = [c for c in range(width) if c not in dropped]
    first_value = next((c for c in kept if values[c]), width)
    stub = [c for c in kept if c < first_value]
    tiers = [list(heads[r]) for r in header]
    _fill_groups(tiers, first_value)
    labels = _unique([join_label([tier[c] for tier in tiers]) for c in kept], len(stub))
    data = [list(rows[r]) for r in body]
    if stub:
        _fill_down(data, stub)
        labelled = [c for c in stub if not _period_column(data, c)]
        if len(labelled) < len(stub):
            _period_groups(data, stub)
        if labelled and not _case_hierarchy(data, labelled[-1]):
            depth = [levels[r] if levels and r < len(levels) else 0 for r in body]
            _nest(data, labelled[-1], depth)
            _sub_rows(data, labelled[-1])
    return TableShape(
        title=title,
        header_rows=tuple(header),
        labels=tuple(labels),
        body=tuple(body),
        rows=tuple(tuple(row[c] for c in kept) for row in data),
        dropped=tuple(dropped),
    )


def _period_column(rows: Sequence[Sequence[str]], c: int) -> bool:
    """Kolumna opisu z latami/okresami („2014”, „2015”) zamiast nazw."""
    periods = [_text(r[c]) for r in rows]
    return sum(bool(_HEADER_NUMBER.fullmatch(p)) for p in periods) >= _PERIOD_SHARE * max(
        1, len(rows)
    )
