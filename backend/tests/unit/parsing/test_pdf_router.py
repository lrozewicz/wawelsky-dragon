"""Testy routera stron PDF (kontrakt C6, 05 §8.2)."""

import pytest

from app.parsing.pdf_router import (
    PageQuality,
    PdfPageInfo,
    page_text_quality,
    route_page,
    route_reason,
)
from app.parsing.types import ConvertOptions


def pq(
    chars: int = 2000,
    density: float = 30.0,
    mojibake: float = 0.0,
    cid: float = 0.0,
    cover: float = 0.1,
) -> PageQuality:
    """Wygodny konstruktor PageQuality dla tabel decyzyjnych (strona dobra domyślnie)."""
    return PageQuality(chars, density, mojibake, cid, cover)


def test_convert_options_min_chars_default() -> None:
    # A8: domyślny próg to 150, nie 20.
    assert ConvertOptions().min_chars == 150  # noqa: PLR2004 — pin domyślnego progu (A8)


@pytest.mark.parametrize(
    ("page", "expected"),
    [
        (
            PdfPageInfo("Ala ma\nkota\t ", 100.0, 100.0, 0.0, 0),
            PageQuality(9, 9.0, 0.0, 0.0, 0.0),  # spacje/nowe linie nie liczone
        ),
        (
            PdfPageInfo("x" * 100, 100.0, 100.0, 0.0, 0),
            PageQuality(100, 100.0, 0.0, 0.0, 0.0),  # 100 / (10000/10000)
        ),
        (
            PdfPageInfo("abc", 0.0, 50.0, 0.0, 0),
            PageQuality(3, 0.0, 0.0, 0.0, 0.0),  # pole 0 → density 0.0
        ),
        (
            PdfPageInfo("ȥȥab", 100.0, 100.0, 0.0, 0),
            PageQuality(4, 4.0, 0.5, 0.0, 0.0),  # mojibake z encoding (C5)
        ),
        (
            PdfPageInfo("(cid:1) (cid:2) ab cd", 100.0, 100.0, 0.0, 2),
            PageQuality(18, 18.0, 0.0, 0.5, 0.0),  # 2/4 słów
        ),
        (
            PdfPageInfo("ab", 100.0, 100.0, 1.7, 0),
            PageQuality(2, 2.0, 0.0, 0.0, 1.0),  # przycięty do 1
        ),
        (
            PdfPageInfo("ab", 100.0, 100.0, -0.2, 0),
            PageQuality(2, 2.0, 0.0, 0.0, 0.0),  # przycięty do 0
        ),
    ],
    ids=[
        "chars-ignore-whitespace",
        "density-100",
        "density-zero-area",
        "mojibake",
        "cid-ratio",
        "cover-clip-high",
        "cover-clip-negative",
    ],
)
def test_page_text_quality(page: PdfPageInfo, expected: PageQuality) -> None:
    assert page_text_quality(page) == expected


@pytest.mark.parametrize(
    ("q", "opts", "expected"),
    [
        (pq(chars=100), ConvertOptions(), "chars<150"),
        (pq(chars=100, mojibake=0.9), ConvertOptions(), "chars<150"),  # kolejność: chars wygrywa
        (pq(chars=150), ConvertOptions(), ""),  # granica: chars == 150
        (pq(chars=180), ConvertOptions(min_chars=200), "chars<200"),  # próg zawsze z opts
        (PageQuality(2000, 30.0, 0.2, 0.0, 0.0), ConvertOptions(), "mojibake"),
        (pq(mojibake=0.05), ConvertOptions(), ""),  # granica: == mojibake_max
        (pq(cid=0.1), ConvertOptions(), "cid"),
        (pq(cid=0.02), ConvertOptions(), ""),  # granica: == cid_max
        (pq(chars=500, cover=0.9), ConvertOptions(), "image_cover"),
        (pq(chars=500, cover=0.6), ConvertOptions(), ""),  # granica: cover == image_cover
        (pq(chars=599, cover=0.7), ConvertOptions(), "image_cover"),  # chars tuż pod 600
        (pq(chars=600, cover=0.7), ConvertOptions(), ""),  # chars == 600 → nie image_cover
        (pq(), ConvertOptions(), ""),  # strona dobra
    ],
    ids=[
        "chars-low",
        "chars-before-mojibake",
        "chars-eq-150",
        "min-chars-from-opts",
        "mojibake",
        "mojibake-eq-max",
        "cid",
        "cid-eq-max",
        "image-cover",
        "cover-eq-threshold",
        "cover-599-chars",
        "cover-600-chars",
        "good",
    ],
)
def test_route_reason(q: PageQuality, opts: ConvertOptions, expected: str) -> None:
    assert route_reason(q, opts) == expected


AVAIL: dict[str, ConvertOptions] = {
    "both": ConvertOptions(vision_available=True, ocr_available=True),
    "vision-only": ConvertOptions(vision_available=True),
    "ocr-only": ConvertOptions(ocr_available=True),
    "none": ConvertOptions(),
}

SCENARIOS: dict[str, PageQuality] = {
    "good": pq(),  # reason ""
    "chars": pq(chars=100),  # reason "chars<150"
    "mojibake": pq(mojibake=0.2),  # reason "mojibake"
    "cid": pq(cid=0.5),  # reason "cid"
    "image-cover": pq(chars=500, cover=0.9),  # reason "image_cover"
    "empty": pq(chars=0, density=0.0),  # reason "chars<150"
    "almost-empty": pq(chars=5),  # chars != 0, ale < min_chars
    "a8": pq(chars=30, cover=0.9),  # A8: obraz z resztką tekstu
}

# Wiersze: (id, strategia, scenariusz, dostępność, oczekiwany tryb) — tabela C6 razy dostępności.
ROUTE_CASES: list[tuple[str, str, str, str, str]] = [
    # wiersz 1: strategia vision → zawsze fallback
    ("vision-good-both", "vision", "good", "both", "vision"),
    ("vision-good-vision-only", "vision", "good", "vision-only", "vision"),
    ("vision-good-ocr-only", "vision", "good", "ocr-only", "ocr"),
    ("vision-good-none", "vision", "good", "none", "text"),
    # wiersz 2: fast, chars == 0 i ocr_available → "ocr"
    ("fast-empty-both", "fast", "empty", "both", "ocr"),
    ("fast-empty-ocr-only", "fast", "empty", "ocr-only", "ocr"),
    # wiersz 3: fast, inaczej → "text"
    ("fast-empty-vision-only", "fast", "empty", "vision-only", "text"),
    ("fast-empty-none", "fast", "empty", "none", "text"),
    ("fast-almost-empty-both", "fast", "almost-empty", "both", "text"),
    ("fast-almost-empty-ocr-only", "fast", "almost-empty", "ocr-only", "text"),
    ("fast-good-none", "fast", "good", "none", "text"),
    # wiersz 4: auto, reason "image_cover" → vision albo fallback
    ("auto-image-cover-both", "auto", "image-cover", "both", "vision"),
    ("auto-image-cover-vision-only", "auto", "image-cover", "vision-only", "vision"),
    ("auto-image-cover-ocr-only", "auto", "image-cover", "ocr-only", "ocr"),
    ("auto-image-cover-none", "auto", "image-cover", "none", "text"),
    # wiersz 5: auto, inny reason (chars/mojibake/cid) → fallback
    ("auto-chars-ocr-only", "auto", "chars", "ocr-only", "ocr"),
    ("auto-chars-both", "auto", "chars", "both", "vision"),
    ("auto-chars-vision-only", "auto", "chars", "vision-only", "vision"),
    ("auto-chars-none", "auto", "chars", "none", "text"),
    ("auto-mojibake-both", "auto", "mojibake", "both", "vision"),
    ("auto-mojibake-ocr-only", "auto", "mojibake", "ocr-only", "ocr"),
    ("auto-mojibake-none", "auto", "mojibake", "none", "text"),
    ("auto-cid-both", "auto", "cid", "both", "vision"),
    ("auto-cid-ocr-only", "auto", "cid", "ocr-only", "ocr"),
    ("auto-empty-both", "auto", "empty", "both", "vision"),
    ("auto-empty-none", "auto", "empty", "none", "text"),
    ("auto-a8-vision-only", "auto", "a8", "vision-only", "vision"),
    # wiersz 6: auto, reason "" → "text"
    ("auto-good-both", "auto", "good", "both", "text"),
    ("auto-good-vision-only", "auto", "good", "vision-only", "text"),
    ("auto-good-ocr-only", "auto", "good", "ocr-only", "text"),
    ("auto-good-none", "auto", "good", "none", "text"),
]


@pytest.mark.parametrize(
    ("strategy", "scenario", "avail", "expected"),
    [(c[1], c[2], c[3], c[4]) for c in ROUTE_CASES],
    ids=[c[0] for c in ROUTE_CASES],
)
def test_route_page(strategy: str, scenario: str, avail: str, expected: str) -> None:
    assert route_page(SCENARIOS[scenario], strategy, AVAIL[avail]) == expected


@pytest.mark.parametrize(
    ("q", "strategy", "opts", "expected"),
    [
        # przykłady dosłownie z briefu T2
        (PageQuality(100, 1.0, 0.0, 0.0, 0.0), "auto", ConvertOptions(ocr_available=True), "ocr"),
        (PageQuality(2000, 30.0, 0.0, 0.0, 0.1), "auto", ConvertOptions(), "text"),
        (
            PageQuality(30, 0.3, 0.0, 0.0, 0.9),
            "auto",
            ConvertOptions(vision_available=True),
            "vision",
        ),
        (PageQuality(2000, 30.0, 0.2, 0.0, 0.0), "auto", ConvertOptions(), "text"),
        (PageQuality(0, 0.0, 0.0, 0.0, 0.0), "fast", ConvertOptions(ocr_available=True), "ocr"),
    ],
    ids=[
        "brief-chars-ocr",
        "brief-good-text",
        "brief-a8-vision",
        "brief-mojibake-text",
        "brief-fast-empty-ocr",
    ],
)
def test_route_page_brief_examples(
    q: PageQuality, strategy: str, opts: ConvertOptions, expected: str
) -> None:
    assert route_page(q, strategy, opts) == expected


def test_route_reason_brief_example() -> None:
    # przykład 5 z briefu T2
    assert route_reason(PageQuality(2000, 30.0, 0.2, 0.0, 0.0), ConvertOptions()) == "mojibake"
