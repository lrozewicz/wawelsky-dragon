#!/usr/bin/env python3
"""Generator fixture'a e2e: deterministyczny PDF z polskim tekstem (CONTRACT C7).

Uruchomienie z katalogu backend (liczba stron opcjonalna, domyślnie 120):
    uv run python ../frontend/e2e/fixtures/make-multi-batch-pdf.py [strony]

Wynik: ``multi-batch-<strony>.pdf`` obok skryptu (120 — scenariusze ogólne,
960 — T11: Stop w trakcie konwersji przy szybkiej maszynie wielordzeniowej).

Wbudowany font reportlab (Vera) nie ma polskich glifów (pdfplumber zwraca \x00 dla
ż/ę/ś/ń/ź/ą), więc rejestrujemy DejaVuSans (awaryjnie LiberationSans).
"""
import sys
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

FONT_NAME = "DejaVu"
FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]

# Słowa z pełnym zestawem polskich diakrytyków: ą ć ę ł ń ó ś ź ż
RZECZOWNIKI = [
    "żubr", "łąka", "ścieżka", "dąb", "wąż", "słońce", "gęś", "pałac",
    "źrebak", "mąka", "kępa", "łódź", "rzęsa", "książę", "łabędź",
    "ziemia", "grań", "błonie", "wieś", "ćma",
]
PRZYMIOTNIKI = [
    "żółty", "gęsty", "łączny", "miękki", "śmiały", "ciasny", "mądry",
    "łagodny", "pewny", "niski", "ciemny", "zimny", "cudzy", "mokry",
    "krótki", "puchły", "śnieżny", "świerkowy", "wiosenny", "mały",
]
CZASOWNIKI = [
    "płynie", "śpiewa", "dąży", "łączy", "świeci", "drzemie", "ciągnie",
    "wędruje", "rośnie", "kwitnie", "błyszczy", "śnieje", "staje",
    "męczy", "schodzi", "błądzi", "pędzi", "idzie",
]
MIEJSCA = [
    "nad łąką", "w dolinie", "przy źródle", "obok dębu", "za wzgórzem",
    "koło młyna", "pod niebem", "wśród pól", "przy rzece",
    "na mokradłach", "w głębi lasu", "za wsią", "nad jeziorem",
    "przy drodze", "na skraju", "pośród łąk",
]


def zdanie(n: int, j: int, k: int) -> str:
    """Zdanie o treści zależnej od numeru strony (n), akapitu (j) i zdania (k)."""
    r = RZECZOWNIKI[(n * 3 + j * 7 + k) % len(RZECZOWNIKI)]
    p = PRZYMIOTNIKI[(n * 5 + j * 11 + k * 2) % len(PRZYMIOTNIKI)]
    c = CZASOWNIKI[(n * 7 + j * 13 + k * 3) % len(CZASOWNIKI)]
    m = MIEJSCA[(n * 11 + j * 17 + k * 5) % len(MIEJSCA)]
    s = PRZYMIOTNIKI[(n + j + k) % len(PRZYMIOTNIKI)]
    return (
        f"{p.capitalize()} {r} {c} {m}, strzeżony przez {s} strażnika "
        f"o numerze {n:03d}-{j}{k}."
    )


def akapit(n: int, j: int) -> str:
    zdania = [zdanie(n, j, k) for k in range(5)]
    return " ".join(zdania)


def zawijaj(tekst: str, font: str, rozmiar: float, szerokosc: float) -> list[str]:
    """Zachłanne zawijanie słów do szerokości (w punktach)."""
    linie: list[str] = []
    biezaca = ""
    for slowo in tekst.split():
        proba = f"{biezaca} {slowo}" if biezaca else slowo
        if pdfmetrics.stringWidth(proba, font, rozmiar) <= szerokosc:
            biezaca = proba
        else:
            linie.append(biezaca)
            biezaca = slowo
    if biezaca:
        linie.append(biezaca)
    return linie


def main() -> None:
    page_count = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    output = Path(__file__).resolve().with_name(f"multi-batch-{page_count}.pdf")
    sciezka_fontu = next(p for p in FONT_PATHS if Path(p).exists())
    pdfmetrics.registerFont(TTFont(FONT_NAME, sciezka_fontu))

    szerokosc, wysokosc = A4
    margines = 72.0
    kolumna = szerokosc - 2 * margines
    c = Canvas(str(output), pagesize=A4, invariant=1)

    for n in range(1, page_count + 1):
        c.setFont(FONT_NAME, 18)
        c.drawString(margines, wysokosc - 60, f"Strona {n} z {page_count}")

        c.setFont(FONT_NAME, 11)
        y = wysokosc - 100
        for j in range(3):
            tekst = akapit(n, j)
            if j == 0:
                # pattern z kontraktu C7: „Strona N: …"
                tekst = f"Strona {n}: {tekst}"
            for linia in zawijaj(tekst, FONT_NAME, 11, kolumna):
                c.drawString(margines, y, linia)
                y -= 15
            y -= 12
        c.showPage()

    c.save()
    print(f"zapisano {output} ({output.stat().st_size} bajtów)")


if __name__ == "__main__":
    main()
