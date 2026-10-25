"""Typy parsowania (kontrakt C1, K5 §4.1) — picklowalne, bez stanu."""

from dataclasses import dataclass
from typing import Literal

PdfStrategy = Literal["fast", "auto", "vision"]
PageMode = Literal["text", "ocr", "vision"]

# Rozdzielczości renderu stron (05 §8.4): OCR 300 dpi, VLM 200 dpi.
OCR_DPI = 300
VISION_DPI = 200


@dataclass(frozen=True)
class ConvertOptions:
    """Opcje konwersji; buduje E1-6 z parser_config (layout_recognize → strategia wg 05 §6.1)."""

    pdf_strategy: PdfStrategy = "auto"
    pages: tuple[tuple[int, int], ...] = ((1, 1_000_000),)  # parser_config.pages, 1-based, włącznie
    vision_available: bool = False  # jest model image2text (decyduje worker)
    ocr_available: bool = False  # jest tesseract (self-check)
    ocr_langs: str = "pol+eng"
    min_chars: int = 150  # 05 §8.2
    mojibake_max: float = 0.05
    cid_max: float = 0.02
    image_cover: float = 0.6
    max_pages: int = 2000
    max_sheet_rows: int = 200_000
    max_uncompressed_bytes: int = 2048 * 1024 * 1024  # WD_MAX_UNCOMPRESSED_MB
    max_archive_ratio: int = 100  # WD_MAX_ARCHIVE_RATIO


@dataclass(frozen=True)
class PendingPage:
    """Strona oczekująca na rozpoznanie OCR/VLM (render PNG + powód odesłania)."""

    page: int  # 1-based; dla obrazów 1..n (TIFF wielostronicowy)
    mode: Literal["ocr", "vision"]
    image_png: bytes  # render 200 dpi (vision) / 300 dpi (ocr)
    reason: str  # np. "chars<150", "mojibake", "image_cover"
    text_layer: str = ""  # warstwa tekstowa strony, tylko gdy przeszła bramkę routera (DEC-248 P1)


@dataclass
class ConvertedDocument:
    """Wynik konwersji: znormalizowany HTML + statystyki; granica E1-4 → E1-5."""

    html: str  # zgodny z 05 §7; strony z pending_pages mają pusty <section data-page="n"></section>
    pages: int | None
    pending_pages: list[PendingPage]
    metadata: dict[str, str]
    warnings: list[str]
    stats: dict[str, int]  # m.in. chars, pages_text, pages_ocr, pages_vision
