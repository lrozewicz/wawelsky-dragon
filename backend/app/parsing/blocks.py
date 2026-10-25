"""html_to_blocks — znormalizowany HTML (05 §7) na listę Block (CONTRACT WP E1-5 C11)."""

import re
from html import escape
from html.parser import HTMLParser

from app.domain.chunking.types import Block, BlockKind, Position, TableData
from app.parsing.table_grid import cell_span, linearize

_VOID = frozenset({"br", "img", "hr"})
_INVISIBLE = frozenset({"script", "style"})
_CONTAINERS = frozenset({"div", "body"})
_HEADING_LEVELS: dict[str, int] = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_BLOCK_TAGS = frozenset(_HEADING_LEVELS) | {"p", "ul", "ol", "table", "pre", "figure", "aside"}
_KINDS: dict[str, BlockKind] = {
    "p": "paragraph",
    "ul": "list",
    "ol": "list",
    "table": "table",
    "pre": "code",
    "figure": "figure",
    "aside": "notes",
}
_BBOX_PARTS = 4
_MIN_PAGE = 1
_INDENT = "  "
_CELL_SEPARATOR = " | "
_WS_RUN = re.compile(r"[^\S\n]+")
_WS_ALL = re.compile(r"\s+")

_Bbox = tuple[int, int, int, int]
_Row = tuple[tuple[str, ...], str, tuple[tuple[int, int], ...]]  # komórki, <tr>, (colspan, rowspan)
_SectionState = tuple[str | None, int | None]  # (nazwa sekcji, strona dla positions)
_Sink = tuple[list[str], str, bool]  # kawałki tekstu, wstawka za <br>, tryb dosłowny (pre)
_Item = tuple[list[str], list[str]]  # element listy: kawałki tekstu + wiersze podlisty
_ListLevel = tuple[bool, list[_Item]]  # ramka listy: numerowana (ol) + jej elementy


def _attr(attrs: list[tuple[str, str | None]], name: str) -> str | None:
    """Wartość pierwszego atrybutu o podanej nazwie (kolejność źródła)."""
    for key, value in attrs:
        if key == name:
            return value
    return None


def _parse_page(value: str | None) -> int | None:
    """int >= 1 albo None (niepoprawna liczba traktowana jak brak)."""
    if value is None:
        return None
    try:
        page = int(value)
    except ValueError:
        return None
    return page if page >= _MIN_PAGE else None


def _parse_bbox(value: str | None) -> _Bbox | None:
    """data-bbox="x0,y0,x1,y1" -> zaokrąglone (x0, x1, y0, y1); zły format -> None."""
    if value is None:
        return None
    parts = value.split(",")
    if len(parts) != _BBOX_PARTS:
        return None
    try:
        floats = [float(part) for part in parts]
    except ValueError:
        return None
    x0, y0, x1, y1 = floats
    return (round(x0), round(x1), round(y0), round(y1))


def _start_html(tag: str, attrs: list[tuple[str, str | None]]) -> str:
    """Serializacja znacznika otwierającego (atrybuty w kolejności źródła, None -> "")."""
    rendered = "".join(f' {key}="{escape(value or "", quote=True)}"' for key, value in attrs)
    return f"<{tag}{rendered}>"


def _norm_text(parts: list[str]) -> str:
    """Kawałki tekstu (dane ze zredukowanymi białymi znakami, <br> jako "\\n");
    zredukuj powtórzone spacje, przytnij każdą linię i całość."""
    collapsed = _WS_RUN.sub(" ", "".join(parts))
    return "\n".join(line.strip() for line in collapsed.split("\n")).strip()


def _parse_section(attrs: list[tuple[str, str | None]]) -> _SectionState:
    """data-page -> "page:n" (+ strona), data-slide -> "slide:n", data-sheet -> "sheet:nazwa"."""
    page = _parse_page(_attr(attrs, "data-page"))
    if page is not None:
        return (f"page:{page}", page)
    slide = _parse_page(_attr(attrs, "data-slide"))
    if slide is not None:
        return (f"slide:{slide}", None)
    sheet = _attr(attrs, "data-sheet")
    return (f"sheet:{sheet}", None) if sheet else (None, None)


class _Parser(HTMLParser):
    """Parser zdarzeń HTML na Blocki; cały stan w polach instancji (determinizm)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[Block] = []
        self._headings: list[tuple[int, str]] = []
        self._sections: list[_SectionState] = []
        self._caps: list[list[str]] = []  # stos aktywnych serializacji: blok > thead > tr
        self._implicit: _Sink = ([], "\n", False)  # tekst poza blokami (niejawne akapity)
        self._sink: _Sink | None = None  # zlew wewnętrzny bloku (li/komórka/figcaption)
        self._invisible = False  # wewnątrz script/style
        self._btag: str | None = None  # znacznik otwartego bloku; None — poza blokiem
        self._blevel: int | None = None
        self._bbbox: _Bbox | None = None
        self._bparts: list[str] = []  # kawałki tekstu bloków h/p/aside/pre
        self._bfig: list[str] | None = None  # kawałki tekstu figcaption
        self._t_rows: list[_Row] = []
        self._t_cells: list[str] | None = None
        self._t_spans: list[tuple[int, int]] = []
        self._t_pending_span: tuple[int, int] = (1, 1)
        self._t_tr_cap: list[str] | None = None
        self._t_in_thead = False
        self._t_thead_rows: list[_Row] | None = None
        self._t_thead: list[_Row] | None = None
        self._t_thead_cap: list[str] | None = None
        self._t_thead_html = ""
        self._lists: list[_ListLevel] = []
        self._list_lines: list[str] | None = None

    def _out(self, piece: str) -> None:
        """Serializuj fragment do wszystkich aktywnych buforów."""
        for cap in self._caps:
            cap.append(piece)

    def _target(self) -> _Sink | None:
        """Dokąd płynie tekst: poza blokiem zlew niejawny, w bloku zlew wewnętrzny."""
        return self._implicit if self._btag is None else self._sink

    def _heading_path(self) -> tuple[str, ...]:
        return tuple(text for _, text in self._headings)

    def _positions(self, bbox: _Bbox | None) -> tuple[Position, ...]:
        """Pozycje RAGFlow [strona, lewo, prawo, góra, dół]; poza data-page — ()."""
        page = self._sections[-1][1] if self._sections else None
        if page is None:
            return ()
        if bbox is None:
            return ((page, 0, 0, 0, 0),)
        x0, x1, y0, y1 = bbox
        return ((page, x0, x1, y0, y1),)

    def _flush_implicit(self) -> None:
        """Zamknij niejawny akapit (tekst poza blokami), jeśli coś zebrał."""
        text = _norm_text(self._implicit[0])
        self._implicit = ([], "\n", False)
        if not text:
            return
        section = self._sections[-1][0] if self._sections else None
        html = f"<p>{escape(text, quote=False)}</p>"
        path = self._heading_path()
        positions = self._positions(None)
        self.blocks.append(Block("paragraph", text, html, None, path, positions, section, None))

    # -- zdarzenia --

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _INVISIBLE:
            self._invisible = True
        elif tag in _VOID:
            self._out(_start_html(tag, attrs))
            if tag == "br" and (target := self._target()) is not None:
                target[0].append(target[1])
        elif self._btag is None and tag in _BLOCK_TAGS:
            self._start_block(tag, attrs)
        elif self._start_table_part(tag, attrs):
            pass
        else:
            self._out(_start_html(tag, attrs))
            if self._btag is None:
                if tag == "section":
                    self._sections.append(_parse_section(attrs))
            else:  # div/body/strong/em/a/… — przezroczyste
                self._start_inner(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if self._invisible:  # CDATA script/style kończy wyłącznie własny znacznik domknięcia
            self._invisible = tag in _INVISIBLE
            return
        if tag in _VOID:
            return
        self._out(f"</{tag}>")
        if tag in ("ul", "ol") and self._lists:
            if len(self._lists) == 1:  # końcowy znacznik listy blokowej
                self._finalize_block(tag)
            else:
                self._pop_frame()
            return
        if self._btag is not None and tag == self._btag:
            self._finalize_block(tag)
        elif self._end_table_part(tag) or self._end_inner(tag):
            pass
        elif self._btag is None:
            if tag == "section" and self._sections:
                self._flush_implicit()  # koniec kontenera kończy niejawny akapit
                self._sections.pop()
            elif tag in _CONTAINERS:
                self._flush_implicit()

    def handle_data(self, data: str) -> None:
        if self._invisible:
            return
        self._out(escape(data, quote=False))
        target = self._target()
        if target is None:
            return
        target[0].append(data if target[2] else _WS_ALL.sub(" ", data))

    def close(self) -> None:
        """Po close() domknij niejawny akapit zebrany do końca dokumentu."""
        super().close()
        self._flush_implicit()

    def _start_table_part(self, tag: str, attrs: list[tuple[str, str | None]]) -> bool:
        """thead/tr w tabeli — nowy bufor serializacji, zagnieżdżony w bloku tabeli."""
        if tag not in ("thead", "tr") or self._btag != "table":
            return False
        cap: list[str] = []
        self._caps.append(cap)
        self._out(_start_html(tag, attrs))
        if tag == "thead":
            self._t_in_thead = True
            self._t_thead_rows = []
            self._t_thead_cap = cap
        else:
            self._t_tr_cap = cap
            self._t_cells = []
            self._t_spans = []
        return True

    def _start_inner(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Znacznik wewnątrz bloku: zagnieżdżona lista, element listy, komórka, figcaption."""
        if tag in ("ul", "ol") and self._lists:
            self._lists.append((tag == "ol", []))
        elif tag == "li" and self._lists:
            parts: list[str] = []
            self._lists[-1][1].append((parts, []))
            self._sink = (parts, "\n", False)
        elif tag in ("th", "td") and self._t_cells is not None:
            self._t_pending_span = cell_span(attrs)
            self._sink = ([], " ", False)
        elif tag == "figcaption" and self._btag == "figure" and self._bfig is None:
            parts = []
            self._bfig = parts
            self._sink = (parts, "\n", False)

    def _end_table_part(self, tag: str) -> bool:
        """Koniec thead/tr w tabeli: ustal nagłówek (thead z tr) albo dopisz wiersz."""
        if tag == "thead" and self._t_thead_rows is not None:
            cap, rows = self._t_thead_cap, self._t_thead_rows
            self._caps.pop()
            self._t_in_thead = False
            self._t_thead_rows = None
            self._t_thead_cap = None
            if rows and cap is not None:  # thead z co najmniej jednym tr
                self._t_thead = rows
                self._t_thead_html = "".join(cap)
            return True
        if tag == "tr" and self._t_tr_cap is not None:
            row: _Row = (tuple(self._t_cells or ()), "".join(self._t_tr_cap), tuple(self._t_spans))
            self._caps.pop()
            self._t_tr_cap = None
            self._t_cells = None
            if self._t_in_thead and self._t_thead_rows is not None:
                self._t_thead_rows.append(row)
            else:
                self._t_rows.append(row)
            return True
        return False

    def _end_inner(self, tag: str) -> bool:
        """Koniec li/komórki/figcaption — zamknij zlew tekstu (komórka trafia do wiersza)."""
        if tag in ("th", "td") and self._sink is not None and self._t_cells is not None:
            self._t_cells.append(_WS_ALL.sub(" ", "".join(self._sink[0])).strip())
            self._t_spans.append(self._t_pending_span)
            self._sink = None
            return True
        if tag == "li" and self._lists and self._sink is not None:
            self._sink = None
            return True
        if tag == "figcaption" and self._btag == "figure" and self._sink is not None:
            self._sink = None
            return True
        return False

    def _start_block(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Nowy blok najwyższego poziomu; najpierw domknij niejawny akapit."""
        self._flush_implicit()
        self._t_rows = []
        self._t_cells = None
        self._t_tr_cap = None
        self._t_in_thead = False
        self._t_thead_rows = None
        self._t_thead = None
        self._t_thead_cap = None
        self._t_thead_html = ""
        self._lists = []
        self._list_lines = None
        cap: list[str] = []
        self._caps.append(cap)
        self._out(_start_html(tag, attrs))
        self._blevel = _HEADING_LEVELS.get(tag)
        self._bparts = []
        if self._blevel is not None or tag in ("p", "aside", "pre"):
            self._sink = (self._bparts, "\n", tag == "pre")
        else:
            self._sink = None
        self._bfig = None
        self._bbbox = _parse_bbox(_attr(attrs, "data-bbox"))
        self._btag = tag
        if tag in ("ul", "ol"):
            self._lists = [(tag == "ol", [])]

    def _pop_frame(self) -> None:
        """Zamknij ramkę listy: wyrenderuj wiersze do bloku albo elementu-rodzica."""
        ordered, items = self._lists.pop()
        depth = len(self._lists)
        lines: list[str] = []
        for number, (parts, sub) in enumerate(items, start=1):
            prefix = f"{number}. " if ordered else "- "
            lines.append(_INDENT * depth + prefix + _norm_text(parts))
            lines.extend(sub)
        if depth == 0:
            self._list_lines = lines
        elif self._lists[-1][1]:  # zagnieżdżona — dopisz do ostatniego elementu rodzica
            self._lists[-1][1][-1][1].extend(lines)

    def _table_data(self) -> tuple[TableData, str]:
        """TableData i tekst bloku tabeli (nagłówek z thead albo z pierwszego tr)."""
        header_rows: list[_Row]
        body_rows: list[_Row]
        if self._t_thead is not None:
            header_rows, header_html, body_rows = self._t_thead, self._t_thead_html, self._t_rows
        elif self._t_rows:
            header_rows = [self._t_rows[0]]
            header_html = f"<thead>{self._t_rows[0][1]}</thead>"
            body_rows = self._t_rows[1:]
        else:
            header_rows, header_html, body_rows = [], "", []
        header, rows = linearize(header_rows, body_rows)
        lines = [_CELL_SEPARATOR.join(header)] if header else []
        lines.extend(_CELL_SEPARATOR.join(row[0]) for row in body_rows)
        table = TableData(
            header=header,
            rows=rows,
            header_html=header_html,
            rows_html=tuple(row[1] for row in body_rows),
        )
        return table, "\n".join(lines)

    def _finalize_block(self, tag: str) -> None:
        """Zamknij blok: oceń tekst, pomiń pusty, w przeciwnym razie dopisz do wyniku."""
        self._btag = None
        self._sink = None
        html = "".join(self._caps.pop())
        while self._lists:  # niedomknięte ramki listy — domykanie od środka
            self._pop_frame()
        positions = self._positions(self._bbbox)
        section = self._sections[-1][0] if self._sections else None
        level = self._blevel
        if level is not None:
            text = _norm_text(self._bparts)
            if not text:  # pusty nagłówek nie tworzy bloku i nie zmienia ścieżki
                return
            while self._headings and self._headings[-1][0] >= level:
                self._headings.pop()
            path = self._heading_path()
            self._headings.append((level, text))
            self.blocks.append(Block("heading", text, html, level, path, positions, section, None))
            return
        table: TableData | None = None
        if tag == "table":
            table, text = self._table_data()
        elif tag in ("ul", "ol"):
            text = "\n".join(self._list_lines or [])
        elif tag == "figure":
            text = _norm_text(self._bfig or [])
        elif tag == "pre":
            text = "".join(self._bparts).strip("\n")
        else:  # p, aside
            text = _norm_text(self._bparts)
        if not text:
            return
        path = self._heading_path()
        self.blocks.append(Block(_KINDS[tag], text, html, None, path, positions, section, table))


def html_to_blocks(html: str) -> list[Block]:
    """Parsuj znormalizowany HTML (05 §7) na listę Block (CONTRACT WP E1-5 C11)."""
    parser = _Parser()
    parser.feed(html)
    parser.close()
    return parser.blocks
