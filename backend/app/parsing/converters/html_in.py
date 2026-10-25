"""Konwerter HTML (kontrakt C8, C8a) — czyszczenie dokumentu z szumu i banerów zgód."""

from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup, Tag

from app.parsing.converters.common import finish, read_bytes
from app.parsing.html import promote_table_headers
from app.parsing.types import ConvertedDocument, ConvertOptions

_DROP_TAGS = frozenset({"script", "style", "nav", "footer", "aside", "header", "form", "noscript"})
_BANNER_MARKERS = ("cookie", "consent", "gdpr")


def _attribute_hits(el: Tag, attr: str) -> list[str]:
    """Wartości atrybutu jako lista (bs4: `id` to tekst, `class` to lista klas)."""
    value = el.get(attr)
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def _is_banner(el: Tag) -> bool:
    """Baner zgody: id lub dowolna klasa zawiera cookie/consent/gdpr (case-insensitive)."""
    parts = _attribute_hits(el, "id") + _attribute_hits(el, "class")
    return any(marker in part.lower() for part in parts for marker in _BANNER_MARKERS)


def clean_html_document(data: bytes | str) -> tuple[str, dict[str, str]]:
    """Usuwa szum (C8a): skrypty, nawigację, banery zgód; zwraca (czysty HTML, metadane)."""
    soup = BeautifulSoup(data, "lxml")
    for el in list(soup.find_all(True)):
        if el.decomposed:
            continue  # rodzic usunięty wcześniej razem z poddrzewem
        if el.name in _DROP_TAGS or _is_banner(el):
            el.decompose()
    metadata: dict[str, str] = {}
    if soup.title is not None:
        title = soup.title.get_text().strip()
        if title:
            metadata["title"] = title
    return promote_table_headers(str(soup.body or soup)), metadata


def convert_html(path: Path, opts: ConvertOptions) -> ConvertedDocument:
    """Plik HTML → znormalizowany HTML (C8a); bajty — bs4 respektuje `<meta charset>`."""
    html, metadata = clean_html_document(read_bytes(path))
    return finish(html, diagnosis="page has no text", metadata=metadata)
