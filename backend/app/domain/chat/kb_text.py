"""Konwersja HTML z ``content_llm`` na tekst bloku wiedzy promptu czatu (CONTRACT WP E4-7c).

Czysta funkcja domenowa na stdlib ``html.parser`` (bez importów app.*). Tabele
``<table>…</table>`` zostają dosłownie jako HTML (jak upstream), reszta znaczników znika.
"""

from html import unescape
from html.parser import HTMLParser

# Elementy blokowe: kończą/otwierają linię (CONTRACT, reguła 1).
_BLOCK_TAGS = frozenset(
    {
        "p",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "div",
        "br",
        "li",
        "ul",
        "ol",
        "section",
        "blockquote",
    }
)
_LIST_TAG = "li"
_TABLE_TAG = "table"


class _KbTextParser(HTMLParser):
    """Zbiera linie tekstu; poza tabelami usuwa tagi, wewnątrz przepisuje dosłownie."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.lines: list[str] = []
        self._cur: list[str] = []
        self._prefix = ""
        self._table_depth = 0
        self._table: list[str] = []

    def _flush(self) -> None:
        text = "".join(self._cur).strip()
        self._cur = []
        if text:
            self.lines.append(self._prefix + text)
        self._prefix = ""

    def _in_table(self) -> bool:
        return self._table_depth > 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._in_table():
            if tag == _TABLE_TAG:
                self._table_depth += 1
            self._table.append(self.get_starttag_text() or "")
            return
        if tag == _TABLE_TAG:
            self._flush()
            self._table_depth = 1
            self._table = [self.get_starttag_text() or ""]
            return
        if tag in _BLOCK_TAGS:
            self._flush()
            if tag == _LIST_TAG:
                self._prefix = "- "

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._in_table():
            self._table.append(self.get_starttag_text() or "")
            return
        if tag in _BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if self._in_table():
            if tag == _TABLE_TAG:
                self._table_depth -= 1
            self._table.append("</" + tag + ">")
            if self._table_depth == 0:
                self.lines.append("".join(self._table))
                self._table = []
            return
        if tag in _BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._in_table():
            self._table.append(data)
            return
        parts = data.split("\n")
        self._cur.append(parts[0])
        for part in parts[1:]:
            self._flush()
            self._cur.append(part)

    def handle_entityref(self, name: str) -> None:
        if self._in_table():
            self._table.append("&" + name + ";")
            return
        self._cur.append(unescape("&" + name + ";"))

    def handle_charref(self, name: str) -> None:
        if self._in_table():
            self._table.append("&#" + name + ";")
            return
        self._cur.append(unescape("&#" + name + ";"))

    def finish(self) -> str:
        self._flush()
        if self._table_depth:
            self.lines.append("".join(self._table))
            self._table = []
            self._table_depth = 0
        return "\n".join(self.lines)


def kb_text(content_llm: str) -> str:
    """Tekst bez HTML (tabele dosłownie); pusty wynik → "" (fallback u wywołującego)."""
    parser = _KbTextParser()
    parser.feed(content_llm)
    parser.close()
    return parser.finish()
