#!/usr/bin/env python3
"""Jednorazowy generator fixtures v13-1 (WP V13-1 T1): PDF z zakładkami i bez oraz md z nagłówkami.

Pliki wyjściowe są zacommitowane; generator trzymamy obok (wzór: e2e/fixtures/make-multi-batch-pdf.py),
żeby dało się je odtworzyć/odtworzyć świadomie:

    cd backend && uv run --with reportlab python ../frontend/e2e/fixtures/v13-1/make-fixtures.py

`rl_config.invariant` daje powtarzalne bajty (stała data i identyfikator dokumentu).
Zakładki (poziom 0): strony 1-based 1, 3 i 4 — tytuły trafiają dosłownie do asercji
`e2e/s30-v13-1-mapa-mix.spec.ts` (SC-V13-02 k2/k3) — zmiana tytułu = zmiana specu.
"""

from __future__ import annotations

import sys
from pathlib import Path

from reportlab import rl_config
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# Tytuły zakładek — DOSŁOWNIE te same ciągi w s30-v13-1-mapa-mix.spec.ts.
BOOKMARKS: list[tuple[str, str, int]] = [
    # (klucz zakładki, tytuł, strona 1-based)
    ("wstep", "Smok Wawelski — rozdział wstępny", 1),
    ("zamek", "Zamek na wzgórzu — rozdział drugi", 3),
    ("przeglad", "Przegląd korpusu — rozdział końcowy", 4),
]

PARAGRAPHS = [
    "Smok Wawelski mieszkał w jamie pod Wawelem i porywał bydło z okolicznych wsi, "
    "dopóki sprytny szewc nie podał mu skóry wypełnionej siarką i smołą.",
    "Zamek Królewski na Wawelu wznosi się nad Wisłą w Krakowie i przez stulecia był "
    "siedzibą królów Polski oraz miejscem koronacji i pochówku władców.",
    "Korpus dokumentów testowych zawiera próbki formatów PDF, DOCX i Markdown, "
    "które służą do sprawdzania parsowania, chunkowania i cytowań w systemie.",
    "Przegląd zbioru potwierdza, że polskie znaki: ąćęłńóśźż pozostają czytelne "
    "po konwersji, a tabele i listy zachowują strukturę wierzb chunków.",
]

MD_BODY = """# Korpus testowy V13-1

Ten dokument Markdown służy do sprawdzenia spisu treści z nagłówków (K21 §2 p. 2b).
Zawiera dokładnie cztery nagłówki, więc oczekiwany wpis logu to `Outline: 4 entries (headings)`.

## Sekcja pierwsza

Parsowanie zamienia nagłówki na bloki, a bloki na pozycje spisu treści dokumentu.
Treść akapitu jest dłuższa niż próba minimalna, więc powstaje przynajmniej jeden fragment.

## Sekcja druga

### Podsekcja szczegółowa

Wcięcie nagłówków (h1, h2, h3) mapuje się na poziomy spisu względem najwyższego
nagłówka w dokumencie, tutaj h1 jako poziom zerowy spisu.
"""


def page_text(c: canvas.Canvas, number: int) -> None:
    c.setFont("Helvetica", 11)
    y = 780
    for paragraph in PARAGRAPHS:
        c.drawString(60, y, f"[{number}] {paragraph[:90]}")
        y -= 40
        c.drawString(60, y, paragraph)
        y -= 60


def make_pdf(path: Path, with_bookmarks: bool) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setTitle("Fixture V13-1 — próbka parsowania")
    for number in range(1, 5):
        page_text(c, number)
        if with_bookmarks:
            for key, title, page in BOOKMARKS:
                if page == number:
                    c.bookmarkPage(key)
                    c.addOutlineEntry(title, key, level=0)
        c.showPage()
    c.save()


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
    rl_config.invariant = 1
    make_pdf(out / "v13-zakladki.pdf", with_bookmarks=True)
    make_pdf(out / "v13-bez-zakladek.pdf", with_bookmarks=False)
    (out / "v13-naglowki.md").write_text(MD_BODY, encoding="utf-8")
    print(f"zapisano: {out}/v13-zakladki.pdf, v13-bez-zakladek.pdf, v13-naglowki.md")


if __name__ == "__main__":
    main()
