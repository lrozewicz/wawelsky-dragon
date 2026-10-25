"""Konwerter obrazów (kontrakt C8) — strony do OCR/VLM jako PendingPage."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, cast

from PIL import Image, UnidentifiedImageError

from app.parsing.converters.common import finish, png_bytes
from app.parsing.errors import binary_missing, corrupted_file, limit_exceeded
from app.parsing.html import section_html
from app.parsing.types import ConvertedDocument, ConvertOptions, PendingPage


def convert_image(path: Path, opts: ConvertOptions) -> ConvertedDocument:
    """Obraz (png/jpg/webp/tiff/bmp) → puste sekcje stron + PendingPage do rozpoznania."""
    fmt = path.suffix.lower().lstrip(".")
    try:
        img = Image.open(path)
    except UnidentifiedImageError:
        raise corrupted_file(fmt, "not a valid image") from None
    except Image.DecompressionBombError:
        # PIL rzuca błąd przy pikselach > 2 * MAX_IMAGE_PIXELS — dolne ograniczenie = 2 * MAX.
        # MAX_IMAGE_PIXELS: int | None; None wyłącza sprawdzanie — wyjątek wtedy nie powstaje.
        limit = cast(int, Image.MAX_IMAGE_PIXELS)
        raise limit_exceeded("image pixels", limit * 2, limit) from None
    frames = getattr(img, "n_frames", 1)
    if frames > opts.max_pages:
        raise limit_exceeded("pages", frames, opts.max_pages)
    mode: Literal["ocr", "vision"]
    if opts.vision_available:
        mode = "vision"
    elif opts.ocr_available:
        mode = "ocr"
    else:
        raise binary_missing("tesseract")
    sections: list[str] = []
    pending: list[PendingPage] = []
    for nr in range(frames):
        img.seek(nr)
        pending.append(
            PendingPage(page=nr + 1, mode=mode, image_png=png_bytes(img.copy()), reason="image")
        )
        sections.append(section_html("page", nr + 1, ""))
    img.close()
    return finish("".join(sections), diagnosis="image has no text", pages=frames, pending=pending)
