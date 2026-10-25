"""Spójność fixture OCR z fake-llm (WP E5-H4a T4) i determinizm renderu (WP E5-H8e T4).

Renderuje `fixtures/ocr/two_level_table.pdf` tak samo jak pipeline i sprawdza, że wyliczony
`sha8` jest kluczem w `tools/fake-llm/fixtures/ocr.json`. Rozjazd oznacza zmianę renderu
(wersja `pypdfium2`/`Pillow`) i wymaga ponownego uruchomienia `make_fixture.py`.

Klucz cache wizji liczy `sha256(image_png)` (DEC-293 p.1), więc ten sam obraz przy ponownym
renderze musi dać bajtowo identyczny PNG — inaczej trafienie w cache nigdy nie nastąpi.
"""

import hashlib
import json

import pytest

from tests.fixtures.ocr.make_fixture import (
    OCR_JSON_PATH,
    PDF_PATH,
    REPO_ROOT,
    render_page_png,
)

# Fixture e2e (SC-E5-H8e-03): PDF ≥ 50 stron używany przez cache wizji (kontrakt E5-H8e §C5).
MULTI_BATCH_PDF = REPO_ROOT / "frontend" / "e2e" / "fixtures" / "multi-batch-120.pdf"


def test_fixture_in_sync() -> None:
    """sha8 renderu strony jest kluczem w `ocr.json` (komunikat: uruchom make_fixture.py)."""
    png = render_page_png(PDF_PATH)
    sha8 = hashlib.sha256(png).hexdigest()[:8]
    data = json.loads(OCR_JSON_PATH.read_text(encoding="utf-8"))
    assert sha8 in data, (
        "sha8 strony nie zgadza się z tools/fake-llm/fixtures/ocr.json — uruchom make_fixture.py"
    )


@pytest.mark.parametrize("page_index", [0, 1, 60])
def test_render_is_byte_identical_across_repeats(page_index: int) -> None:
    """Dwa rendery tej samej strony `multi-batch-120.pdf` → ten sam sha256 PNG (DEC-293 p.1)."""
    first = render_page_png(MULTI_BATCH_PDF, page_index)
    second = render_page_png(MULTI_BATCH_PDF, page_index)
    assert first == second
    assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()
