"""Konwertery czystego tekstu i kodu źródłowego (kontrakt C8)."""

from __future__ import annotations

import html as _html
from pathlib import Path

from app.parsing.converters.common import finish, read_bytes
from app.parsing.encoding import decode_bytes
from app.parsing.html import normalize_text, paragraphs_html
from app.parsing.types import ConvertedDocument, ConvertOptions


def convert_text(path: Path, opts: ConvertOptions) -> ConvertedDocument:
    """Tekst (.txt) → akapity `<p>`; metadane z nazwą kodowania (C5)."""
    text, encoding = decode_bytes(read_bytes(path), fmt="txt")
    return finish(
        paragraphs_html(text),
        diagnosis="file has no text",
        metadata={"encoding": encoding},
    )


def convert_code(path: Path, opts: ConvertOptions) -> ConvertedDocument:
    """Kod źródłowy → `<pre><code>` z zachowanymi spacjami; metadane z nazwą kodowania."""
    text, encoding = decode_bytes(read_bytes(path), fmt="code")
    body = _html.escape(normalize_text(text, pre=True), quote=True)
    return finish(
        f"<pre><code>{body}</code></pre>",
        diagnosis="file has no text",
        metadata={"encoding": encoding},
    )
