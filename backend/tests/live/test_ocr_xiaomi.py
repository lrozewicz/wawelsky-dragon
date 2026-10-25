"""Smoke live (marker ``live``): PDF GUS → chunki przez Xiaomi-OCR-0 (T6, Q28 p. 1).

Opt-in — uruchamia TL na lokalnym vLLM; wymaga ``WD_OCR_BASE_URL`` (bramka vLLM, np.
``http://127.0.0.1:18000/v1``) ORAZ ``WD_OCR_PDF`` (ścieżka rocznika GUS poza repo); bez nich
oba testy są pomijane. Ta sama ścieżka co ingestia: ``convert_options(..., layout_vision=True)``
→ ``convert_document(..., vision=VlmRecognizer(...))`` → ``html_to_blocks`` → ``chunk_blocks``.
Czasy/stronę dopisuje do pliku z ``WD_OCR_REPORT`` (jeśli ustawiona).

Strony wyznacza warstwa tekstu PDF (nie twardy numer): TABL. 17 (160) — wiersz „15―24 lata”
(benchmark s. 241 druk → strona PDF 1-based 243) oraz TABL. 14 (157) — bezrobocie
(benchmark s. 238 druk → strona PDF 240; wcześniejsze „TABL. 14 (131)” to zgony, dlatego
szukamy numerowanego tytułu tabeli, nie samego „TABL. 14”).
"""

import difflib
import os
import re
import time
from collections.abc import Sequence
from pathlib import Path

import pdfplumber
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.domain.chunking.chunker import chunk_blocks
from app.domain.chunking.presets import preset_for
from app.domain.chunking.types import ChunkDraft
from app.llm.openai_gateway import OpenAIGateway
from app.llm.types import ModelRef
from app.parsing.blocks import html_to_blocks
from app.parsing.diacritics_stage import DiacriticsCorrector, DiacriticsOptions, StageCorrector
from app.parsing.html import sanitize_html, text_chars
from app.parsing.recognizers import VlmRecognizer
from app.services.ingest_convert import chunk_config, convert_document, convert_options

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (os.environ.get("WD_OCR_BASE_URL") and os.environ.get("WD_OCR_PDF")),
        reason="live: brak WD_OCR_BASE_URL lub WD_OCR_PDF (uruchamia TL na lokalnym vLLM)",
    ),
]

MODEL_NAME = "xiaomi-ocr-0"
CHUNK_METHOD = "naive"  # domyślna metoda chunkowania RAGFlow (DEFAULT_PARSER_CONFIG)
CHUNK_TOKEN_NUM = 512
MIN_MATCH_RATIO = 0.95  # próg zgodności liczb (jak ../ocr-bench/xiaomi-ocr-0/numcmp.py)
T17_TITLE = "TABL. 17 (160)"
T14_TITLE = "TABL. 14 (157)"
PAGE_SEARCH = range(200, 261)  # zakres przeszukiwany w warstwie tekstu (1-based, w PDF)
_ROW_15_24 = re.compile(r"15.24 lata")
# Ciąg liczb jak numcmp.py (liczby całkowite i dziesiętne z przecinkiem).
_NUM = re.compile(r"(?<![\w,])\d+(?:,\d+)?(?![\w])")
# Pary nagłówek→wartość w tekście chunka tabeli: nazwa kolumny (ścieżka „ / ”) „: ” wartość.
_OGOLEM = r"og\S*em total"
# Pisownia kolumny po korekcie warstwą PDF: dokładnie „ogółem total” (bez tolerancji na brak „ł”).
_OGOLEM_EXACT = "ogółem total"
# Wiersz „15―24 lata” TABL. 17 (wartości z benchmarku właściciela).
_T17_EXPECTED: tuple[tuple[str, str, str], ...] = (
    ("2019", _OGOLEM, "9,9"),
    ("2019", "w tym kobiety", "10,3"),
    ("2022", _OGOLEM, "10,8"),
    ("2022", "w tym kobiety", "11,3"),
    ("2023", _OGOLEM, "11,3"),
    ("2023", "w tym kobiety", "11,1"),
)
# Te same 6 par co wyżej, ale kolumna „ogółem total” z dokładną pisownią po korekcie.
_T17_EXPECTED_CORRECTED: tuple[tuple[str, str, str], ...] = tuple(
    (year, _OGOLEM_EXACT if column == _OGOLEM else column, value)
    for year, column, value in _T17_EXPECTED
)
# Błędna pisownia kolumny (bez „ł”): jako osobne słowo nie może zostać po korekcie.
_OGOLEM_TYPO = re.compile(r"\bog[óo]lem\b", re.I)


def _nums(html: str) -> list[str]:
    """Liczby z zawartości chunka jak ``numcmp.py::nums()``: bez tagów i ``$``/``\\(``/``\\)``."""
    clean = re.sub(r"<[^>]+>", " ", html)
    for token in ("$", r"\(", r"\)"):
        clean = clean.replace(token, " ")
    return _NUM.findall(clean)


def _find_page(path: Path, title: str) -> int:
    """Pierwszy numer strony (1-based) w ``PAGE_SEARCH``, której tekst zawiera ``title``."""
    with pdfplumber.open(path) as pdf:
        for number in PAGE_SEARCH:
            text = pdf.pages[number - 1].extract_text() or ""
            if title in text:
                return number
    raise AssertionError(
        f"nie znaleziono {title!r} na stronach {PAGE_SEARCH.start}-{PAGE_SEARCH.stop - 1}"
    )


def _settings() -> Settings:
    """Ustawienia bramki OCR z ``WD_OCR_BASE_URL`` (klucz dowolny — vLLM go nie weryfikuje)."""
    return Settings(
        env="test",
        llm_base_url=os.environ["WD_OCR_BASE_URL"],
        llm_api_key=SecretStr("none"),
        llm_max_retries=0,
    )


def _write_report(page: int, seconds: float, drafts: Sequence[ChunkDraft], html_chars: int) -> None:
    """Dopisuje wynik do pliku ``WD_OCR_REPORT`` (gdy ustawiona) i wypisuje linię (dla ``-s``)."""
    line = f"strona={page} sekundy={seconds:.1f} chunków={len(drafts)} znaków_html={html_chars}"
    print(line)
    target = os.environ.get("WD_OCR_REPORT")
    if target:
        with Path(target).open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def _ogolem_counts(text: str) -> tuple[int, int]:
    """Liczba wystąpień („ogółem”, „ogólem”) jako osobne słowa — do wypisania przed/po korekcie."""
    return (
        len(re.findall(r"\bogółem\b", text, re.I)),
        len(re.findall(r"\bogólem\b", text, re.I)),
    )


async def _page_chunks(
    path: Path, page: int, *, diacritics: DiacriticsCorrector | None = None
) -> list[ChunkDraft]:
    """Konwersja jednej strony (profil OTSL) i chunkowanie — kroki 6-7 ingestii.

    ``diacritics`` (opcjonalny korektor etapów, domyślnie brak) idzie tą samą drogą co produkcja
    do ``convert_document``; warstwa PDF działa, gdy strona przeszła bramkę routera.
    """
    parser_config = {
        "layout_recognize": MODEL_NAME,
        "pages": [[page, page]],
        "chunk_token_num": CHUNK_TOKEN_NUM,
    }
    opts = convert_options(
        parser_config, _settings(), layout_vision=True, vision_available=True, ocr_available=False
    )
    gateway = OpenAIGateway(_settings())
    try:
        vision = VlmRecognizer(gateway, ModelRef(None, MODEL_NAME, "image2text"))
        start = time.perf_counter()
        converted = await convert_document(
            path, ".pdf", opts, executor=None, ocr=None, vision=vision, diacritics=diacritics
        )
        seconds = time.perf_counter() - start
    finally:
        await gateway.aclose()
    html = sanitize_html(converted.html)
    drafts = chunk_blocks(
        html_to_blocks(html), preset_for(CHUNK_METHOD), chunk_config(parser_config)
    )
    _write_report(page, seconds, drafts, text_chars(html))
    return drafts


async def test_t17_values_in_correct_columns() -> None:
    """Wiersz „15―24 lata” TABL. 17 ma wartości w kolumnach zgodnych z latami (nieprzesunięte)."""
    path = Path(os.environ["WD_OCR_PDF"])
    drafts = await _page_chunks(path, _find_page(path, T17_TITLE))
    row = next((draft for draft in drafts if _ROW_15_24.search(draft.text)), None)
    assert row is not None, "brak wiersza „15―24 lata” w żadnym chunku strony TABL. 17"
    for year, column, value in _T17_EXPECTED:
        pattern = rf"{year} / {column}[^;:]*: {value}"
        assert re.search(pattern, row.text), (
            f"brak pary {year} {column!r} = {value} w tekście chunka tabeli"
        )


async def test_t14_numbers_match_text_layer() -> None:
    """Liczby z chunków TABL. 14 zgadzają się z warstwą tekstu strony (próg ``MIN_MATCH_RATIO``).

    Liczby bierzemy z ``chunk.html`` po zdjęciu tagów (jak ``numcmp.py::nums()``), a nie z
    ``chunk.text``: linearyzacja tekstu tabeli powtarza w każdym wierszu nazwy kolumn (lata),
    co zaniża dopasowanie sekwencji (zmierzone 0,943 na benchmarku właściciela) niezależnie od
    wierności OCR. Tu mierzymy wierność rozpoznania, więc porównujemy zawartość HTML chunków
    z warstwą tekstu strony.
    """
    path = Path(os.environ["WD_OCR_PDF"])
    page = _find_page(path, T14_TITLE)
    drafts = await _page_chunks(path, page)
    got = _nums("\n".join(draft.html for draft in drafts))
    with pdfplumber.open(path) as pdf:
        gt = _NUM.findall(pdf.pages[page - 1].extract_text() or "")
    assert gt, f"warstwa tekstu strony {page} bez liczb"
    matcher = difflib.SequenceMatcher(None, gt, got, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    ratio = matched / len(gt)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op != "equal":
            print(f"  {op}: GT={gt[i1:i2]} OCR={got[j1:j2]}")
    assert ratio >= MIN_MATCH_RATIO, (
        f"zgodność liczb {ratio:.3f} < {MIN_MATCH_RATIO} (GT={len(gt)}, OCR={len(got)})"
    )


async def test_t17_diacritics_corrected_end_to_end() -> None:
    """Pełna ścieżka produkcyjna z korektą warstwą PDF: TABL. 17 ma dokładne „ogółem” bez „ogólem”.

    Ten sam wiersz „15―24 lata” co w ``test_t17_values_in_correct_columns``, ale kolumna
    „ogółem total” musi mieć dokładną pisownię po korekcie (bez tolerancyjnego wzorca).
    """
    path = Path(os.environ["WD_OCR_PDF"])
    page = _find_page(path, T17_TITLE)
    raw = await _page_chunks(path, page)
    corrected = await _page_chunks(path, page, diacritics=StageCorrector(DiacriticsOptions()))
    raw_text = "\n".join(draft.text for draft in raw)
    text = "\n".join(draft.text for draft in corrected)
    print(f"TABL. 17 (ogółem, ogólem) przed: {_ogolem_counts(raw_text)}")
    print(f"TABL. 17 (ogółem, ogólem) po: {_ogolem_counts(text)}")
    row = next((draft for draft in corrected if _ROW_15_24.search(draft.text)), None)
    assert row is not None, "brak wiersza „15―24 lata” w żadnym chunku strony TABL. 17"
    for year, column, value in _T17_EXPECTED_CORRECTED:
        pattern = rf"{year} / {column}[^;:]*: {value}"
        assert re.search(pattern, row.text), (
            f"brak pary {year} {column!r} = {value} w tekście chunka tabeli po korekcie"
        )
    typo = _OGOLEM_TYPO.search(text)
    assert typo is None, f"po korekcie w tekście jest „ogólem”: {typo.group(0)!r}"
    assert re.search(r"[Oo]gółem", text), "brak w tekście wariantu „ogółem”/„Ogółem”"
    assert re.search(r"[Kk]obiety", text), "brak w tekście słowa „kobiety”"


async def test_t14_diacritics_end_to_end() -> None:
    """Korekta TABL. 14: liczby z chunków zgodne z warstwą i identyczne przed/po korekcie.

    Korekta zmienia wyłącznie litery (DEC-248), więc ciąg liczb z ``chunk.html`` bez korekty
    i z korektą musi być równy; przy okazji sprawdzamy zgodność z warstwą tekstu (jak wyżej).
    """
    path = Path(os.environ["WD_OCR_PDF"])
    page = _find_page(path, T14_TITLE)
    raw = await _page_chunks(path, page)
    corrected = await _page_chunks(path, page, diacritics=StageCorrector(DiacriticsOptions()))
    raw_nums = _nums("\n".join(draft.html for draft in raw))
    got = _nums("\n".join(draft.html for draft in corrected))
    raw_text = "\n".join(draft.text for draft in raw)
    text = "\n".join(draft.text for draft in corrected)
    print(f"TABL. 14 liczby bez korekty ({len(raw_nums)}): {raw_nums}")
    print(f"TABL. 14 liczby z korektą ({len(got)}): {got}")
    print(f"TABL. 14 (ogółem, ogólem) bez korekty: {_ogolem_counts(raw_text)}")
    print(f"TABL. 14 (ogółem, ogólem) z korektą: {_ogolem_counts(text)}")
    assert got == raw_nums, "korekta zmieniła ciąg liczb w chunkach TABL. 14"
    with pdfplumber.open(path) as pdf:
        gt = _NUM.findall(pdf.pages[page - 1].extract_text() or "")
    assert gt, f"warstwa tekstu strony {page} bez liczb"
    matcher = difflib.SequenceMatcher(None, gt, got, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    ratio = matched / len(gt)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op != "equal":
            print(f"  {op}: GT={gt[i1:i2]} OCR={got[j1:j2]}")
    assert ratio >= MIN_MATCH_RATIO, (
        f"zgodność liczb {ratio:.3f} < {MIN_MATCH_RATIO} (GT={len(gt)}, OCR={len(got)})"
    )
