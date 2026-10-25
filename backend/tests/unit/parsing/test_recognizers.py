"""Testy rozpoznawaczy OCR/VLM, complete_pages i self_check (kontrakt C10)."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from collections.abc import AsyncIterator
from io import BytesIO
from pathlib import Path

import pytesseract
import pytest
from PIL import Image

from app.llm.errors import LLMUnavailable
from app.llm.types import ModelRef
from app.parsing.converters.pdf import convert_pdf
from app.parsing.diacritics_stage import DiacriticsOptions, StageCorrector
from app.parsing.errors import BinaryMissing, EmptyDocument
from app.parsing.html import text_chars
from app.parsing.recognizers import (
    OTSL_MAX_TOKENS,
    OTSL_PROMPT,
    VLM_MAX_TOKENS,
    VLM_PROMPT,
    TesseractRecognizer,
    VlmRecognizer,
    _insert_fragment,
    complete_pages,
    extract_body,
    recognize_stream,
    self_check,
    vision_profile,
)
from app.parsing.types import ConvertedDocument, ConvertOptions, PendingPage
from tests.unit.parsing.factories import PdfPage, PdfText, body_text, make_pdf

# Stałe kontraktu C10 używane w asercjach (ruff PLR2004 nie lubi gołych literałów).
_CONTRACT_MAX_TOKENS = 4096
_CONTRACT_OTSL_MAX_TOKENS = 8192  # CONTRACT WP E5-H4a §3
_VISION_ATTEMPTS = 2  # 1 próba + 1 retry
_PAGE_COUNT = 3
_VISION_PDF_PAGES = 5  # CONTRACT WP E5-H6d §3 — PDF w całości na wizji
# Odpowiedź modelu OTSL: tekst + tabela z colspan/rowspan (przykład z briefu T3).
_OTSL_RESPONSE = "TABL. 17\n\n<fcel>A<fcel>2019<lcel><nl><ucel><fcel>x<fcel>y<nl>\n"
_DEFAULT_TESSERACT_TIMEOUT_S = 120.0
_CUSTOM_TIMEOUT_S = 30.0


def make_png() -> bytes:
    """Mały prawdziwy PNG (Pillow), by Image.open w teście tesseracta działał."""
    buffer = BytesIO()
    Image.new("RGB", (4, 4), (255, 0, 0)).save(buffer, format="PNG")
    return buffer.getvalue()


def make_doc(html: str, pending: list[PendingPage]) -> ConvertedDocument:
    return ConvertedDocument(
        html,
        None,
        pending,
        {},
        [],
        {"chars": 0, "pages_text": 0, "pages_ocr": 0, "pages_vision": 0},
    )


class FakeRecognizer:
    """Atrapa rozpoznawacza: kolejne odpowiedzi z listy, zapis wywołań i równoległości."""

    def __init__(self, name: str, responses: list[str | Exception]) -> None:
        self.name = name
        self._responses = list(responses)
        self.calls: list[tuple[int, str | None]] = []
        self.active = 0
        self.max_active = 0

    async def recognize(
        self, image_png: bytes, *, page: int, hint: str | None = None, use_cache: bool = True
    ) -> str:
        self.calls.append((page, hint))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0)  # szansa na przemieszanie współbieżnych wywołań
            response = self._responses.pop(0) if self._responses else ""
            if isinstance(response, Exception):
                raise response
            return response
        finally:
            self.active -= 1


class FakeGateway:
    """Atrapa LLMGateway z jedną metodą vision (zapis wywołań, zadane odpowiedzi)."""

    def __init__(self, responses: list[str | Exception], *, delay_s: float = 0.0) -> None:
        self._responses = list(responses)
        self._delay_s = delay_s
        self.calls: list[dict[str, object]] = []

    async def vision(  # noqa: PLR0913 — atrapa portu bramki (self + model,prompt,png + 3 kwargs)
        self,
        model: ModelRef,
        prompt: str,
        image_png: bytes,
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        cache: bool = False,
    ) -> str:
        self.calls.append(
            {
                "model": model,
                "prompt": prompt,
                "image_png": image_png,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "cache": cache,
            }
        )
        await asyncio.sleep(self._delay_s)
        response = self._responses.pop(0) if self._responses else ""
        if isinstance(response, Exception):
            raise response
        return response


# --- extract_body (przykłady z C10 + wielkość liter + brak </body>) ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("```html\n<p>a</p>\n```", "<p>a</p>"),
        ("<html><body><p>x</p></body></html>", "<p>x</p>"),
        ("<p>b</p>", "<p>b</p>"),
        ('<HTML><BODY class="a"><p>y</p></BODY></HTML>', "<p>y</p>"),
        ("<body><p>z</p>", "<p>z</p>"),
        ("```\n<p>c</p>\n```", "<p>c</p>"),
    ],
    ids=["fence-html", "body", "plain", "uppercase", "no-closing-body", "fence-plain"],
)
def test_extract_body(raw: str, expected: str) -> None:
    assert extract_body(raw) == expected


# --- VlmRecognizer ---


async def test_vlm_extracts_body_and_sends_max_tokens() -> None:
    gateway = FakeGateway(["<html><body><p>x</p></body></html>"])
    model = ModelRef(None, "fake-vision", "image2text")
    vlm = VlmRecognizer(gateway, model, timeout_s=5.0)
    png = make_png()
    assert await vlm.recognize(png, page=3) == "<p>x</p>"
    call = gateway.calls[0]
    assert call["model"] is model
    assert call["image_png"] == png
    assert call["max_tokens"] == VLM_MAX_TOKENS == _CONTRACT_MAX_TOKENS


async def test_vlm_prompt_plain_and_with_hint() -> None:
    plain = FakeGateway(["<p>x</p>"])
    await VlmRecognizer(plain, ModelRef(None, "fake-vision", "image2text")).recognize(
        make_png(), page=1
    )
    hinted = FakeGateway(["<p>x</p>"])
    await VlmRecognizer(hinted, ModelRef(None, "fake-vision", "image2text")).recognize(
        make_png(), page=1, hint="mojibake"
    )
    assert plain.calls[0]["prompt"] == VLM_PROMPT
    assert hinted.calls[0]["prompt"] == f"{VLM_PROMPT}\n\nmojibake"


async def test_vlm_timeout() -> None:
    gateway = FakeGateway(["<p>x</p>"], delay_s=1.0)
    vlm = VlmRecognizer(gateway, ModelRef(None, "fake-vision", "image2text"), timeout_s=0.01)
    with pytest.raises(TimeoutError):
        await vlm.recognize(make_png(), page=1)


# --- cache wizji: flaga use_cache → cache bramki (E5-H8e §C3) ---


async def test_vlm_recognize_passes_cache_flag() -> None:
    """``use_cache`` rozpoznawacza trafia do ``vision(cache=…)``: domyślnie True, jawnie False."""
    gateway = FakeGateway(["<p>a</p>", "<p>b</p>"])
    vlm = VlmRecognizer(gateway, ModelRef(None, "fake-vision", "image2text"))
    await vlm.recognize(make_png(), page=1)
    await vlm.recognize(make_png(), page=1, use_cache=False)
    assert [call["cache"] for call in gateway.calls] == [True, False]


async def test_page_first_try_cached_second_not() -> None:
    """Pierwsza próba strony idzie z cache wizji, ponowienie bez (DEC-293 p.1)."""
    doc = make_doc('<section data-page="1"></section>', [PendingPage(1, "vision", b"png", "image")])
    gateway = FakeGateway(["<p> </p>", "<p>x</p>"])
    vision = VlmRecognizer(gateway, ModelRef(None, "fake-vision", "image2text"))
    result = await complete_pages(doc, ocr=None, vision=vision)
    assert result.stats["pages_vision"] == 1
    assert [call["cache"] for call in gateway.calls] == [True, False]


async def test_otsl_recognize_passes_cache_flag() -> None:
    """Profil OTSL też przekazuje ``use_cache`` do bramki."""
    gateway = FakeGateway([_OTSL_RESPONSE])
    vlm = VlmRecognizer(gateway, ModelRef(None, "xiaomi-ocr-0", "image2text"))
    await vlm.recognize(make_png(), page=1, use_cache=False)
    assert gateway.calls[0]["cache"] is False


# --- profil wizji OTSL (T3) ---


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("xiaomi-ocr-0", "otsl"),
        ("Xiaomi-OCR-0", "otsl"),
        ("fake-ocr", "otsl"),
        ("gpt-4.1-mini", "html"),
        ("fake-vision", "html"),
    ],
)
def test_vision_profile_by_name(name: str, expected: str) -> None:
    assert vision_profile(name) == expected


async def test_otsl_profile_call_parameters() -> None:
    gateway = FakeGateway([_OTSL_RESPONSE])
    vlm = VlmRecognizer(gateway, ModelRef(None, "xiaomi-ocr-0", "image2text"))
    await vlm.recognize(make_png(), page=1)
    call = gateway.calls[0]
    assert call["prompt"] == OTSL_PROMPT
    assert call["max_tokens"] == OTSL_MAX_TOKENS == _CONTRACT_OTSL_MAX_TOKENS
    assert call["temperature"] == 0.0


async def test_otsl_profile_table_html() -> None:
    gateway = FakeGateway([_OTSL_RESPONSE])
    vlm = VlmRecognizer(gateway, ModelRef(None, "xiaomi-ocr-0", "image2text"))
    html = await vlm.recognize(make_png(), page=1)
    assert "<p>TABL. 17</p>" in html
    assert '<th colspan="2">2019</th>' in html


async def test_otsl_truncated_warning_reaches_document_warnings() -> None:
    doc = make_doc('<section data-page="1"></section>', [PendingPage(1, "vision", b"png", "image")])
    gateway = FakeGateway(["<fcel>a<fcel>b<nl><fcel>1"])
    vlm = VlmRecognizer(gateway, ModelRef(None, "fake-ocr", "image2text"))
    result = await complete_pages(doc, ocr=None, vision=vlm)
    assert "page 1: OTSL truncated: closed last row" in result.warnings
    assert vlm.warnings == ["page 1: OTSL truncated: closed last row"]


async def test_html_profile_unchanged_no_temperature() -> None:
    gateway = FakeGateway(["<p>x</p>"])
    vlm = VlmRecognizer(gateway, ModelRef(None, "gpt-4.1-mini", "image2text"))
    await vlm.recognize(make_png(), page=1)
    call = gateway.calls[0]
    assert call["prompt"] == VLM_PROMPT
    assert call["max_tokens"] == VLM_MAX_TOKENS
    assert call["temperature"] is None  # kwarg temperature nieprzekazany w profilu html


def test_otsl_profile_routes_text_layer_pdf_pages(tmp_path: Path) -> None:
    path = tmp_path / "doc.pdf"
    path.write_bytes(
        make_pdf(
            [
                PdfPage(texts=[PdfText(72, 100, 11, body_text(30))]),
                PdfPage(texts=[PdfText(72, 100, 11, body_text(30))]),
            ]
        )
    )
    doc = convert_pdf(path, ConvertOptions(pdf_strategy="vision", vision_available=True))
    assert [pending.mode for pending in doc.pending_pages] == ["vision", "vision"]
    for pending in doc.pending_pages:
        image = Image.open(BytesIO(pending.image_png))
        width = 595.0 * 200 / 72  # VISION_DPI = 200, strona Letter 595 pt
        assert abs(image.size[0] - width) <= 2  # noqa: PLR2004 — tolerancja renderu


# --- complete_pages ---


async def test_complete_pages_without_pending_returns_same_object() -> None:
    doc = make_doc("<p>a</p>", [])
    assert await complete_pages(doc, ocr=None, vision=None) is doc


async def test_vision_success_first_try() -> None:
    doc = make_doc('<section data-page="1"></section>', [PendingPage(1, "vision", b"png", "image")])
    vision = FakeRecognizer("vlm", ["<p>Tekst</p>"])
    result = await complete_pages(doc, ocr=None, vision=vision)
    assert result.html == '<section data-page="1"><p>Tekst</p></section>'
    assert result.pending_pages == []
    assert result.stats["pages_vision"] == 1
    assert result.stats["pages_ocr"] == 0
    assert vision.calls == [(1, None)]  # hint=None — spłata długu E1-4 (reason poza promptem)
    assert result.warnings == []


async def test_vision_retry_after_llm_unavailable() -> None:
    doc = make_doc('<section data-page="1"></section>', [PendingPage(1, "vision", b"png", "image")])
    vision = FakeRecognizer("vlm", [LLMUnavailable("boom"), "<p>x</p>"])
    result = await complete_pages(doc, ocr=None, vision=vision)
    assert len(vision.calls) == _VISION_ATTEMPTS
    assert result.stats["pages_vision"] == 1
    assert result.warnings == []


async def test_vision_twice_failed_falls_back_to_ocr() -> None:
    doc = make_doc('<section data-page="1"></section>', [PendingPage(1, "vision", b"png", "image")])
    vision = FakeRecognizer("vlm", [LLMUnavailable("boom"), LLMUnavailable("boom2")])
    ocr = FakeRecognizer("tesseract", ["<p>O</p>"])
    result = await complete_pages(doc, ocr=ocr, vision=vision)
    assert result.stats["pages_ocr"] == 1
    assert result.stats["pages_vision"] == 0
    assert "page 1: vlm failed (LLMUnavailable)" in result.warnings
    assert len(vision.calls) == _VISION_ATTEMPTS
    assert len(ocr.calls) == 1


async def test_empty_response_counts_as_failure() -> None:
    doc = make_doc('<section data-page="1"></section>', [PendingPage(1, "vision", b"png", "image")])
    vision = FakeRecognizer("vlm", ["<p> </p>", "<p> </p>"])
    ocr = FakeRecognizer("tesseract", ["<p>O</p>"])
    result = await complete_pages(doc, ocr=ocr, vision=vision)
    assert result.stats["pages_ocr"] == 1
    assert "page 1: vlm failed (EmptyResponse)" in result.warnings


async def test_mode_ocr_without_ocr_uses_vision() -> None:
    doc = make_doc(
        '<section data-page="2"></section>', [PendingPage(2, "ocr", b"png", "empty page")]
    )
    vision = FakeRecognizer("vlm", ["<p>V</p>"])
    result = await complete_pages(doc, ocr=None, vision=vision)
    assert result.html == '<section data-page="2"><p>V</p></section>'
    assert result.stats["pages_vision"] == 1


async def test_no_result_warning_document_returned() -> None:
    doc = make_doc(
        '<section data-page="1"><p>tresc</p></section><section data-page="2"></section>',
        [PendingPage(2, "ocr", b"png", "empty page")],
    )
    result = await complete_pages(doc, ocr=None, vision=None)
    assert "page 2: no text recognized (empty page)" in result.warnings
    assert "1 of 1 pages have no text after OCR/VLM" in result.warnings
    assert result.pending_pages == []
    assert text_chars(result.html) > 0


async def test_all_pages_empty_raises_empty_document() -> None:
    doc = make_doc('<section data-page="1"></section>', [PendingPage(1, "vision", b"png", "image")])
    vision = FakeRecognizer("vlm", [LLMUnavailable("boom"), LLMUnavailable("boom2")])
    with pytest.raises(EmptyDocument) as exc_info:
        await complete_pages(doc, ocr=None, vision=vision)
    assert exc_info.value.details == {"diagnosis": "no text recognized by OCR/VLM"}


async def test_k_of_m_warning_when_half_pages_fail() -> None:
    doc = make_doc(
        '<section data-page="1"><p>a</p></section>'
        '<section data-page="2"></section><section data-page="3"></section>',
        [
            PendingPage(2, "ocr", b"png", "empty page"),
            PendingPage(3, "ocr", b"png", "empty page"),
        ],
    )
    ocr = FakeRecognizer("tesseract", [LLMUnavailable("boom"), "<p>ok</p>"])
    result = await complete_pages(doc, ocr=ocr, vision=None)
    assert "page 2: tesseract failed (LLMUnavailable)" in result.warnings
    assert "1 of 2 pages have no text after OCR/VLM" in result.warnings
    assert result.stats["pages_ocr"] == 1


async def test_pages_vision_counted_once_after_recognition(tmp_path: Path) -> None:
    """PDF 5 stron na wizji: licznik = strony rozpoznane (5), nie pending + rozpoznane (10)."""
    path = tmp_path / "doc.pdf"
    path.write_bytes(
        make_pdf(
            [PdfPage(texts=[PdfText(72, 100, 11, body_text(30))]) for _ in range(_VISION_PDF_PAGES)]
        )
    )
    doc = convert_pdf(path, ConvertOptions(pdf_strategy="vision", vision_available=True))
    assert doc.stats["pages_vision"] == _VISION_PDF_PAGES  # licznik pending po konwersji
    vision = FakeRecognizer("vlm", [f"<p>p{page}</p>" for page in range(1, _VISION_PDF_PAGES + 1)])
    result = await complete_pages(doc, ocr=None, vision=vision)
    assert result.stats["pages_vision"] == _VISION_PDF_PAGES  # jedna prawda: strony rozpoznane
    assert result.stats["pages_ocr"] == 0


async def test_pages_vision_skips_unrecognized_page(tmp_path: Path) -> None:
    """Strona bez rozpoznanego tekstu (fragment None) nie jest liczona do pages_vision."""
    path = tmp_path / "doc.pdf"
    path.write_bytes(
        make_pdf([PdfPage(texts=[PdfText(72, 100, 11, body_text(30))]) for _ in range(3)])
    )
    doc = convert_pdf(path, ConvertOptions(pdf_strategy="vision", vision_available=True))
    vision = FakeRecognizer(
        "vlm",
        ["<p>a</p>", LLMUnavailable("boom"), LLMUnavailable("boom2"), "<p>c</p>"],
    )
    result = await complete_pages(doc, ocr=None, vision=vision, vision_concurrency=1)
    assert result.stats["pages_vision"] == 2  # noqa: PLR2004 — 2 z 3 stron rozpoznane
    assert result.stats["pages_ocr"] == 0


async def test_insert_into_slide_section() -> None:
    doc = make_doc(
        '<section data-slide="1"></section>',
        [PendingPage(1, "vision", b"png", "image-only slide")],
    )
    vision = FakeRecognizer("vlm", ["<h2>Tytuł</h2>"])
    result = await complete_pages(doc, ocr=None, vision=vision)
    assert result.html == '<section data-slide="1"><h2>Tytuł</h2></section>'
    assert "<section data-page=" not in result.html


async def test_append_new_section_when_no_empty_section() -> None:
    doc = make_doc("<p>intro</p>", [PendingPage(5, "vision", b"png", "image")])
    vision = FakeRecognizer("vlm", ["<p>V</p>"])
    result = await complete_pages(doc, ocr=None, vision=vision)
    assert result.html == "<p>intro</p>" + '<section data-page="5"><p>V</p></section>'


def test_insert_fragment_into_non_empty_slide_section() -> None:
    """T5: fragment dla slajdu z tekstem trafia przed `</section>` tego slajdu (nie na koniec)."""
    html = (
        '<section data-slide="1"><h2>Slajd 1</h2><p>tekst</p></section>'
        '<section data-slide="2"><h2>Slajd 2</h2><p>inny</p></section>'
    )
    result = _insert_fragment(html, 2, "<p>OCR</p>")
    assert result == (
        '<section data-slide="1"><h2>Slajd 1</h2><p>tekst</p></section>'
        '<section data-slide="2"><h2>Slajd 2</h2><p>inny</p><p>OCR</p></section>'
    )


def test_insert_fragment_into_empty_page_section() -> None:
    """T5: przypadek istniejący — pusta sekcja strony nadal wypełniana w miejscu."""
    assert _insert_fragment('<section data-page="3"></section>', 3, "<p>OCR</p>") == (
        '<section data-page="3"><p>OCR</p></section>'
    )


def test_insert_fragment_appends_section_when_missing() -> None:
    """T5: przypadek istniejący — brak sekcji o numerze → dopisanie na końcu."""
    assert _insert_fragment("<p>intro</p>", 5, "<p>OCR</p>") == (
        '<p>intro</p><section data-page="5"><p>OCR</p></section>'
    )


def test_insert_fragment_slide_number_no_prefix_collision() -> None:
    """T5: slajd 1 nie może dopasować `data-slide="10"` — dopasowanie z cudzysłowem i `>`."""
    html = '<section data-slide="10"><h2>Slajd 10</h2><p>a</p></section>'
    assert _insert_fragment(html, 1, "<p>OCR</p>") == (
        html + '<section data-page="1"><p>OCR</p></section>'
    )


async def test_input_document_not_modified() -> None:
    doc = make_doc('<section data-page="1"></section>', [PendingPage(1, "vision", b"png", "image")])
    html_before = doc.html
    pending_before = list(doc.pending_pages)
    warnings_before = list(doc.warnings)
    stats_before = dict(doc.stats)
    await complete_pages(doc, ocr=None, vision=FakeRecognizer("vlm", ["<p>x</p>"]))
    assert doc.html == html_before
    assert doc.pending_pages == pending_before
    assert doc.warnings == warnings_before
    assert doc.stats == stats_before


async def test_concurrency_one_serializes_calls() -> None:
    doc = make_doc(
        '<section data-page="1"></section>'
        '<section data-page="2"></section><section data-page="3"></section>',
        [
            PendingPage(1, "vision", b"png", "image"),
            PendingPage(2, "vision", b"png", "image"),
            PendingPage(3, "vision", b"png", "image"),
        ],
    )
    vision = FakeRecognizer("vlm", ["<p>1</p>", "<p>2</p>", "<p>3</p>"])
    result = await complete_pages(doc, ocr=None, vision=vision, vision_concurrency=1)
    assert vision.max_active == 1
    assert result.stats["pages_vision"] == _PAGE_COUNT


async def _pages_iter(pages: list[PendingPage]) -> AsyncIterator[PendingPage]:
    """Strumień stron dla ``recognize_stream`` (odpowiednik ``_pending_iter`` z modułu)."""
    for page in pages:
        yield page


async def test_recognize_stream_rejects_zero_vision_concurrency() -> None:
    """MINOR T5/T10: ``vision_concurrency < 1`` na wejściu ``recognize_stream`` → ValueError.

    Wartość 0 tworzy zero workerów i ciche puste rozpoznanie, więc odrzucamy ją na wejściu.
    """
    with pytest.raises(ValueError, match="vision_concurrency must be >= 1"):
        await recognize_stream(_pages_iter([]), ocr=None, vision=None, vision_concurrency=0)


async def test_complete_pages_rejects_zero_vision_concurrency() -> None:
    """MINOR T5/T10: walidacja ``vision_concurrency`` na wejściu ``complete_pages``."""
    doc = make_doc('<section data-page="1"></section>', [PendingPage(1, "vision", b"png", "image")])
    with pytest.raises(ValueError, match="vision_concurrency must be >= 1"):
        await complete_pages(doc, ocr=None, vision=None, vision_concurrency=0)


async def test_script_from_recognizer_is_sanitized() -> None:
    doc = make_doc('<section data-page="1"></section>', [PendingPage(1, "vision", b"png", "image")])
    vision = FakeRecognizer("vlm", ["<p>a</p><script>evil()</script>"])
    result = await complete_pages(doc, ocr=None, vision=vision)
    assert result.html == '<section data-page="1"><p>a</p></section>'
    assert "<script" not in result.html


# --- korekta diakrytyków w complete_pages (T4a, CONTRACT §4) ---


class FakeCorrector:
    """Atrapa korektora diakrytyków: zwraca zadany fragment i ostrzeżenia."""

    def __init__(self, fragment: str, warnings: list[str]) -> None:
        self._fragment = fragment
        self._warnings = warnings
        self.calls: list[tuple[str, str, int]] = []

    async def correct(self, fragment: str, *, layer_text: str, page: int) -> tuple[str, list[str]]:
        self.calls.append((fragment, layer_text, page))
        return self._fragment, self._warnings


async def test_complete_pages_corrects_vision_fragment() -> None:
    doc = make_doc(
        '<section data-page="1"></section>',
        [PendingPage(1, "vision", b"png", "image", "Ogółem")],
    )
    vision = FakeRecognizer("vlm", ["<p>Ogólem</p>"])
    result = await complete_pages(
        doc,
        ocr=None,
        vision=vision,
        diacritics=StageCorrector(DiacriticsOptions()),
    )
    assert "Ogółem" in result.html
    assert "Ogólem" not in result.html


async def test_complete_pages_does_not_correct_tesseract() -> None:
    doc = make_doc(
        '<section data-page="1"></section>',
        [PendingPage(1, "ocr", b"png", "empty page", "Ogółem")],
    )
    ocr = FakeRecognizer("tesseract", ["<p>Ogólem</p>"])
    result = await complete_pages(
        doc,
        ocr=ocr,
        vision=None,
        diacritics=StageCorrector(DiacriticsOptions()),
    )
    assert "Ogólem" in result.html
    assert "Ogółem" not in result.html


async def test_complete_pages_without_diacritics_unchanged() -> None:
    doc = make_doc('<section data-page="1"></section>', [PendingPage(1, "vision", b"png", "image")])
    vision = FakeRecognizer("vlm", ["<p>Ogólem</p>"])
    result = await complete_pages(doc, ocr=None, vision=vision)
    assert "Ogólem" in result.html


async def test_complete_pages_collects_diacritics_warnings() -> None:
    doc = make_doc(
        '<section data-page="1"></section>',
        [PendingPage(1, "vision", b"png", "image", "Ogółem")],
    )
    warning = "page 1: diacritics chunk rejected (numbers)"
    corrector = FakeCorrector("<p>Ogółem</p>", [warning])
    vision = FakeRecognizer("vlm", ["<p>Ogólem</p>"])
    result = await complete_pages(doc, ocr=None, vision=vision, diacritics=corrector)
    assert warning in result.warnings
    assert corrector.calls == [("<p>Ogólem</p>", "Ogółem", 1)]


# --- TesseractRecognizer ---


def test_tesseract_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: None)
    with pytest.raises(BinaryMissing):
        TesseractRecognizer()


async def test_tesseract_recognize_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/tesseract")
    seen: dict[str, object] = {}

    def fake_image_to_string(image: object, lang: str | None = None, timeout: float = 0) -> str:
        seen["image"] = image
        seen["lang"] = lang
        seen["timeout"] = timeout
        return "Ala ma kota\n\nDrugi akapit"

    monkeypatch.setattr(pytesseract, "image_to_string", fake_image_to_string)
    result = await TesseractRecognizer().recognize(make_png(), page=1)
    assert result == "<p>Ala ma kota</p><p>Drugi akapit</p>"
    assert seen["lang"] == "pol+eng"
    assert seen["timeout"] == _DEFAULT_TESSERACT_TIMEOUT_S


async def test_tesseract_custom_langs_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/tesseract")
    seen: dict[str, object] = {}

    def fake_image_to_string(image: object, lang: str | None = None, timeout: float = 0) -> str:
        seen["lang"] = lang
        seen["timeout"] = timeout
        return "Hello"

    monkeypatch.setattr(pytesseract, "image_to_string", fake_image_to_string)
    result = await TesseractRecognizer("eng", timeout_s=_CUSTOM_TIMEOUT_S).recognize(
        make_png(), page=2
    )
    assert result == "<p>Hello</p>"
    assert seen["lang"] == "eng"
    assert seen["timeout"] == _CUSTOM_TIMEOUT_S


# --- self_check ---


def test_self_check_all_binaries_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: None)
    assert self_check() == {"tesseract": False, "wvHtml": False, "catppt": False}


def test_self_check_probe_variants(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/tool")
    calls: list[tuple[list[str], float]] = []
    outcomes: list[object] = [
        subprocess.CompletedProcess([], 1),  # dowolny kod wyjścia → True
        subprocess.TimeoutExpired(cmd="wvHtml", timeout=5),  # → False
        OSError("permission denied"),  # → False
    ]

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append((list(cmd), float(kwargs["timeout"])))
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert self_check() == {"tesseract": True, "wvHtml": False, "catppt": False}
    assert calls == [
        (["tesseract", "--version"], 5.0),
        (["wvHtml", "--version"], 5.0),
        (["catppt", "-V"], 5.0),
    ]
