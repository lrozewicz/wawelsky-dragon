"""Ręczne generowanie binarnych fixture testowych parsowania (nie jest uruchamiane przez pytest).

Użycie (z backend/):
`uv run --no-project --with pikepdf python tests/fixtures/parsing/make_fixtures.py`

Tworzy `encrypted.pdf`: PDF 1.4 z factories (1 strona z tekstem) zaszyfrowany pikepdf
(hasło użytkownika `secret`, właściciela `o`) — do testu EncryptedFile w convert_pdf.
"""

import io
import sys
from pathlib import Path

import pikepdf

BACKEND = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BACKEND))

from tests.unit.parsing.factories import PdfPage, PdfText, make_pdf  # noqa: E402


def main() -> None:
    source = make_pdf([PdfPage(texts=[PdfText(72, 100, 11, "Secret page")])])
    target = Path(__file__).resolve().parent / "encrypted.pdf"
    with pikepdf.open(io.BytesIO(source)) as pdf:
        pdf.save(
            target,
            encryption=pikepdf.Encryption(owner="o", user="secret"),
        )
    print(f"{target}: {target.stat().st_size} B")


if __name__ == "__main__":
    main()
