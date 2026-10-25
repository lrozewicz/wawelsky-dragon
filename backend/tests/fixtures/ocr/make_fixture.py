# ruff: noqa: E402 — ścieżka repo dokładana do sys.path przed importami `app`/`tests`
"""Generator fixture OCR dla profilu OTSL (WP E5-H4a T4).

Skrypt uruchamiany z katalogu `backend/`:

    uv run python tests/fixtures/ocr/make_fixture.py

Tworzy deterministyczny 1-stronicowy PDF A4 z tytułem „TABL. 1" i ASCII-tabelą
dwupoziomową (nagłówek „SPEC" | „2022" | „2023"; podnagłówek „ogolem"/„kobiety"), a
następnie renderuje stronę 1 DOKŁADNIE tak, jak robi to pipeline (`VISION_DPI`,
`pypdfium2` + `png_bytes`) i liczy `sha256(png)[:8]`. Wynik zapisuje do
`tools/fake-llm/fixtures/ocr.json` jako `{sha8: "<markdown z OTSL>"}` — model `fake-ocr`
zwraca ten OTSL dosłownie dla tego obrazu (K10 poprawka 2026-10-04b).

Warstwa tekstowa PDF nie wpływa na wynik (profil OTSL renderuje stronę, nie czyta tekstu);
służy tylko determinizmowi PNG. Zmiana wersji `pypdfium2`/`Pillow` zmienia PNG i wymaga
ponownego uruchomienia tego skryptu — pilnuje tego `tests/unit/parsing/test_ocr_fixture.py`.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = FIXTURE_DIR.parents[2]
REPO_ROOT = FIXTURE_DIR.parents[3]
PDF_PATH = FIXTURE_DIR / "two_level_table.pdf"
OCR_JSON_PATH = REPO_ROOT / "tools" / "fake-llm" / "fixtures" / "ocr.json"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pypdfium2

from app.parsing.converters.common import png_bytes
from app.parsing.types import VISION_DPI
from tests.unit.parsing.factories import PdfPage, PdfText, make_pdf

# Tytuł i ASCII-tabela dwupoziomowa rysowane tekstami (pozycje w pt od górnej krawędzi).
_TEXTS = (
    PdfText(x=50, top=40, size=14, text="TABL. 1"),
    PdfText(x=50, top=90, size=11, text="SPEC"),
    PdfText(x=170, top=90, size=11, text="2022"),
    PdfText(x=380, top=90, size=11, text="2023"),
    PdfText(x=170, top=110, size=11, text="ogolem"),
    PdfText(x=270, top=110, size=11, text="kobiety"),
    PdfText(x=380, top=110, size=11, text="ogolem"),
    PdfText(x=480, top=110, size=11, text="kobiety"),
    PdfText(x=50, top=130, size=11, text="15-24 lata"),
    PdfText(x=170, top=130, size=11, text="10,8"),
    PdfText(x=270, top=130, size=11, text="11,3"),
    PdfText(x=380, top=130, size=11, text="11,3"),
    PdfText(x=480, top=130, size=11, text="11,1"),
)

# OTSL zwracany przez fake-ocr dla wyrenderowanej strony (nagłówek dwupoziomowy lcel/ucel).
OCR_MARKDOWN = (
    "TABL. 1\n\n"
    "<fcel>SPEC<fcel>2022<lcel><fcel>2023<lcel><nl>"
    "<ucel><fcel>ogolem<fcel>kobiety<fcel>ogolem<fcel>kobiety<nl>"
    "<fcel>15-24 lata<fcel>10,8<fcel>11,3<fcel>11,3<fcel>11,1<nl>\n"
)


def render_page_png(pdf_path: Path, page_index: int = 0) -> bytes:
    """Renderuje stronę jak pipeline (VISION_DPI + pypdfium2 + `png_bytes`)."""
    pdf = pypdfium2.PdfDocument(pdf_path)
    try:
        page = pdf[page_index]
        try:
            image = page.render(scale=VISION_DPI / 72).to_pil()
        finally:
            page.close()
    finally:
        pdf.close()
    return png_bytes(image)


def main() -> None:
    """Buduje PDF, renderuje stronę, zapisuje PDF i `ocr.json`; wypisuje sha8."""
    PDF_PATH.write_bytes(make_pdf([PdfPage(texts=_TEXTS, width=595.0, height=842.0)]))
    png = render_page_png(PDF_PATH)
    sha8 = hashlib.sha256(png).hexdigest()[:8]
    OCR_JSON_PATH.write_text(
        json.dumps({sha8: OCR_MARKDOWN}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"{PDF_PATH.name}: sha8={sha8} → {OCR_JSON_PATH}")


if __name__ == "__main__":
    main()
