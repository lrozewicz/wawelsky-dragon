"""Konwerter DOC (kontrakt C8) — zewnętrzny wvHtml, wynik czyszczony jak strona WWW."""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.parsing.converters.common import finish, run_binary
from app.parsing.converters.html_in import clean_html_document
from app.parsing.types import ConvertedDocument, ConvertOptions


def convert_doc(path: Path, opts: ConvertOptions) -> ConvertedDocument:
    """Starszy .doc → HTML przez wvHtml; `out.html` czytany jako bajty i czyszczony (C8a)."""
    with tempfile.TemporaryDirectory() as tmp:
        run_binary("wvHtml", [f"--targetdir={tmp}", str(path), "out.html"], fmt="doc")
        html, metadata = clean_html_document((Path(tmp) / "out.html").read_bytes())
    return finish(html, diagnosis="document has no text", metadata=metadata)
