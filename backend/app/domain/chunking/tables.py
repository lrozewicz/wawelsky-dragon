"""Tabele: tekst wierszy i dzielenie tabeli na chunki (CONTRACT WP E1-5 C7)."""

import html
import logging
import re
from collections.abc import Sequence

from app.domain.chunking.limits import split_to_limit
from app.domain.chunking.types import Block, ChunkConfig, ChunkDraft, TableData

logger = logging.getLogger(__name__)

_LEAD_MAX = 300  # dłuższy akapit to treść, nie podpis tabeli
# Koniec zdania: [.!?] i wielka litera (także bez spacji); „tys. zł” nie dzieli.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s*(?=[A-ZĄĆĘŁŃÓŚŹŻ])")
# Skala i jednostka liczb tabeli: „(dollars in millions)”, „w mln zł”, „w tys.”.
_UNIT = re.compile(
    r"(?i)\b(in (thousands|millions|billions)|w (tys\.?|tysiącach|mln|milionach|mld|miliardach)"
    r"|(tys|mln|mld)\.? (zł|złotych|pln|usd|eur)|thousands of|millions of)\b"
)
# Tytuł tabeli: „TABL. 13 (227).”, „Tablica 2”, „Tabela 1.”, „Tab. 4”, „Table 3”; OCR także
# „TABLE. 27”, „TABLEL. 26”. Roczniki w DOCX: „TABL.” stoi poza tekstem akapitu (styl
# „Tyt. tab. pol.”), zostaje „5 (190). POJAZDY…” — numer w dziale, numer w roczniku w nawiasie
# i tytuł wielkimi literami.
_CAPTION = re.compile(
    r"(?i)^(tabl\.|tablica|tabela|tab\.|tablel?\.?)\s*(\d|[ivxlc]+\b)"
    r"|^\d{1,3}\s?\(\d{1,4}\)\.\s*(?-i:[A-ZĄĆĘŁŃÓŚŹŻ]{2})"
)
# Nysa: TABL. 4 | Stan w dniu 31 XII | POPULATION BY AGE | As of 31 XII | tabela;
# praca 2017: TABL. 13 (116) + 3 linie tytułu PL + 2 linie EN, każda osobnym akapitem.
_CAPTION_LOOKBACK = 7
_CAPTION_GAP_MAX = 120  # dłuższy akapit między tytułem a tabelą to treść — tytuł jest czegoś innego
_CAPTION_TAIL = 2
_CONT = re.compile(r"(?i)\((cd|cont|dok)\.?\)")
_PL_CHARS = re.compile(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")
_MIN_TRANSLATIONS = 2
_SECTION_MAX = 100  # dłuższy tekst w jednej komórce to notatka, nie etykieta sekcji
_SENTENCE_WORDS = 6
_MIN_BLOCK = 3  # tyle kolejnych powtórzonych etykiet wyznacza blok („Miasta”, „Wieś”)
_BLOCK_CANDIDATES = 20  # ostatnie wystąpienia etykiety sprawdzane jako początek ciągu
_NUMERIC = re.compile(r"[\d\s.,%()+\-\u2013\u2014]*")
Lines = Sequence[Sequence[str]]  # linie tekstu każdego wiersza tabeli (table_lines)


def _unit_lead(prev: Block | None) -> str:
    if prev is None or prev.kind != "paragraph":  # nagłówek jest już w breadcrumbie
        return ""
    text = " ".join(prev.text.split())
    if not text:
        return ""
    last = _SENTENCE_END.split(text)[-1] if len(text) > _LEAD_MAX else text
    if len(last) > _LEAD_MAX:
        return ""
    return last if last.endswith(":") or _UNIT.search(last) else ""


def table_caption(before: Sequence[Block]) -> str:
    """Tytuł tabeli („TABL. 13 (227). SZKOŁY PODSTAWOWE…”, „Tabela 2. …”) z akapitów tuż przed nią.

    W rocznikach tytuł stoi w akapicie (czasem na końcu bloku przypisów poprzedniej tabeli),
    nie w nagłówku, więc bez niego żaden chunk tabeli nie mówi, czego dotyczą liczby.
    Szuka w ostatnich ``_CAPTION_LOOKBACK`` akapitach; za tytułem dopuszcza najwyżej
    ``_CAPTION_TAIL`` linii w tym samym akapicie (tłumaczenie tytułu, podtytuł) albo krótkie
    osobne akapity (OCR: „Stan w dniu 31 XII”, tytuł EN, „As of 31 XII”).
    """
    for back, block in enumerate(reversed(before[-_CAPTION_LOOKBACK:])):
        if block.kind in ("table", "heading"):  # tytuł sprzed nagłówka należy do innej sekcji
            return ""
        if block.kind != "paragraph":
            continue
        lines = [ln.strip() for ln in block.text.splitlines() if ln.strip()]
        for i in range(len(lines) - 1, -1, -1):
            if _CAPTION.match(lines[i]):
                if len(lines) - 1 - i > _CAPTION_TAIL:
                    return ""
                return " ".join(lines[i].split())[:_LEAD_MAX]
        # OCR daje dopiski tytułu („Stan w dniu 31 XII”, tłumaczenie) jako osobne akapity; tytuł
        # może stać kilka akapitów wyżej, ale tylko za krótkimi dopiskami, nie za tekstem
        if back and len(" ".join(lines)) > _CAPTION_GAP_MAX:
            return ""
    return ""


def table_lead(prev: Block | None, before: Sequence[Block] = ()) -> str:
    """Tytuł tabeli i zdanie wprowadzające (kończy się „:” albo podaje jednostkę).

    Bez nich chunk z samymi liczbami traci temat i skalę („66,952” bez „in millions”).
    ``prev`` to blok tuż przed tabelą, ``before`` bloki przed nią (do szukania tytułu).
    """
    caption = table_caption(before) if before else ""
    unit = _unit_lead(prev)
    if caption and unit and (unit in caption or caption in unit):
        return max(caption, unit, key=len)
    return "\n".join(part for part in (caption, unit) if part)


_CAPS_MIN_WORDS = 4
_CAPS_MIN_CHARS = 25
_CAPS_RATIO = 0.9
_PL_LETTERS = frozenset("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")
_EN_WORDS = frozenset({"THE", "OF", "IN", "BY", "ON", "AND", "AGAINST", "FOR", "WITH"})


def _english(text: str) -> bool:
    """Angielski tekst: bez polskich liter i z angielskim słowem funkcyjnym."""
    words = {w.strip(".,:;()").upper() for w in text.split()}
    return not _PL_LETTERS.intersection(text) and bool(words & _EN_WORDS)


def caps_title(prev: Block | None) -> str:
    """Tytuł bez „Tabela N” wersalikami tuż nad tabelą (załączniki aktów: „LIMIT PRZYJĘĆ…”).

    Tylko gdy tabela nie ma tytułu z ``table_lead`` — inaczej krótkie wersaliki to wiersz-sekcja
    albo nagłówek strony. Pomija tabelę, której tytuł „TABL. …” jest nagłówkiem (stoi w
    breadcrumbie) — wersaliki pod nim to tylko tłumaczenie.
    """
    if prev is None or prev.kind != "paragraph":
        return ""
    if prev.heading_path and _CAPTION.match(prev.heading_path[-1]):
        return ""
    text = " ".join(prev.text.split())
    if _english(text):  # tłumaczenie EN polskiego nagłówka („VOIVODSHIP AGAINST THE…”)
        return ""
    letters = [c for c in text if c.isalpha()]
    if (
        len(text) < _CAPS_MIN_CHARS
        or len(text) > _LEAD_MAX
        or len(text.split()) < _CAPS_MIN_WORDS
        or text.endswith(".")
        or not letters
        or sum(c.isupper() for c in letters) < _CAPS_RATIO * len(letters)
    ):
        return ""
    return text


def _norm_head(cell: str) -> str:
    return _CONT.sub("", " ".join(cell.split())).strip().casefold()


def _period(header: Sequence[str]) -> int:
    """Szerokość jednego rekordu, gdy tabela „podwójna” powtarza nagłówek obok siebie (0: nie).

    Roczniki GUS składają wąskie tabele w dwie kolumny strony: Poznań i Luboń w jednym
    wierszu. Bez rozdzielenia model bierze wartości sąsiedniego miasta.
    """
    n = len(header)
    heads = [_norm_head(h) for h in header]
    for k in range(2, n // 2 + 1):
        if n % k or not heads[0]:
            continue
        if all(heads[i] == heads[i % k] for i in range(n)):
            return k
    return 0


def _label(row: Sequence[str]) -> str:
    """Tekst wiersza-etykiety (jedyna niepusta, nieliczbowa w 1. lub 2. kolumnie) lub ""."""
    filled = [i for i, v in enumerate(row) if v.strip()]
    if len(filled) != 1 or filled[0] > 1:
        return ""
    text = row[filled[0]].strip()
    if _NUMERIC.fullmatch(text) or len(text) > _SECTION_MAX:
        return ""
    if text.endswith(".") and len(text.split()) >= _SENTENCE_WORDS:  # notatka, nie sekcja
        return ""
    return text


def _has_data(row: Sequence[str]) -> bool:
    return not _label(row) and any(v.strip() for v in row)


def _translation_rows(header: Sequence[str], rows: Sequence[Sequence[str]]) -> set[int]:
    """Wiersze-tłumaczenia tabel dwujęzycznych: etykieta bez polskich znaków po wierszu z danymi.

    GUS po każdym wierszu „Uczniowie w tys. …” daje „Pupils in thousands” bez liczb; jako
    osobna linia mylą model i rozrzedzają chunk. Usuwane tylko, gdy wzorzec dotyczy co najmniej
    połowy wierszy z danymi (tabela naprawdę naprzemienna), żeby nie gubić podtytułów sekcji,
    i tylko w tabeli polskiej (polskie znaki w nagłówku lub etykietach), nie w angielskiej.
    """
    data = [i for i, r in enumerate(rows) if _has_data(r)]
    polish = " ".join([*header, *(r[0] for r in rows if r)])
    if not _PL_CHARS.search(polish):
        return set()
    after = [i + 1 for i in data if i + 1 < len(rows) and _label(rows[i + 1])]
    if len(after) < _MIN_TRANSLATIONS or len(after) * 2 < len(data):
        return set()
    return {
        i
        for i in after
        if not _PL_CHARS.search(_label(rows[i])) and not _label(rows[i]).endswith(":")
    }


def _core(label: str) -> str:
    """Etykieta do porównań: bez „(cd.)”, „(dok.)”, „(cont.)”, kropek i wielkości liter."""
    return " ".join(_CONT.sub("", label).replace("…", "").strip(" .").split()).casefold()


def _with_section(row: Sequence[str], section: str) -> tuple[str, ...]:
    """Etykieta sekcji („WIEŚ”, „Szkoły specjalne”) dopisana do pierwszej komórki opisowej."""
    out = tuple(row)
    for i in (0, 1):
        if i < len(out) and out[i].strip() and not _NUMERIC.fullmatch(out[i].strip()):
            if _core(out[i]).startswith(_core(section)):  # „Females / Females”
                return out
            return (*out[:i], f"{section} / {out[i].strip()}", *out[i + 1 :])
    return out


def _desc(row: Sequence[str]) -> str:
    """Pierwsza komórka opisowa (nieliczbowa) z dwóch pierwszych kolumn, albo ""."""
    for i in (0, 1):
        if i < len(row) and row[i].strip() and not _NUMERIC.fullmatch(row[i].strip()):
            return " ".join(row[i].split())
    return ""


def _row_label(row: Sequence[str]) -> str:
    return _desc(row).casefold()


def _block_headers(rows: Sequence[Sequence[str]]) -> dict[int, str]:
    """Nagłówki bloków powtarzających ten sam ciąg etykiet: {indeks wiersza: etykieta bloku}.

    GUS daje „POLSKA”, 16 województw, „Miasta”, te same 16, „Wieś”, te same 16 — wiersz
    zbiorczy ma liczby, więc nie jest wierszem-sekcją. Gdy co najmniej ``_MIN_BLOCK`` kolejnych
    etykiet powtarza wcześniejszy ciąg, wiersz tuż przed każdym z obu ciągów jest ich nagłówkiem.
    """
    labels = [_row_label(r) if _has_data(r) else "" for r in rows]
    where: dict[str, list[int]] = {}
    out: dict[int, str] = {}
    i = 0
    while i < len(labels):
        best, start = 0, -1
        for j in where.get(labels[i], [])[-_BLOCK_CANDIDATES:] if labels[i] else []:
            n = 0
            while (
                i + n < len(labels)
                and j + n < i
                and labels[i + n]
                and labels[j + n] == labels[i + n]
            ):
                n += 1
            if n > best:
                best, start = n, j
        if best >= _MIN_BLOCK and i > 0 and start > 0:
            for first in (start, i):
                head = rows[first - 1]
                label = next(
                    (
                        c.strip()
                        for c in head[:2]
                        if c.strip() and not _NUMERIC.fullmatch(c.strip())
                    ),
                    "",
                )
                if label:
                    for r in range(first, first + best):
                        out.setdefault(r, " ".join(label.split())[:_LEAD_MAX])
        for n in range(max(best, 1)):
            if i + n < len(labels) and labels[i + n]:
                where.setdefault(labels[i + n], []).append(i + n)
        i += max(best, 1)
    return out


def _part_labels(row: Sequence[str], k: int) -> list[str]:
    parts = [row[s : s + k] for s in range(0, len(row), k)] if k else [row]
    return [label for part in parts if (label := _label(part))]


def section_heads(tables: Sequence[TableData]) -> frozenset[str]:
    """Etykiety wierszy-sekcji ze wszystkich tabel dokumentu (``_core``).

    Rocznik dzieli tabelę na strony: „Podkarpackie (cd.)” bywa sekcją dopiero na następnej
    stronie, a na bieżącej „Podkarpackie” to wiersz z sumą, który musi zamknąć „Opolskie (dok.)”.
    """
    out: set[str] = set()
    for t in tables:
        k = _period(t.header)
        out.update(_core(label) for row in t.rows for label in _part_labels(row, k))
    return frozenset(out)


def table_lines(table: TableData, doc_heads: frozenset[str] = frozenset()) -> list[list[str]]:
    """Linie tekstu każdego wiersza tabeli (C7): jeden rekord „nazwa: wartość” na linię.

    - wiersz tabeli „podwójnej” (nagłówek powtórzony obok) daje osobną linię na rekord;
    - wiersz-tłumaczenie tabeli dwujęzycznej daje pustą listę;
    - wiersz z samą etykietą to sekcja („MIASTA”, „WIEŚ”): nie daje linii, a jej tekst trafia
      do etykiety kolejnych wierszy, bo po podziale tabeli na chunki sekcja zostaje w innym
      chunku niż jej wiersze (dwa „Warmińsko-mazurskie” bez „miasta”/„wieś”).
    """
    k = _period(table.header)
    header = table.header[:k] if k else table.header
    skip = _translation_rows(table.header, table.rows)
    blocks = {} if k else _block_headers(table.rows)
    sections: dict[int, str] = {}  # sekcja per kolumna rekordów tabeli „podwójnej”
    # Etykiety, które gdzieś są wierszem-sekcją („Podkarpackie (cd.)”): ten sam opis w wierszu
    # z danymi („Podkarpackie” z sumą) otwiera nową sekcję, zamiast dziedziczyć poprzednią.
    heads = doc_heads | section_heads([table])
    pending: dict[int, list[tuple[int, str]]] = {}  # wiersze-etykiety (PL + EN) przed danymi
    out: list[list[str]] = []
    for idx, row in enumerate(table.rows):
        out.append([])
        if idx in skip:
            continue
        parts = [row[s : s + k] for s in range(0, len(row), k)] if k else [row]
        for j, part in enumerate(parts):
            if label := _label(part):
                pending.setdefault(j, []).append((idx, label))
                continue
            if not any(v.strip() for v in part):
                continue
            if j in pending:
                sections[j] = " ".join(text for _, text in pending.pop(j))[:_LEAD_MAX]
            elif (own := _desc(part)) and _core(own) in heads:
                sections[j] = own[:_LEAD_MAX]
                out[idx].append(row_text(header, part))  # wiersz z danymi: tekst niepusty
                continue
            if block := blocks.get(idx):
                part = _with_section(part, block)  # noqa: PLW2901
            if section := sections.get(j):
                part = _with_section(part, section)  # noqa: PLW2901
            if line := row_text(header, part):
                out[idx].append(line)
    for labels in pending.values():  # etykiety bez danych po nich (koniec tabeli) zostają tekstem
        for idx, text in labels:
            out[idx].append(row_text(header, (text,)))
    return out


def _breadcrumb(path: tuple[str, ...]) -> str:
    return " > ".join(path)


def _bc_text(path: tuple[str, ...]) -> str:
    return _breadcrumb(path) + "\n" if path else ""


def _bc_html(path: tuple[str, ...]) -> str:
    return f'<p class="breadcrumb">{html.escape(_breadcrumb(path))}</p>' if path else ""


def row_text(header: Sequence[str], row: Sequence[str]) -> str:
    """Pary "nazwa: wartość", a bez nazwy kolumny sama wartość; złączone "; " (C7).

    Zastępcze ``column_N`` nic nie znaczy, a pogarsza embedding i myli modele przy odczycie.
    """
    pairs: list[str] = []
    for i, value in enumerate(row):
        if not value.strip():
            continue
        named = i < len(header) and header[i].strip()
        pairs.append(f"{header[i]}: {value}" if named else value)
    return "; ".join(pairs)


def _group_text(t: TableData, idxs: Sequence[int], html4excel: bool, lines: Lines) -> str:
    """Tekst grupy wierszy; przy html4excel linia nagłówka na początku (gdy nagłówek niepusty)."""
    if not html4excel:
        return "\n".join(line for i in idxs for line in lines[i])
    out = [" | ".join(t.header)] if t.header else []
    out.extend(" | ".join(t.rows[i]) for i in idxs)
    return "\n".join(out)


def table_text(table: TableData, html4excel: bool) -> str:
    """Tekst całej tabeli (C7): rekordy "kol: wart" po jednym na linię albo linie " | "."""
    lines = [] if html4excel else table_lines(table)
    return _group_text(table, range(len(table.rows)), html4excel, lines)


def _draft(block: Block, text: str, fragment_html: str, cfg: ChunkConfig) -> ChunkDraft:
    return ChunkDraft(
        ordinal=-1,
        text=text,
        html=fragment_html,
        chunk_type="table",
        heading_path=block.heading_path,
        positions=block.positions,
        page_from=None,
        page_to=None,
        tokens=cfg.count_tokens(text),
        questions=(),
        metadata={},
    )


def _row_groups(t: TableData, bc: str, cfg: ChunkConfig, lines: Lines) -> list[list[int]]:
    """Zachłanne grupowanie indeksów wierszy do limitu; nadmiarowy wiersz w grupie własnej."""
    groups: list[list[int]] = []
    current: list[int] = []
    for idx in range(len(t.rows)):
        single = bc + _group_text(t, [idx], cfg.html4excel, lines)
        if cfg.count_tokens(single) > cfg.chunk_token_num:
            if current:
                groups.append(current)
            groups.append([idx])
            current = []
            continue
        if current:
            tekst = bc + _group_text(t, [*current, idx], cfg.html4excel, lines)
            if cfg.count_tokens(tekst) > cfg.chunk_token_num:
                groups.append(current)
                current = [idx]
                continue
        current.append(idx)
    if current:
        groups.append(current)
    return groups


_CELL_HTML = re.compile(r"<t([dh])\b([^>]*)>(.*?)</t\1\s*>", re.S | re.I)
_TR_OPEN = re.compile(r"^\s*<tr\b[^>]*>", re.I)
_ROWSPAN = re.compile(r"""\s+rowspan\s*=\s*["']?\d*["']?""", re.I)
_SPAN_VALUE = r"""\b{}\s*=\s*["']?(\d+)"""


def _span_of(attrs: str, name: str) -> int:
    m = re.search(_SPAN_VALUE.format(name), attrs, re.I)
    return max(1, int(m.group(1))) if m else 1


def _with_rowspan(cell: re.Match[str], rows: int) -> str:
    """Komórka z rowspan ustawionym na ``rows`` (1 → bez atrybutu)."""
    attrs = _ROWSPAN.sub("", cell.group(2)) + (f' rowspan="{rows}"' if rows > 1 else "")
    return f"<t{cell.group(1)}{attrs}>{cell.group(3)}</t{cell.group(1)}>"


def split_rows_html(rows_html: Sequence[str], group: Sequence[int]) -> list[str]:
    """``<tr>`` wierszy ``group`` (kolejne indeksy) z rowspan domkniętym w obrębie grupy.

    Gdy tabela dzielona na fragmenty ma komórkę z rowspan (np. etykieta „Polska” nad
    latami), wiersze-kontynuacje w następnym fragmencie nie mają tej komórki, więc ich
    wartości przesuwają się o kolumnę w lewo. Pierwszy wiersz grupy dostaje kopię komórek
    rozpiętych z wcześniejszych wierszy, a rowspan nie wystaje poza grupę. Wiersze bez
    zmian zostają dosłownie.
    """
    rows = [list(_CELL_HTML.finditer(h)) for h in rows_html]
    if not group or not any(_span_of(c.group(2), "rowspan") > 1 for row in rows for c in row):
        return [rows_html[i] for i in group]
    first, last = group[0], group[-1]
    if list(group) != list(range(first, last + 1)):
        return [rows_html[i] for i in group]
    occupied: set[tuple[int, int]] = set()
    placed: list[list[tuple[int, re.Match[str], int]]] = []  # (kolumna, komórka, rowspan)
    for r, row in enumerate(rows[: last + 1]):
        column, cells = 0, []
        for cell in row:
            while (r, column) in occupied:
                column += 1
            colspan = _span_of(cell.group(2), "colspan")
            rowspan = _span_of(cell.group(2), "rowspan")
            for dr in range(rowspan):
                for dc in range(colspan):
                    occupied.add((r + dr, column + dc))
            cells.append((column, cell, rowspan))
            column += colspan
        placed.append(cells)
    out: list[str] = []
    for r in group:
        own: list[tuple[int, str, bool]] = [
            (c, _with_rowspan(m, last - r + 1), True)
            if rs > last - r + 1
            else (c, m.group(0), False)
            for c, m, rs in placed[r]
        ]
        carried: list[tuple[int, str, bool]] = []
        if r == first:
            carried = [
                (c, _with_rowspan(m, min(origin + rs, last + 1) - first), True)
                for origin in range(first)
                for c, m, rs in placed[origin]
                if origin + rs > first
            ]
        opening = _TR_OPEN.match(rows_html[r])
        if not any(changed for *_, changed in own + carried) or opening is None:
            out.append(rows_html[r])
            continue
        merged = sorted(own + carried, key=lambda x: x[0])
        out.append(opening.group(0) + "".join(html_ for _, html_, _ in merged) + "</tr>")
    return out


def _split_html(t: TableData, group: list[int]) -> str:
    body = "".join(split_rows_html(t.rows_html, group))
    return "<table>" + t.header_html + "<tbody>" + body + "</tbody></table>"


def _group_drafts(  # noqa: PLR0913
    t: TableData,
    block: Block,
    group: list[int],
    cfg: ChunkConfig,
    *,
    bc: str,
    bc_html: str,
    lines: Lines,
) -> list[ChunkDraft]:
    """Drafty jednej grupy; samotny wiersz ponad limit dzielony split_to_limit (C7 pkt 3)."""
    row_text_all = _group_text(t, group, cfg.html4excel, lines)
    fragment = bc_html + _split_html(t, group)
    if len(group) == 1 and cfg.count_tokens(bc + row_text_all) > cfg.chunk_token_num:
        logger.warning("table row split", extra={"tokens": cfg.count_tokens(bc + row_text_all)})
        limit = cfg.chunk_token_num - cfg.count_tokens(bc)
        pieces = split_to_limit(row_text_all, limit, cfg.count_tokens)
        return [_draft(block, bc + piece, fragment, cfg) for piece in pieces]
    return [_draft(block, bc + row_text_all, fragment, cfg)]


def chunk_table(
    block: Block, cfg: ChunkConfig, lead: str = "", heads: frozenset[str] = frozenset()
) -> list[ChunkDraft]:
    """Tabela → drafty (C7): jeden draft w limicie, inaczej dzielenie po wierszach.

    ``lead`` (zdanie wprowadzające z jednostką) trafia za breadcrumb do każdego draftu tabeli.
    """
    bc = _bc_text(block.heading_path) + (lead + "\n" if lead else "")
    bc_html = _bc_html(block.heading_path) + (
        f'<p class="table-lead">{html.escape(lead)}</p>' if lead else ""
    )
    if block.table is None:
        return [_draft(block, bc + block.text, bc_html + block.html, cfg)]
    t = block.table
    lines = [] if cfg.html4excel else table_lines(t, heads)
    whole = bc + _group_text(t, range(len(t.rows)), cfg.html4excel, lines)
    if cfg.count_tokens(whole) <= cfg.chunk_token_num:
        return [_draft(block, whole, bc_html + block.html, cfg)]
    drafts: list[ChunkDraft] = []
    for group in _row_groups(t, bc, cfg, lines):
        if not cfg.html4excel and not any(lines[i] for i in group):
            continue  # same wiersze-tłumaczenia
        drafts.extend(_group_drafts(t, block, group, cfg, bc=bc, bc_html=bc_html, lines=lines))
    return drafts
