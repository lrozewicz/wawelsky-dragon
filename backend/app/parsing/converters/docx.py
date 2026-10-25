"""Konwerter DOCX (kontrakt C8) — mammoth do HTML, metadane z python-docx."""

from __future__ import annotations

from pathlib import Path

import docx
import mammoth

from app.parsing.converters.common import check_zip, finish
from app.parsing.html import promote_table_headers
from app.parsing.types import ConvertedDocument, ConvertOptions

# Domyślna mapa mammoth nie zna stylu Title — dopinamy go na h1 (C8).
_STYLE_MAP = "p[style-name='Title'] => h1:fresh"


def convert_docx(path: Path, opts: ConvertOptions) -> ConvertedDocument:
    """DOCX → znormalizowany HTML; obrazy pomijane, tabele z thead, metadane title/author."""
    check_zip(path, "docx", opts)
    with path.open("rb") as fileobj:
        result = mammoth.convert_to_html(
            fileobj,
            style_map=_STYLE_MAP,
            convert_image=mammoth.images.img_element(lambda _image: {}),
        )
    properties = docx.Document(str(path)).core_properties
    metadata: dict[str, str] = {}
    if properties.title:
        metadata["title"] = properties.title
    if properties.author:
        metadata["author"] = properties.author
    return finish(
        promote_table_headers(result.value),
        diagnosis="document has no text",
        metadata=metadata,
    )
