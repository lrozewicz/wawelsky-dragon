"""Sanityzacja i budowa HTML (kontrakt C3, 05 §7) — własna implementacja na lxml."""

from __future__ import annotations

import html as _html
import re
import unicodedata
from collections.abc import Sequence
from typing import Literal

import lxml.html
from lxml import etree

# Whitelist 05 §7: dozwolone tagi, atrybuty per tag, tagi usuwane z zawartością.
ALLOWED_TAGS: frozenset[str] = frozenset(
    {
        "section",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "p",
        "ul",
        "ol",
        "li",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "pre",
        "code",
        "figure",
        "figcaption",
        "aside",
        "br",
        "strong",
        "em",
        "a",
    }
)
ALLOWED_ATTRS: dict[str, frozenset[str]] = {
    "section": frozenset({"data-page", "data-slide", "data-sheet"}),
    "p": frozenset({"data-bbox"}),
    "table": frozenset({"data-bbox"}),
    "th": frozenset({"colspan", "rowspan"}),
    "td": frozenset({"colspan", "rowspan"}),
    "figure": frozenset({"data-image"}),
    "aside": frozenset({"data-notes"}),
    "a": frozenset({"href"}),
}
DROP_WITH_CONTENT: frozenset[str] = frozenset(
    {
        "script",
        "style",
        "noscript",
        "template",
        "iframe",
        "object",
        "embed",
        "head",
        "title",
        "svg",
        "math",
    }
)

_RENAMES = {"b": "strong", "i": "em", "tfoot": "tbody"}
_SAFE_HREF_PREFIXES = ("http://", "https://", "mailto:", "/", "#")
_SECTION_ATTRS = {"page": "data-page", "slide": "data-slide", "sheet": "data-sheet"}
_PARAGRAPH_SPLIT = re.compile(r"\n[ \t]*\n+")
_MULTI_SPACE = re.compile(r" {2,}")
# Znaki kategorii Cc usuwane poza wyjątkami z C3 (\n, \t, U+FEFF — ten ostatni jest Cf).
_KEEP_CTRL = ("\n", "\t", "\ufeff")
# Tabela bez thead promuje pierwszy wiersz dopiero od tej liczby wierszy (C3).
_MIN_ROWS_FOR_HEADER = 2


def normalize_text(text: str, *, pre: bool = False) -> str:
    """NFC, \r\n/\r → \n, bez znaków sterujących; bez `pre` też NBSP→spacja i redukcja spacji."""
    s = unicodedata.normalize("NFC", text)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = "".join(c for c in s if c in _KEEP_CTRL or unicodedata.category(c) != "Cc")
    if not pre:
        s = s.replace("\u00a0", " ")
        s = _MULTI_SPACE.sub(" ", s)
    return s


def esc(text: str) -> str:
    """Escapowanie tekstu do HTML z wcześniejszą normalizacją."""
    return _html.escape(normalize_text(text), quote=True)


def _parse(html: str) -> lxml.html.HtmlElement:
    """Fragment → korzeń-`div`; pełny dokument (`<html`/`<body`/doctype) → element `<body>`."""
    low = html.lstrip().lower()
    if low.startswith("<!doctype") or "<html" in low or "<body" in low:
        doc = lxml.html.document_fromstring(html)
        body = doc.find("body")
        return body if body is not None else doc
    return lxml.html.fragment_fromstring(html, create_parent="div")


def _in_root(el: object, root: lxml.html.HtmlElement) -> bool:
    """Czy element wciąż należy do drzewa korzenia (inne padły z `drop_tree` rodzica)."""
    return any(anc is root for anc in el.iterancestors())  # type: ignore[attr-defined]


def _href_ok(value: str) -> bool:
    v = value.strip().lower()
    return v.startswith(_SAFE_HREF_PREFIXES) or ":" not in v


def sanitize_html(html: str) -> str:
    """Whitelist tagów/atrybutów 05 §7 + normalizacja tekstu; puste elementy zostają."""
    if html == "":
        return ""
    root = _parse(html)
    for el in list(root.iter()):
        if el is not root and not _in_root(el, root):
            continue  # poddrzewo usunięte wcześniej razem z przodkiem
        if el.tag is etree.Comment or el.tag is etree.ProcessingInstruction:
            el.drop_tree()
            continue
        if el is root:
            continue  # sztuczny div/body — nigdy nie rozbierany
        tag = el.tag if isinstance(el.tag, str) else ""
        if tag in DROP_WITH_CONTENT:
            el.drop_tree()
            continue
        if tag in _RENAMES:
            el.tag = _RENAMES[tag]
            tag = el.tag
        if tag == "aside" and "data-notes" not in el.attrib:
            el.drop_tag()
            continue
        if tag not in ALLOWED_TAGS:
            el.drop_tag()
            continue
        allowed = ALLOWED_ATTRS.get(tag, frozenset())
        for attr in list(el.attrib):
            bad_href = tag == "a" and attr == "href" and not _href_ok(el.attrib[attr])
            if attr not in allowed or bad_href:
                del el.attrib[attr]
    _normalize_texts(root)
    return _serialize_children(root)


def _normalize_texts(root: lxml.html.HtmlElement) -> None:
    """Normalizuje tekst i tail wszystkich elementów; wewnątrz `pre` bez redukcji spacji."""
    if root.text:
        root.text = normalize_text(root.text)
    for el in root.iter():
        if el is root:
            continue
        ancestors_pre = any(a.tag == "pre" for a in el.iterancestors())
        if el.text:
            el.text = normalize_text(el.text, pre=el.tag == "pre" or ancestors_pre)
        if el.tail:  # tail jest na poziomie rodzica — w pre tylko gdy przodek jest pre
            el.tail = normalize_text(el.tail, pre=ancestors_pre)


def _serialize_children(root: lxml.html.HtmlElement) -> str:
    """Skleja tekst początkowy z serializacją dzieci korzenia (bez tagu korzenia)."""
    parts = [root.text or ""]
    for child in root:
        parts.append(lxml.html.tostring(child, encoding="unicode", method="html"))
        parts.append(child.tail or "")
    return "".join(parts)


def paragraphs_html(text: str) -> str:
    """Akapity z tekstu: pusta linia dzieli, pojedynczy \n → <br>."""
    out: list[str] = []
    for raw_block in _PARAGRAPH_SPLIT.split(normalize_text(text)):
        block = raw_block.strip()
        if not block:
            continue
        lines = (esc(line) for line in block.split("\n"))
        out.append("<p>" + "<br>".join(lines) + "</p>")
    return "".join(out)


def table_html(
    rows: Sequence[Sequence[str]], *, header_rows: int = 1, bbox: str | None = None
) -> str:
    """Tabela HTML; krótsze wiersze dopełniane pustymi komórkami, komórki przez esc."""
    if not rows:
        return ""
    width = max(len(row) for row in rows)

    def _row(row: Sequence[str], tag: str) -> str:
        cells = "".join(f"<{tag}>{esc(cell)}</{tag}>" for cell in row)
        cells += f"<{tag}></{tag}>" * (width - len(row))
        return f"<tr>{cells}</tr>"

    head = "".join(_row(row, "th") for row in rows[:header_rows])
    body = "".join(_row(row, "td") for row in rows[header_rows:])
    attrs = f' data-bbox="{bbox}"' if bbox is not None else ""
    out = f"<table{attrs}>"
    if head:
        out += f"<thead>{head}</thead>"
    if body:
        out += f"<tbody>{body}</tbody>"
    return out + "</table>"


def section_html(kind: Literal["page", "slide", "sheet"], value: int | str, inner: str) -> str:
    """Sekcja strony/slajdu/arkusza z atrybutem data-*; wartość przez esc."""
    attr = _SECTION_ATTRS[kind]
    return f'<section {attr}="{esc(str(value))}">{inner}</section>'


def promote_table_headers(html: str) -> str:
    """Tabele bez <thead> i z ≥ 2 wierszami: pierwszy wiersz → thead (td→th), reszta → tbody."""
    if not html.strip():
        return ""
    root = _parse(html)
    for table in root.iter("table"):
        if table.find("thead") is not None:
            continue
        rows = [el for el in table if el.tag == "tr"]
        if len(rows) < _MIN_ROWS_FOR_HEADER:
            continue
        index = table.index(rows[0])
        for row in rows:
            table.remove(row)
        for cell in rows[0]:
            if cell.tag == "td":
                cell.tag = "th"
        thead = etree.Element("thead")
        thead.append(rows[0])
        tbody = etree.Element("tbody")
        for row in rows[1:]:
            tbody.append(row)
        table.insert(index, thead)
        table.insert(index + 1, tbody)
    return sanitize_html(_serialize_children(root))


def text_chars(html: str) -> int:
    """Liczba znaków nie-białych w treści tekstowej HTML (bez tagów)."""
    if html == "":
        return 0
    root = _parse(html)
    return sum(1 for ch in "".join(root.itertext()) if not ch.isspace())
