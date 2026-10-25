"""Konwerter Markdown (kontrakt C8) — front-matter + render markdown-it-py."""

from __future__ import annotations

from pathlib import Path

from markdown_it import MarkdownIt

from app.parsing.converters.common import finish, read_bytes
from app.parsing.encoding import decode_bytes
from app.parsing.types import ConvertedDocument, ConvertOptions

_MD = MarkdownIt("commonmark").enable("table")


def _front_matter(text: str) -> tuple[dict[str, str], str]:
    """Rozdziela front-matter (`---` … `---`) od treści; bez zamknięcia — całość to treść."""
    lines = text.split("\n")
    if lines[0].strip() != "---":
        return {}, text
    metadata: dict[str, str] = {}
    for nr, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return metadata, "\n".join(lines[nr + 1 :])
        key, sep, value = line.partition(":")
        if not sep:
            continue  # linia bez `klucz: wartość` nie jest metadaną
        metadata[key.strip()] = value.strip().strip("\"'")
    return {}, text  # brak zamykającego `---` — bez metadanych


def convert_markdown(path: Path, opts: ConvertOptions) -> ConvertedDocument:
    """Markdown → znormalizowany HTML; metadane z front-matter."""
    data = read_bytes(path)
    text, _ = decode_bytes(data, fmt="md")
    metadata, content = _front_matter(text)
    return finish(_MD.render(content), diagnosis="document has no text", metadata=metadata)
