"""Eval (a) diakrytyków i (d) skanów (marker ``live``): surowe wyjścia Xiaomi → korekta → metryka.

Opt-in — uruchamia TL przez ``tools/dev/live.sh pytest-live tests/live/test_diacritics_eval.py``.
Mierzy na zestawie właściciela (5 stron + 6 wycinków) procent słów z poprawnymi diakrytykami,
fałszywe poprawki i nietykalność liczb/tagów dla wariantów: ``baseline``, ``layer``,
``scan_nodict``, ``scan_wordfreq``, ``scan_llm``, ``scan_wordfreq_llm``.

Wejście (poza repo, tylko odczyt): surowe ``*.raw.md`` z ``${WD_OCRBENCH_DIR}/xiaomi-ocr-0``
(domyślnie ``<korzeń głównego checkoutu>/../ocr-bench``) i PDF GUS z ``WD_OCR_PDF`` (domyślnie
``<korzeń>/../dataset/...``). OTSL→HTML→Markdown tą samą drogą co produkcja
(``otsl_to_html`` + ``extract_body`` + ``_OTSL_MD``).

Raport JSON do ``WD_EVAL_REPORT`` (domyślnie ``work/wp/E5-H4b/reports/eval-diacritics.json``
w korzeniu checkoutu), księga kosztów dopisywana do ``work/wp/E5-H4b/reports/cost-ledger.json``
(nadpisanie ścieżki: ``WD_EVAL_LEDGER``). Twardy limit 4,5 USD sumy księgi i biegu przerywa test
przed kolejnym wywołaniem LLM. ``WD_EVAL_NO_LLM=1`` pomija warianty z LLM (do biegu bez kluczy).

GT metryki pochodzi z **niezależnego** ekstraktora niż warstwa używana do korekty: warstwa idzie
z pdfplumber (produkcja, ``PendingPage.text_layer``), a wzorzec z pypdfium2. ``common.py`` używa
pymupdf, ale nie jest on zależnością projektu (AGPL) ani nie ma go w obrazie; pypdfium2 jest
zależnością bezpośrednią backendu i daje te same pisownie (metryka odtwarza wartości z
``summary.txt`` eksperymentu, np. ``p238`` baseline 60,9%).
"""

from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pdfplumber
import pypdfium2 as pdfium
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.llm.openai_gateway import OpenAIGateway
from app.llm.types import ModelRef
from app.parsing.diacritics_llm import LlmDiacriticsCorrector
from app.parsing.diacritics_stage import DiacriticsOptions, StageCorrector
from app.parsing.otsl import otsl_to_html
from app.parsing.recognizers import _OTSL_MD, extract_body
from tests.unit.diacritics_metrics import (
    build_gt,
    classify_change,
    nums,
    page_words,
    score_text,
    word_changes,
)

# Flaga biegu bez LLM i gotowości kluczy — czytane przy imporcie (pominięcie testu).
_NO_LLM = os.environ.get("WD_EVAL_NO_LLM") == "1"
_LLM_READY = bool(os.environ.get("WD_LLM_BASE_URL") and os.environ.get("WD_LLM_API_KEY"))

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not _LLM_READY and not _NO_LLM,
        reason="live: brak WD_LLM_BASE_URL/WD_LLM_API_KEY (bez LLM: ustaw WD_EVAL_NO_LLM=1)",
    ),
]

# Nazwa modelu i ceny domyślne (gpt-5.4-mini, USD za token) — nadpisywalne z env.
MODEL_DEFAULT = "gpt-5.4-mini"
PRICE_IN_DEFAULT = "0.75e-6"
PRICE_OUT_DEFAULT = "4.5e-6"
# Twardy limit kosztu sumy księgi i biegu (USD).
COST_LIMIT_USD = 4.5
# Próg jakości wariantu ``layer`` (DEC-248 p. 9).
LAYER_MIN_PCT = 99.0

# Mapa etykiet druku → 0-based indeks strony PDF (``ocr-bench/diacritics-correction/common.py``).
LAB2IDX = {"238": 239, "241": 242, "224": 225, "232": 233, "239": 240}
CROP2LAB = {"t17": "241", "t14": "238", "t08": "232"}

DOC_FILES = tuple(f"p{lab}_doc.raw.md" for lab in LAB2IDX)
CROP_FILES = tuple(
    f"crop_{group}_{depth}_table.raw.md" for group in CROP2LAB for depth in ("200", "300")
)
FILES = DOC_FILES + CROP_FILES
# Grupy liczb wycinków do raportu (etykieta → prefiks plików).
CROP_NUM_GROUPS = {"T17": "crop_t17_", "T14": "crop_t14_", "T8": "crop_t08_"}

TAG_RE = re.compile(r"<[^>]+>")
REPORT_REL = "work/wp/E5-H4b/reports/eval-diacritics.json"
LEDGER_REL = "work/wp/E5-H4b/reports/cost-ledger.json"


@dataclass
class _Variant:
    """Wariant eval: korektor etapów (``None`` = baseline) i opcjonalny korektor LLM."""

    corrector: StageCorrector | None
    llm: LlmDiacriticsCorrector | None = None


def _git_output(*args: str) -> str:
    """Wynik komendy ``git`` (stała komenda, bez shell)."""
    result = subprocess.run(  # noqa: S603 - stałe argumenty, bez shell
        ["git", *args],  # noqa: S607 - "git" z PATH
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _main_root() -> Path:
    """Korzeń GŁÓWNEGO checkoutu (``git-common-dir``), wspólny dla worktree i checkoutu WP."""
    common_dir = _git_output("rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(common_dir).parent


def _checkout_root() -> Path:
    """Korzeń checkoutu, w którym leży ten plik (np. ``.wp/<id>`` albo worktree)."""
    return Path(__file__).resolve().parents[3]


def _page_index(name: str) -> int:
    """0-based indeks strony PDF dla pliku wejściowego."""
    doc = re.match(r"p(\d+)_", name)
    if doc:
        return LAB2IDX[doc.group(1)]
    crop = re.match(r"crop_(t\d+)_", name)
    assert crop is not None, f"nierozpoznana nazwa pliku: {name}"
    return LAB2IDX[CROP2LAB[crop.group(1)]]


def _render(raw: str) -> str:
    """Surowe wyjście Xiaomi → HTML, tą samą drogą co ``VlmRecognizer._recognize_otsl``."""
    markdown, _ = otsl_to_html(extract_body(raw))
    return str(_OTSL_MD.render(markdown))


def _pct(ok: int, bad: int) -> float | None:
    """Procent ``ok/(ok+bad)*100`` albo ``None``, gdy nie ma ocenianych słów."""
    return round(100 * ok / (ok + bad), 2) if ok + bad else None


def _number_match(original: Sequence[str], corrected: Sequence[str]) -> tuple[bool, str]:
    """``(identyczne, "dopasowane/wszystkie")`` dla ciągów liczb (jak ``numcmp``)."""
    matcher = difflib.SequenceMatcher(None, list(original), list(corrected), autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    return list(original) == list(corrected), f"{matched}/{len(original)}"


def _missing_inputs(bench: Path, pdf_path: Path) -> list[str]:
    """Lista brakujących plików wejściowych (pusta = komplet)."""
    missing = [str(bench / name) for name in FILES if not (bench / name).exists()]
    if not pdf_path.exists():
        missing.insert(0, str(pdf_path))
    return missing


def _fragments(bench: Path) -> dict[str, str]:
    """Fragmenty HTML wszystkich plików wejściowych (surowe wyjścia Xiaomi → render)."""
    return {name: _render((bench / name).read_text(encoding="utf-8")) for name in FILES}


def _page_texts(pdf_path: Path) -> dict[int, str]:
    """Teksty bazowych stron PDF z pypdfium2 (wzorzec metryki)."""
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        return {i: doc[i].get_textpage().get_text_range() for i in LAB2IDX.values()}
    finally:
        doc.close()


def _layer_texts(pdf_path: Path) -> dict[int, str]:
    """Teksty stron z pdfplumber — warstwa produkcyjna do korekty (``PendingPage.text_layer``)."""
    with pdfplumber.open(pdf_path) as pdf:
        return {i: (pdf.pages[i].extract_text() or "") for i in LAB2IDX.values()}


def _read_ledger_total(path: Path) -> float:
    """Suma z księgi kosztów (0, gdy pliku nie ma)."""
    if not path.exists():
        return 0.0
    return float(json.loads(path.read_text(encoding="utf-8")).get("total_usd", 0.0))


def _guard_budget(ledger_total: float, spent: float) -> None:
    """Przerywa test, gdy suma księgi i biegu przekracza limit — przed kolejnym wywołaniem LLM."""
    if ledger_total + spent > COST_LIMIT_USD:
        pytest.fail(
            f"budżet eval przekroczony: księga {ledger_total:.4f} + bieg {spent:.4f} USD "
            f"> {COST_LIMIT_USD} USD — przerwano przed kolejnym wywołaniem LLM"
        )


def _llm_gateway() -> OpenAIGateway:
    """Bramka LLM z ``WD_LLM_*`` (jak inne testy live)."""
    return OpenAIGateway(
        Settings(
            env="test",
            llm_base_url=os.environ["WD_LLM_BASE_URL"],
            llm_api_key=SecretStr(os.environ["WD_LLM_API_KEY"]),
            llm_max_retries=0,
        )
    )


def _llm_model() -> ModelRef:
    """Referencja modelu korekty z ``WD_EVAL_MODEL`` (domyślnie ``gpt-5.4-mini``)."""
    return ModelRef(
        id=None,
        name=os.environ.get("WD_EVAL_MODEL", MODEL_DEFAULT),
        model_type="chat",
        base_url=os.environ["WD_LLM_BASE_URL"],
        api_key=SecretStr(os.environ["WD_LLM_API_KEY"]),
    )


def _cost(variant: _Variant, price_in: float, price_out: float) -> float:
    """Koszt wariantu z tokenów jego korektora LLM (0 USD bez LLM)."""
    if variant.llm is None:
        return 0.0
    return variant.llm.tokens_in * price_in + variant.llm.tokens_out * price_out


async def _run_variant(  # noqa: PLR0913, PLR0917 - kontekst biegu przekazywany wprost
    name: str,
    variant: _Variant,
    fragments: dict[str, str],
    layer_texts: dict[int, str],
    page_texts: dict[int, str],
    gt: dict[str, set[str]],
    *,
    ledger_total: float,
    spent_before: float,
    price_in: float,
    price_out: float,
) -> dict[str, Any]:
    """Przepuszcza wszystkie pliki przez wariant i zwraca jego wiersz raportu."""
    started = time.perf_counter()
    files: dict[str, Any] = {}
    corrected_map: dict[str, str] = {}
    total_ok = total_bad = false_changes = 0
    errors: Counter[str] = Counter()
    numbers_identical = tags_identical = True
    for fname in FILES:
        index = _page_index(fname)
        original = fragments[fname]
        if variant.corrector is None:
            corrected = original
        else:
            if variant.llm is not None:
                _guard_budget(ledger_total, spent_before + _cost(variant, price_in, price_out))
            layer_text = layer_texts[index] if name == "layer" else ""
            corrected, _ = await variant.corrector.correct(
                original, layer_text=layer_text, page=index + 1
            )
        corrected_map[fname] = corrected
        ok, bad, file_errors = score_text(corrected, gt)
        total_ok += ok
        total_bad += bad
        errors.update(file_errors)
        vocab = page_words(page_texts[index])
        false_changes += sum(
            1
            for orig_word, new_word in word_changes(original, corrected)
            if classify_change(orig_word, new_word, vocab, gt) == "false"
        )
        same_numbers, number_count = _number_match(nums(original), nums(corrected))
        same_tags = TAG_RE.findall(original) == TAG_RE.findall(corrected)
        numbers_identical = numbers_identical and same_numbers
        tags_identical = tags_identical and same_tags
        files[fname.removesuffix(".raw.md")] = {
            "words_ok": ok,
            "words_bad": bad,
            "pct": _pct(ok, bad),
            "numbers_identical": same_numbers,
            "numbers": number_count,
            "tags_identical": same_tags,
        }
    crop_numbers: dict[str, Any] = {}
    for label, prefix in CROP_NUM_GROUPS.items():
        group = [fname for fname in CROP_FILES if fname.startswith(prefix)]
        same, count = _number_match(
            [n for fname in group for n in nums(fragments[fname])],
            [n for fname in group for n in nums(corrected_map[fname])],
        )
        crop_numbers[label] = {"identical": same, "count": count}
    llm = variant.llm
    return {
        "words_ok": total_ok,
        "words_bad": total_bad,
        "pct": _pct(total_ok, total_bad),
        "false_changes": false_changes,
        "rejections": list(llm.rejections) if llm is not None else [],
        "tokens_in": llm.tokens_in if llm is not None else 0,
        "tokens_out": llm.tokens_out if llm is not None else 0,
        "cost_usd": round(_cost(variant, price_in, price_out), 6),
        "seconds": round(time.perf_counter() - started, 2),
        "numbers_identical": numbers_identical,
        "tags_identical": tags_identical,
        "per_page_pct": {key: row["pct"] for key, row in files.items()},
        "crop_numbers": crop_numbers,
        "files": files,
        "top_errors": [f"{err} ({count})" for err, count in errors.most_common(20)],
    }


def _variants(no_llm: bool, gateway: OpenAIGateway | None) -> dict[str, _Variant]:
    """Buduje warianty eval; bez LLM pomija ``scan_llm`` i ``scan_wordfreq_llm``."""
    variants = {
        "baseline": _Variant(None),
        "layer": _Variant(StageCorrector(DiacriticsOptions(layer=True, wordfreq=False))),
        "scan_nodict": _Variant(StageCorrector(DiacriticsOptions(layer=False, wordfreq=False))),
        "scan_wordfreq": _Variant(StageCorrector(DiacriticsOptions(layer=False, wordfreq=True))),
    }
    if no_llm:
        return variants
    assert gateway is not None
    model = _llm_model()
    for name, wordfreq in (("scan_llm", False), ("scan_wordfreq_llm", True)):
        llm = LlmDiacriticsCorrector(gateway, model)
        corrector = StageCorrector(DiacriticsOptions(layer=False, wordfreq=wordfreq, llm=llm))
        variants[name] = _Variant(corrector, llm)
    return variants


def _write_json(path: Path, payload: Any) -> None:
    """Zapisuje JSON (UTF-8, wcięcia 1) tworząc katalogi."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def _append_ledger(path: Path, run_cost: float, run_entry: dict[str, Any]) -> None:
    """Dopisuje bieg do księgi kosztów (czytaj → dodaj → zapisz)."""
    ledger = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"total_usd": 0.0}
    ledger["total_usd"] = round(float(ledger.get("total_usd", 0.0)) + run_cost, 6)
    ledger.setdefault("runs", []).append(run_entry)
    _write_json(path, ledger)


async def test_diacritics_eval_reports_and_layer_threshold() -> None:
    """Liczby, fałszywe poprawki i próg ``layer``; raport i księga kosztów."""
    checkout = _checkout_root()
    main_root = _main_root()
    pdf_path = Path(
        os.environ.get(
            "WD_OCR_PDF",
            main_root.parent / "dataset/documents/pl/pdf/gus_rocznik_statystyczny_rp_2024.pdf",
        )
    )
    bench = Path(os.environ.get("WD_OCRBENCH_DIR", main_root.parent / "ocr-bench"))
    bench = bench / "xiaomi-ocr-0"
    missing = _missing_inputs(bench, pdf_path)
    if missing:
        pytest.skip("live: brak plików wejściowych: " + ", ".join(missing))

    no_llm = os.environ.get("WD_EVAL_NO_LLM") == "1"
    price_in = float(os.environ.get("WD_EVAL_PRICE_IN", PRICE_IN_DEFAULT))
    price_out = float(os.environ.get("WD_EVAL_PRICE_OUT", PRICE_OUT_DEFAULT))
    report_path = Path(os.environ.get("WD_EVAL_REPORT", checkout / REPORT_REL))
    ledger_path = Path(os.environ.get("WD_EVAL_LEDGER", checkout / LEDGER_REL))
    ledger_total = _read_ledger_total(ledger_path)

    fragments = _fragments(bench)
    page_texts = _page_texts(pdf_path)
    layer_texts = _layer_texts(pdf_path)
    gt = build_gt([page_texts[index] for index in LAB2IDX.values()])

    gateway: OpenAIGateway | None = None
    if not no_llm:
        gateway = _llm_gateway()
    rows: dict[str, Any] = {}
    spent = 0.0
    try:
        for name, variant in _variants(no_llm, gateway).items():
            rows[name] = await _run_variant(
                name,
                variant,
                fragments,
                layer_texts,
                page_texts,
                gt,
                ledger_total=ledger_total,
                spent_before=spent,
                price_in=price_in,
                price_out=price_out,
            )
            spent += rows[name]["cost_usd"]
    finally:
        if gateway is not None:
            await gateway.aclose()

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "no_llm": no_llm,
        "gt_extractor": "pypdfium2",
        "layer_extractor": "pdfplumber",
        "limit_usd": COST_LIMIT_USD,
        "run_cost_usd": round(spent, 6),
        "ledger_total_before_usd": ledger_total,
        "variants": rows,
    }
    _write_json(report_path, report)
    _append_ledger(
        ledger_path,
        spent,
        {
            "at": report["generated_at"],
            "no_llm": no_llm,
            "cost_usd": round(spent, 6),
            "variants": {name: row["cost_usd"] for name, row in rows.items()},
        },
    )

    for name, row in rows.items():
        print(
            f"{name:20s} ok/bad={row['words_ok']}/{row['words_bad']} pct={row['pct']} "
            f"fałszywe={row['false_changes']} liczby={row['numbers_identical']} "
            f"koszt={row['cost_usd']:.6f} USD czas={row['seconds']:.1f}s"
        )

    layer = rows["layer"]
    assert layer["pct"] is not None and layer["pct"] >= LAYER_MIN_PCT, (
        f"layer: {layer['pct']}% < {LAYER_MIN_PCT}% (DEC-248 p. 9; wynik w {report_path})"
    )
    assert layer["numbers_identical"], "layer: liczby zmienione po korekcie"
    assert layer["false_changes"] == 0, f"layer: fałszywe poprawki: {layer['files']}"
    for name, row in rows.items():
        assert row["numbers_identical"], f"{name}: liczby nieidentyczne z wejściem"
        assert row["tags_identical"], f"{name}: tagi nieidentyczne z wejściem"
