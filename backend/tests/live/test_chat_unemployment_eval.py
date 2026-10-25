"""Eval (b) par (rok, kolumna), retrievalu i (c) czatu o bezrobociu 2022 (marker ``live``, T5b).

Opt-in — uruchamia TL przez ``tools/dev/live.sh pytest-live``. Z surowych wyjść Xiaomi (po korekcie
warstwą PDF, ``StageCorrector(DiacriticsOptions())``) buduje chunki TABL. 17 i TABL. 14, mierzy
trafność par (rok, kolumna) (b1) i nietykalność liczb (b2), rangi retrievalu embeddingami (b3) oraz
odpowiedź czatu o bezrobocie 2022 z notatką „kilka miar” (c) w dwóch trybach kontekstu: ``topk``
(6 najbliższych chunków) i ``oracle`` (top-6 plus chunki 2,9 BAEL 2022 i 5,2 rejestrowanego) —
drugi tryb mierzy wpływ notatki niezależnie od retrievalu.

Wejście (poza repo, tylko odczyt): surowe ``p{238,241,224,232,239}_doc.raw.md`` z
``${WD_OCRBENCH_DIR}/xiaomi-ocr-0`` (domyślnie ``<korzeń>/../ocr-bench``) i PDF GUS z
``WD_OCR_PDF``. Konwersję, warstwę pdfplumber i księgę kosztów bierzemy z T5a
(``tests/live/test_diacritics_eval.py``), wzorce i ``_nums`` z ``tests/live/test_ocr_xiaomi.py``.

Bez kluczy (``WD_EVAL_NO_LLM=1``) bieg ogranicza się do (b1)(b2) — bez embeddingów i czatu. Raport
JSON do ``WD_EVAL_REPORT_B`` (domyślnie ``work/wp/E5-H4b/reports/eval-retrieval-chat.json``).
Limit 4,5 USD sumy księgi i biegu przerywa bieg przed kolejnym wywołaniem.
"""

from __future__ import annotations

import difflib
import math
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from app.domain.chat.config import DEFAULT_PROMPT_CONFIG
from app.domain.chat.prompts import build_kb_blocks, build_system
from app.domain.chunking.chunker import chunk_blocks
from app.domain.chunking.presets import preset_for
from app.domain.chunking.types import ChunkDraft
from app.domain.retrieval.types import RetrievedChunk
from app.llm.openai_gateway import OpenAIGateway
from app.llm.tokens import count_tokens
from app.llm.types import ModelRef
from app.parsing.blocks import html_to_blocks
from app.parsing.diacritics_stage import DiacriticsOptions, StageCorrector
from app.parsing.html import sanitize_html
from app.services.ingest_convert import chunk_config
from tests.live import test_diacritics_eval as eval_a
from tests.live.test_ocr_xiaomi import _NUM, _OGOLEM, _T17_EXPECTED, _nums

# Flaga biegu bez LLM i gotowości kluczy — czytane przy imporcie (pominięcie modułu).
_NO_LLM = os.environ.get("WD_EVAL_NO_LLM") == "1"
_LLM_READY = bool(os.environ.get("WD_LLM_BASE_URL") and os.environ.get("WD_LLM_API_KEY"))

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not _LLM_READY and not _NO_LLM,
        reason="live: brak WD_LLM_BASE_URL/WD_LLM_API_KEY (bez LLM: ustaw WD_EVAL_NO_LLM=1)",
    ),
]

# Strony wchodzące do retrievalu (cel: p241 TABL. 17, p238 TABL. 14; reszta to dystraktory).
DOC_LABELS = ("241", "238", "224", "232", "239")
T17_LABEL = "241"
T14_LABEL = "238"
# Wiersz „15―24 lata” TABL. 17 (jak w teście smoke).
ROW_15_24 = re.compile(r"15.24 lata")
# W wariancie po korekcie wymagamy dokładnie poprawnej nazwy kolumny (przed bywa „ogólem total”).
OGOLEM_AFTER = "ogółem total"

# Model i ceny domyślne (USD za token) — nadpisywalne z env.
EMBED_MODEL_DEFAULT = "text-embedding-3-small"
CHAT_MODEL_DEFAULT = "gpt-5.4-nano"
CHAT_PRICE_IN_DEFAULT = "0.2e-6"
CHAT_PRICE_OUT_DEFAULT = "1.25e-6"
EMBED_PRICE_DEFAULT = "0.02e-6"

TOP_K = 6
CHAT_REPEATS = 3
MAX_TOKENS = 8192
CHAT_DATE = "2026-10-05 00:00:00"
CHAT_QUESTION = "jakie było bezrobocie w Polsce w 2022?"
# Wartość BAEL (survey) i rejestrowanego bezrobocia 2022 w Polsce — kryterium „obie miary”.
BAEL_VALUE = "2,9"
REGISTERED_VALUE = "5,2"
# Ocena „obie miary” na całych tokenach liczbowych: podciąg „2,9” nie może trafiać w „262,9”.
BAEL_RE = re.compile(rf"(?<![\d,]){BAEL_VALUE}(?![\d])")
REGISTERED_RE = re.compile(rf"(?<![\d,]){REGISTERED_VALUE}(?![\d])")

# Wymuszone chunki trybu „oracle” (c): OGÓŁEM 2022 z TABL. 17 (BAEL 2,9, wiersz OGÓŁEM — nie 15―24
# lata) i stopa bezrobocia rejestrowanego 2022 z TABL. 14 (5,2). Tytuł tabeli bywa w osobnym chunku,
# dlatego rozpoznajemy po etykiecie strony (``T17_LABEL``/``T14_LABEL``) i treści wiersza.
FORCED_T17_RE = re.compile(rf"2022 / {OGOLEM_AFTER}[^;:]*: {BAEL_VALUE}")
FORCED_T14_RATE_RE = re.compile(r"(?i)stopa bezrobocia")
FORCED_T14_RE = re.compile(rf"2022[^;:]*: {REGISTERED_VALUE}")

REPORT_REL = "work/wp/E5-H4b/reports/eval-retrieval-chat.json"
LEDGER_REL = "work/wp/E5-H4b/reports/cost-ledger.json"


@dataclass
class _Budget:
    """Licznik kosztu biegu; przerywa przed kolejnym wywołaniem po przekroczeniu limitu."""

    ledger_total: float
    spent: float = 0.0

    def guard(self) -> None:
        """``pytest.fail``, gdy suma księgi i biegu przekracza limit (przed kolejnym wywołaniem)."""
        if self.ledger_total + self.spent > eval_a.COST_LIMIT_USD:
            pytest.fail(
                f"budżet eval przekroczony: księga {self.ledger_total:.4f} + bieg {self.spent:.4f} "
                f"USD > {eval_a.COST_LIMIT_USD} USD — przerwano przed kolejnym wywołaniem LLM"
            )


def _missing(bench: Path, pdf_path: Path) -> list[str]:
    """Lista brakujących plików wejściowych (pusta = komplet)."""
    missing = [
        str(bench / f"p{label}_doc.raw.md")
        for label in DOC_LABELS
        if not (bench / f"p{label}_doc.raw.md").exists()
    ]
    if not pdf_path.exists():
        missing.insert(0, str(pdf_path))
    return missing


def _chunks(html: str) -> list[ChunkDraft]:
    """Chunkowanie strony jak ``_page_chunks`` (preset ``naive``, okno 512 tokenów)."""
    sanitized = sanitize_html(html)
    return chunk_blocks(
        html_to_blocks(sanitized), preset_for("naive"), chunk_config({"chunk_token_num": 512})
    )


async def _build_chunks(
    bench: Path, layer_texts: dict[int, str]
) -> dict[str, dict[str, list[ChunkDraft]]]:
    """Chunki 5 stron przed i po korekcie (``StageCorrector(DiacriticsOptions())``)."""
    corrector = StageCorrector(DiacriticsOptions())
    out: dict[str, dict[str, list[ChunkDraft]]] = {"before": {}, "after": {}}
    for label in DOC_LABELS:
        html = eval_a._render((bench / f"p{label}_doc.raw.md").read_text(encoding="utf-8"))
        index = eval_a.LAB2IDX[label]
        corrected, _ = await corrector.correct(html, layer_text=layer_texts[index], page=index + 1)
        out["before"][label] = _chunks(html)
        out["after"][label] = _chunks(corrected)
    return out


def _row(chunks: Sequence[ChunkDraft]) -> ChunkDraft | None:
    """Chunk z wierszem „15―24 lata” TABL. 17 (albo ``None``)."""
    return next((draft for draft in chunks if ROW_15_24.search(draft.text)), None)


def _column_pattern(column: str, *, corrected: bool) -> str:
    """Wzorzec kolumny: po korekcie dokładnie „ogółem total”, przed tolerancyjnie (``_OGOLEM``)."""
    if corrected and column == _OGOLEM:
        return OGOLEM_AFTER
    return column


def _pairs(row: ChunkDraft | None, *, corrected: bool) -> list[dict[str, Any]]:
    """Pary (rok, kolumna, wartość) i to, czy chunk wiersza je zawiera (b1)."""
    text = row.text if row is not None else ""
    out: list[dict[str, Any]] = []
    for year, column, value in _T17_EXPECTED:
        pattern = rf"{year} / {_column_pattern(column, corrected=corrected)}[^;:]*: {value}"
        out.append(
            {
                "year": year,
                "column": column,
                "value": value,
                "found": re.search(pattern, text) is not None,
            }
        )
    return out


def _numbers(chunks: Sequence[ChunkDraft]) -> list[str]:
    """Liczby z HTML chunków (jak ``numcmp.py::nums()``)."""
    return _nums("\n".join(draft.html for draft in chunks))


def _match_ratio(got: Sequence[str], gt: Sequence[str]) -> float:
    """Udział liczb wzorca dopasowanych w ciągu OCR (``difflib``, jak smoke T14)."""
    matcher = difflib.SequenceMatcher(None, list(gt), list(got), autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    return round(matched / len(gt), 3) if gt else 0.0


def _questions() -> list[str]:
    """6 pytań o pary (rok, kolumna) TABL. 17 (w kolejności ``_T17_EXPECTED``)."""
    out: list[str] = []
    for year, column, _value in _T17_EXPECTED:
        if column == _OGOLEM:
            out.append(f"Jaka była stopa bezrobocia osób w wieku 15-24 lata w {year} roku ogółem?")
        else:
            out.append(f"Jaka była stopa bezrobocia kobiet w wieku 15-24 lata w {year} roku?")
    return out


def _flat(
    chunks: Mapping[str, Sequence[ChunkDraft]], labels: Sequence[str]
) -> list[tuple[str, ChunkDraft]]:
    """Płaska lista (etykieta strony, chunk) — stała kolejność dla embeddingów i rang."""
    return [(label, draft) for label in labels for draft in chunks[label]]


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosinus dwóch wektorów (0, gdy któryś zerowy)."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _ranking(vectors: Sequence[Sequence[float]], query: Sequence[float]) -> list[int]:
    """Indeksy wektorów od najbardziej do najmniej podobnego (cosinus)."""
    return sorted(range(len(vectors)), key=lambda i: _cosine(vectors[i], query), reverse=True)


def _rank(
    vectors: Sequence[Sequence[float]], query: Sequence[float], target: int | None, top_k: int
) -> int | None:
    """1-based ranga celu w top-k albo ``None`` (cel spoza top-k lub nieznany)."""
    if target is None:
        return None
    for position, index in enumerate(_ranking(vectors, query)[:top_k], start=1):
        if index == target:
            return position
    return None


def _pair_target(
    flat: Sequence[tuple[str, ChunkDraft]], pair_index: int, *, corrected: bool
) -> int | None:
    """Indeks chunku zawierającego parę (rok, kolumna, wartość) albo ``None``."""
    year, column, value = _T17_EXPECTED[pair_index]
    pattern = rf"{year} / {_column_pattern(column, corrected=corrected)}[^;:]*: {value}"
    for index, (_label, draft) in enumerate(flat):
        if re.search(pattern, draft.text):
            return index
    return None


def _forced_chunks(flat: Sequence[tuple[str, ChunkDraft]]) -> dict[str, int | None]:
    """Indeksy chunku TABL. 17 OGÓŁEM 2022 = 2,9 i TABL. 14 stopa 2022 = 5,2 (albo ``None``)."""
    t17 = next(
        (
            index
            for index, (label, draft) in enumerate(flat)
            if label == T17_LABEL and "OGÓŁEM" in draft.text and FORCED_T17_RE.search(draft.text)
        ),
        None,
    )
    t14 = next(
        (
            index
            for index, (label, draft) in enumerate(flat)
            if label == T14_LABEL
            and FORCED_T14_RATE_RE.search(draft.text)
            and FORCED_T14_RE.search(draft.text)
        ),
        None,
    )
    return {"tabl17_2022_ogolem": t17, "tabl14_2022_registered": t14}


def _labels(flat: Sequence[tuple[str, ChunkDraft]], indices: Sequence[int]) -> list[dict[str, Any]]:
    """Etykiety (strona, ordinal) chunków o danych indeksach."""
    return [{"label": flat[index][0], "ordinal": flat[index][1].ordinal} for index in indices]


def _context(
    flat: Sequence[tuple[str, ChunkDraft]],
    vectors: Sequence[Sequence[float]],
    query: Sequence[float],
    indices: Sequence[int],
) -> list[RetrievedChunk]:
    """``RetrievedChunk`` dla indeksów kontekstu z cosinusem do zapytania."""
    return [
        _retrieved(flat[index][0], flat[index][1], _cosine(vectors[index], query))
        for index in indices
    ]


def _retrieved(label: str, draft: ChunkDraft, similarity: float) -> RetrievedChunk:
    """``RetrievedChunk`` z chunku eval (pola spoza treści wypełnione minimalnie)."""
    return RetrievedChunk(
        chunk_id=f"eval-{label}-{draft.ordinal}",
        content=draft.text,
        content_llm=draft.text,
        content_terms="",
        document_id=f"doc-{label}",
        document_name=f"p{label}_doc",
        dataset_id="eval",
        image_id="",
        important_keywords=[],
        questions=[],
        tag_kwd=[],
        positions=[],
        similarity=similarity,
        vector_similarity=similarity,
        term_similarity=0.0,
        highlight=None,
        doc_type="",
        url=None,
        document_metadata=None,
    )


def _embed_model() -> ModelRef:
    """Referencja modelu embeddingów z ``WD_EVAL_EMBED_MODEL``."""
    return ModelRef(
        id=None,
        name=os.environ.get("WD_EVAL_EMBED_MODEL", EMBED_MODEL_DEFAULT),
        model_type="embedding",
        base_url=os.environ["WD_LLM_BASE_URL"],
        api_key=SecretStr(os.environ["WD_LLM_API_KEY"]),
    )


def _chat_model() -> ModelRef:
    """Referencja modelu czatu z ``WD_EVAL_CHAT_MODEL`` (domyślnie ``gpt-5.4-nano``)."""
    return ModelRef(
        id=None,
        name=os.environ.get("WD_EVAL_CHAT_MODEL", CHAT_MODEL_DEFAULT),
        model_type="chat",
        base_url=os.environ["WD_LLM_BASE_URL"],
        api_key=SecretStr(os.environ["WD_LLM_API_KEY"]),
    )


def _embed_price() -> float:
    """Cena embeddingów USD/token z ``WD_EVAL_EMBED_PRICE``."""
    return float(os.environ.get("WD_EVAL_EMBED_PRICE", EMBED_PRICE_DEFAULT))


def _chat_prices() -> tuple[float, float]:
    """Ceny czatu USD/token (in, out); ``WD_EVAL_CHAT_PRICE_*``, fallback ``WD_EVAL_PRICE_*``."""
    price_in = os.environ.get("WD_EVAL_CHAT_PRICE_IN") or os.environ.get(
        "WD_EVAL_PRICE_IN", CHAT_PRICE_IN_DEFAULT
    )
    price_out = os.environ.get("WD_EVAL_CHAT_PRICE_OUT") or os.environ.get(
        "WD_EVAL_PRICE_OUT", CHAT_PRICE_OUT_DEFAULT
    )
    return float(price_in), float(price_out)


def _embed_cost(texts: Sequence[str], price: float) -> float:
    """Koszt embeddingu tekstów (tokeny liczone ``count_tokens``, cena z env)."""
    return sum(count_tokens(text) for text in texts) * price


async def _chat_variant(  # noqa: PLR0913 — kontekst biegu przekazywany wprost
    gateway: OpenAIGateway,
    chat_model: ModelRef,
    context: Sequence[RetrievedChunk],
    monkeypatch: pytest.MonkeyPatch,
    *,
    enabled: bool,
    budget: _Budget,
    price_in: float,
    price_out: float,
) -> dict[str, Any]:
    """3 odpowiedzi czatu dla wariantu notatki „kilka miar” (regułowa ocena „obie miary”)."""
    monkeypatch.setattr("app.domain.chat.prompts.MULTI_MEASURE_NOTE_ENABLED", enabled)
    blocks = build_kb_blocks(context, MAX_TOKENS, count_tokens=count_tokens)
    system = build_system(
        str(DEFAULT_PROMPT_CONFIG["system"]),
        blocks,
        DEFAULT_PROMPT_CONFIG["parameters"],
        {"date": CHAT_DATE},
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": CHAT_QUESTION},
    ]
    answers: list[str] = []
    both = 0
    tokens_in = tokens_out = 0
    for _ in range(CHAT_REPEATS):
        budget.guard()
        result = await gateway.chat(chat_model, messages)
        tokens_in += result.tokens_in
        tokens_out += result.tokens_out
        budget.spent += result.tokens_in * price_in + result.tokens_out * price_out
        if BAEL_RE.search(result.text) and REGISTERED_RE.search(result.text):
            both += 1
        answers.append(result.text)
    return {
        "note_enabled": enabled,
        "both_measures": both,
        "repeats": CHAT_REPEATS,
        "answers": answers,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
    }


async def _llm_sections(  # noqa: PLR0913 — kontekst biegu przekazywany wprost
    gateway: OpenAIGateway,
    monkeypatch: pytest.MonkeyPatch,
    chunks: Mapping[str, Mapping[str, list[ChunkDraft]]],
    budget: _Budget,
    *,
    embed_price: float,
    chat_price_in: float,
    chat_price_out: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Sekcje (b3) retrieval i (c) czat — pomijane przy ``WD_EVAL_NO_LLM=1``."""
    embed_model = _embed_model()
    chat_model = _chat_model()
    flat = {variant: _flat(chunks[variant], DOC_LABELS) for variant in ("before", "after")}
    vectors: dict[str, list[list[float]]] = {}
    for variant in ("before", "after"):
        texts = [draft.text for _label, draft in flat[variant]]
        budget.guard()
        vectors[variant] = await gateway.embed(embed_model, texts)
        budget.spent += _embed_cost(texts, embed_price)

    questions = _questions()
    retrieval: dict[str, Any] = {
        "embed_model": embed_model.name,
        "top_k": TOP_K,
        "questions": questions,
        "variants": {},
    }
    for variant in ("before", "after"):
        corrected = variant == "after"
        rows: list[dict[str, Any]] = []
        for pair_index, question in enumerate(questions):
            budget.guard()
            query = await gateway.embed_query(embed_model, question)
            budget.spent += count_tokens(question) * embed_price
            target = _pair_target(flat[variant], pair_index, corrected=corrected)
            rows.append(
                {"question": question, "rank": _rank(vectors[variant], query, target, TOP_K)}
            )
        retrieval["variants"][variant] = rows

    budget.guard()
    chat_query = await gateway.embed_query(embed_model, CHAT_QUESTION)
    budget.spent += count_tokens(CHAT_QUESTION) * embed_price
    top = _ranking(vectors["after"], chat_query)[:TOP_K]
    forced = _forced_chunks(flat["after"])
    forced_found = all(index is not None for index in forced.values())
    # Tryb „oracle”: top-6 plus chunki wymuszone (TABL. 17 OGÓŁEM 2,9; TABL. 14 stopa 5,2).
    modes: dict[str, list[int]] = {"topk": top}
    if forced_found:
        union = list(top)
        for index in forced.values():
            if index is not None and index not in union:
                union.append(index)
        modes["oracle"] = union
    chat: dict[str, Any] = {
        "question": CHAT_QUESTION,
        "top_k": TOP_K,
        "top_k_labels": _labels(flat["after"], top),
        "forced": {
            key: (None if index is None else _labels(flat["after"], [index])[0])
            for key, index in forced.items()
        },
        "forced_found": forced_found,
        "modes": {},
    }
    for mode, indices in modes.items():
        context = _context(flat["after"], vectors["after"], chat_query, indices)
        chat["modes"][mode] = {"context_labels": _labels(flat["after"], indices)}
        for enabled, key in ((False, "note_disabled"), (True, "note_enabled")):
            chat["modes"][mode][key] = await _chat_variant(
                gateway,
                chat_model,
                context,
                monkeypatch,
                enabled=enabled,
                budget=budget,
                price_in=chat_price_in,
                price_out=chat_price_out,
            )
    return retrieval, chat


async def test_chat_unemployment_eval(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pary (b1), liczby (b2) i raport (b3)(c); asercje tylko dla (b1) wariant „po” i (b2)."""
    checkout = eval_a._checkout_root()
    main_root = eval_a._main_root()
    pdf_path = Path(
        os.environ.get(
            "WD_OCR_PDF",
            main_root.parent / "dataset/documents/pl/pdf/gus_rocznik_statystyczny_rp_2024.pdf",
        )
    )
    bench = Path(os.environ.get("WD_OCRBENCH_DIR", main_root.parent / "ocr-bench")) / "xiaomi-ocr-0"
    missing = _missing(bench, pdf_path)
    if missing:
        pytest.skip("live: brak plików wejściowych: " + ", ".join(missing))

    no_llm = _NO_LLM
    report_path = Path(os.environ.get("WD_EVAL_REPORT_B", checkout / REPORT_REL))
    ledger_path = Path(os.environ.get("WD_EVAL_LEDGER", checkout / LEDGER_REL))
    budget = _Budget(eval_a._read_ledger_total(ledger_path))
    embed_price = _embed_price()
    chat_price_in, chat_price_out = _chat_prices()

    layer_texts = eval_a._layer_texts(pdf_path)
    chunks = await _build_chunks(bench, layer_texts)

    pairs: dict[str, Any] = {
        "before": _pairs(_row(chunks["before"][T17_LABEL]), corrected=False),
        "after": _pairs(_row(chunks["after"][T17_LABEL]), corrected=True),
    }
    pairs["after_all_found"] = all(item["found"] for item in pairs["after"])

    gt_numbers = _NUM.findall(layer_texts[eval_a.LAB2IDX[T14_LABEL]])
    nums_before = _numbers(chunks["before"][T14_LABEL])
    nums_after = _numbers(chunks["after"][T14_LABEL])
    t14: dict[str, Any] = {
        "before": {
            "match_ratio": _match_ratio(nums_before, gt_numbers),
            "gt": len(gt_numbers),
            "ocr": len(nums_before),
            "numbers": nums_before,
        },
        "after": {
            "match_ratio": _match_ratio(nums_after, gt_numbers),
            "gt": len(gt_numbers),
            "ocr": len(nums_after),
            "numbers": nums_after,
        },
        "equal_before_after": "tak" if nums_before == nums_after else "nie",
    }

    retrieval: dict[str, Any] | None = None
    chat: dict[str, Any] | None = None
    gateway = None if no_llm else eval_a._llm_gateway()
    try:
        if gateway is not None:
            retrieval, chat = await _llm_sections(
                gateway,
                monkeypatch,
                chunks,
                budget,
                embed_price=embed_price,
                chat_price_in=chat_price_in,
                chat_price_out=chat_price_out,
            )
    finally:
        if gateway is not None:
            await gateway.aclose()

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "no_llm": no_llm,
        "pairs": pairs,
        "t14_numbers": t14,
        "retrieval": retrieval,
        "chat": chat,
        "cost": {
            "embed_price_usd": embed_price,
            "chat_price_in_usd": chat_price_in,
            "chat_price_out_usd": chat_price_out,
            "run_usd": round(budget.spent, 6),
            "ledger_total_before_usd": budget.ledger_total,
        },
    }
    eval_a._write_json(report_path, report)
    eval_a._append_ledger(
        ledger_path,
        budget.spent,
        {
            "at": report["generated_at"],
            "name": "T5b eval (b)(c)",
            "no_llm": no_llm,
            "cost_usd": round(budget.spent, 6),
        },
    )

    print(f"(b1) pary TABL. 17 po korekcie: {sum(i['found'] for i in pairs['after'])}/6")
    print(
        f"(b2) liczby TABL. 14 równe przed/po: {t14['equal_before_after']} "
        f"(ratio przed={t14['before']['match_ratio']}, po={t14['after']['match_ratio']})"
    )
    if chat is not None:
        print(f"(c) wymuszone chunki znalezione: {chat['forced_found']}; {chat['forced']}")
        for mode, data in chat["modes"].items():
            print(
                f"(c) kontekst {mode}: note_disabled "
                f"{data['note_disabled']['both_measures']}/3, note_enabled "
                f"{data['note_enabled']['both_measures']}/3"
            )

    assert pairs["after_all_found"], (
        f"(b1) wariant „po” bez wszystkich par; braki: "
        f"{[i for i in pairs['after'] if not i['found']]} (raport: {report_path})"
    )
    assert t14["equal_before_after"] == "tak", (
        f"(b2) liczby TABL. 14 zmienione przed/po korektą (raport: {report_path})"
    )
    if chat is not None and not chat["forced_found"]:
        pytest.fail(
            f"(c) nie znaleziono wymuszonych chunków trybu „oracle”: {chat['forced']} "
            f"(raport: {report_path})"
        )
