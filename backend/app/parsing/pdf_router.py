"""Router jakości stron PDF (kontrakt C6; 05 §8.2)."""

from dataclasses import dataclass

from app.parsing.encoding import mojibake_ratio
from app.parsing.types import ConvertOptions, PageMode, PdfStrategy

IMAGE_PAGE_MAX_CHARS = 600  # jedyna stała: 05 §8.2 „chars < 600"


@dataclass(frozen=True)
class PdfPageInfo:
    """Surowe dane jednej strony PDF (wyjście ekstrakcji, wejście routera)."""

    text: str
    width_pt: float
    height_pt: float
    image_cover: float  # 0..1 (suma pól bbox obrazów / pole strony, przycięta do 1)
    cid_count: int  # wystąpienia "(cid:" w text


@dataclass(frozen=True)
class PageQuality:
    """Miary jakości warstwy tekstowej strony."""

    chars: int
    density: float
    mojibake_ratio: float
    cid_ratio: float
    image_cover: float


def page_text_quality(page: PdfPageInfo) -> PageQuality:
    """Liczy miary jakości strony z surowych danych ekstrakcji."""
    chars = sum(1 for ch in page.text if not ch.isspace())
    area = page.width_pt * page.height_pt / 10_000
    return PageQuality(
        chars=chars,
        density=chars / area if area else 0.0,
        mojibake_ratio=mojibake_ratio(page.text),
        cid_ratio=page.cid_count / max(1, len(page.text.split())),
        image_cover=min(1.0, max(0.0, page.image_cover)),
    )


def route_reason(q: PageQuality, opts: ConvertOptions) -> str:
    """Pierwszy spełniony warunek złej jakości (kolejność 05 §8.2); "" = strona dobra."""
    if q.chars < opts.min_chars:
        return f"chars<{opts.min_chars}"
    if q.mojibake_ratio > opts.mojibake_max:
        return "mojibake"
    if q.cid_ratio > opts.cid_max:
        return "cid"
    if q.image_cover > opts.image_cover and q.chars < IMAGE_PAGE_MAX_CHARS:
        return "image_cover"
    return ""


def route_page(q: PageQuality, strategy: PdfStrategy, opts: ConvertOptions) -> PageMode:
    """Wybiera tryb obsługi strony wg strategii i dostępności OCR/VLM."""
    fallback: PageMode
    if opts.vision_available:
        fallback = "vision"
    elif opts.ocr_available:
        fallback = "ocr"
    else:
        fallback = "text"
    if strategy == "vision":
        return fallback
    if strategy == "fast":
        if q.chars == 0 and opts.ocr_available:
            return "ocr"
        return "text"
    reason = route_reason(q, opts)  # strategia auto
    if reason == "image_cover":
        return "vision" if opts.vision_available else fallback
    if reason != "":
        return fallback
    return "text"
