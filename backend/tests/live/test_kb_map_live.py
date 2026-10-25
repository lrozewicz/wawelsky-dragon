"""Test live (marker ``live``) mapy bazy wiedzy (K21 §4, SC-V13-01 k2 wariant live) — T8.

Opt-in — uruchamia TL: ``tools/dev/live.sh pytest-live tests/live/test_kb_map_live.py``.

Cel: sprawdzić, że prawdziwy model czatu z ``.env`` (ten sam co w pozostałych testach live:
``WD_EVAL_CHAT_MODEL``, domyślnie ``gpt-5.4-nano``) na pytanie o zawartość bazy
(„Co zawiera twoja baza wiedzy? Na jakie tematy możesz udzielić informacji?”) wymienia
wszystkie 28 działów rocznika GUS.

Bez bazy MariaDB i bez embeddingów: prompt składamy ręcznie z realnych funkcji domeny
(``is_kb_overview_question``, ``build_map_section``, ``build_system`` z ``citation_prompt``),
z ``CatalogDoc`` zbudowanym z prawdziwego PDF przez ``outline_from_pdf``. Wybrano ręczne
składanie zamiast całego ``chat_pipeline``, bo pipeline wymaga sesji DB, retrievalu i
kontenera zależności — a ten test sprawdza wyłącznie mapę i odpowiedź modelu (jedno wywołanie).

Sekcja mapy trafia na koniec wiadomości systemowej (K21 §3 p. 2, tak samo jak w
``chat_pipeline._pipeline``: ``system + "\\n\\n" + section``), z limitem
``min(WD_CHAT_KB_MAP_TOKENS, 0,3 razy max_tokens modelu)`` (K21 §4 p. 2).

Limit kosztu: jedno wywołanie LLM. Raport JSON (odpowiedź, brakujące działy, zużycie tokenów —
bez kluczy) do ``work/wp/V13-1/reports/live-map-answer.json`` (nadpisywalne ``WD_KB_MAP_REPORT``).

Asercja jest MIĘKKA (K21 §4 p. 2, decyzję podejmuje Architekt): brakujące działy są raportowane,
a test pada tylko przy błędzie wywołania albo pustej odpowiedzi.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.db.repositories.document_profiles import CatalogDoc
from app.domain.chat.config import DEFAULT_PROMPT_CONFIG
from app.domain.chat.kb_overview import build_map_section, is_kb_overview_question
from app.domain.chat.prompts import build_system, citation_prompt
from app.llm.openai_gateway import OpenAIGateway
from app.llm.tokens import count_tokens
from app.llm.types import ModelRef
from app.parsing.outline import outline_from_pdf
from tests.live import test_diacritics_eval as eval_a

# Model czatu jak w pozostałych testach live (``test_chat_unemployment_eval``), nadpisywalny.
CHAT_MODEL_DEFAULT = "gpt-5.4-nano"
# Pytanie z zestawu kontraktu K21 §4 p. 1 (SC-V13-01 k2).
QUESTION = "Co zawiera twoja baza wiedzy? Na jakie tematy możesz udzielić informacji?"
# Budżet modelu (jak domyślny ``ctx.model.max_tokens`` w pipeline) i limit sekcji mapy.
MODEL_MAX_TOKENS = 8192
# Limit odpowiedzi modelu (K21: ≥ 2000), żeby zmieściło się wyliczenie 28 działów.
ANSWER_MAX_TOKENS = 4000
DOCUMENT_NAME = "gus_rocznik_statystyczny_rp_2024.pdf"
DATASET_NAME = "GUS PL"
REPORT_REL = "work/wp/V13-1/reports/live-map-answer.json"

_LLM_READY = bool(os.environ.get("WD_LLM_BASE_URL") and os.environ.get("WD_LLM_API_KEY"))

# Tytuł działu: „DZIAŁ <rzymskie> <treść>”.
_DZIAL_RE = re.compile(r"^DZIAŁ\s+[IVXL]+\s+(?P<rest>.+)$")
# Słowa treści tytułu (wielkie litery, z polskimi znakami).
_WORD_RE = re.compile(r"[A-ZĄĆĘŁŃÓŚŹŻ]+")

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not _LLM_READY,
        reason="live: brak WD_LLM_BASE_URL/WD_LLM_API_KEY (test tylko przez tools/dev/live.sh)",
    ),
]

# 28 działów rocznika GUS (K21 §4 p. 2). Tytuły zakładek poziomu 0 zaczynające się od „DZIAŁ”.
_DZIAL_COUNT = 28


def _chat_model() -> ModelRef:
    """Referencja modelu czatu z ``WD_EVAL_CHAT_MODEL`` (domyślnie ``gpt-5.4-nano``)."""
    return ModelRef(
        id=None,
        name=os.environ.get("WD_EVAL_CHAT_MODEL", CHAT_MODEL_DEFAULT),
        model_type="chat",
        base_url=os.environ["WD_LLM_BASE_URL"],
        api_key=SecretStr(os.environ["WD_LLM_API_KEY"]),
    )


def _gateway() -> OpenAIGateway:
    """Bramka LLM z ``WD_LLM_*`` (jak inne testy live)."""
    return OpenAIGateway(
        Settings(
            env="test",
            llm_base_url=os.environ["WD_LLM_BASE_URL"],
            llm_api_key=SecretStr(os.environ["WD_LLM_API_KEY"]),
            llm_max_retries=0,
        )
    )


def _pdf_path() -> Path:
    """Ścieżka PDF rocznika GUS z ``WD_OCR_PDF`` (domyślnie ``../dataset/documents/pl/pdf``)."""
    default = eval_a._main_root().parent / "dataset/documents/pl/pdf" / DOCUMENT_NAME
    return Path(os.environ.get("WD_OCR_PDF", default))


def _catalog(pdf_path: Path) -> CatalogDoc:
    """``CatalogDoc`` rocznika GUS z prawdziwego PDF (zakładki przez ``outline_from_pdf``)."""
    return CatalogDoc(
        document_id="live-gus-rocznik-2024",
        document_name=DOCUMENT_NAME,
        dataset_id="live-gus",
        dataset_name=DATASET_NAME,
        outline=outline_from_pdf(pdf_path),
        outline_source="pdf_bookmarks",
    )


def _dzial_titles(doc: CatalogDoc) -> list[str]:
    """Tytuły działów (pozycje ``level == 0`` zaczynające się od „DZIAŁ”); K21 §4 p. 2."""
    return [
        item["title"]
        for item in doc.outline
        if item["level"] == 0 and item["title"].upper().startswith("DZIAŁ")
    ]


def _keywords(titles: Sequence[str]) -> list[tuple[str, str]]:
    """Pary (tytuł działu, słowo kluczowe) — pierwsze rzeczowe słowo UNIKALNE wśród działów.

    Bierzemy pierwsze słowo treści tytułu (po „DZIAŁ <rzymskie>”, pomijając spójnik „I”),
    które nie jest podciągiem żadnego innego tytułu działu. Kolizje („HANDEL” XX/XXI,
    „FINANSE” XXII/XXIV, „OCHRONA” II/XII, „RYNEK” VII/XXIII) rozwiązuje kolejne słowo —
    dzięki temu każde słowo kluczowe wskazuje inny dział (inaczej jeden „HANDEL” zaliczyłby dwa).
    """
    rests: list[str] = []
    for title in titles:
        match = _DZIAL_RE.match(title)
        rests.append(match.group("rest") if match else title)
    out: list[tuple[str, str]] = []
    for index, title in enumerate(titles):
        others = [rest.lower() for j, rest in enumerate(rests) if j != index]
        words = [w for w in _WORD_RE.findall(rests[index]) if w != "I"]
        keyword = next(
            (w for w in words if not any(w.lower() in other for other in others)),
            words[0] if words else rests[index],
        )
        out.append((title, keyword))
    return out


def _system_prompt(doc: CatalogDoc) -> str:
    """Wiadomość systemowa z mapą na końcu (K21 §3 p. 2, §4 p. 2) — jak ``chat_pipeline``."""
    map_tokens = min(Settings(env="test").chat_kb_map_tokens, int(MODEL_MAX_TOKENS * 0.3))
    section = build_map_section([doc], max_tokens=map_tokens, count_tokens=count_tokens)
    system = build_system(
        citation_prompt(str(DEFAULT_PROMPT_CONFIG["system"])),
        [],
        DEFAULT_PROMPT_CONFIG["parameters"],
        {"date": "2026-10-17 00:00:00"},
    )
    return system + ("\n\n" + section if section else "")


async def test_kb_map_live_lists_all_gus_departments() -> None:
    """Prawdziwy model wymienia 28 działów GUS z mapy; braki raportowane (assert miękki)."""
    pdf_path = _pdf_path()
    if not pdf_path.exists():
        pytest.skip(f"live: brak pliku PDF: {pdf_path}")

    doc = _catalog(pdf_path)
    keywords = _keywords(_dzial_titles(doc))
    assert len(keywords) == _DZIAL_COUNT, (
        f"oczekiwano {_DZIAL_COUNT} działów w zakładkach PDF, jest {len(keywords)}: "
        f"{[t for t, _ in keywords]}"
    )
    assert is_kb_overview_question(QUESTION), "pytanie nie rozpoznane jako pytanie o bazę (K21 §4)"

    report_path = Path(os.environ.get("WD_KB_MAP_REPORT", eval_a._checkout_root() / REPORT_REL))
    model = _chat_model()
    messages = [
        {"role": "system", "content": _system_prompt(doc)},
        {"role": "user", "content": QUESTION},
    ]

    gateway = _gateway()
    try:
        result = await gateway.chat(model, messages, temperature=0.0, max_tokens=ANSWER_MAX_TOKENS)
    finally:
        await gateway.aclose()

    answer = result.text.strip()
    # Słowo kluczowe na granicach słowa (regex z IGNORECASE|UNICODE), nie po podciągu —
    # „RYNEK” nie ma zaliczać np. „przezraganicznych” form z tym samym fragmentem.
    missing = [
        title
        for title, keyword in keywords
        if re.search(rf"\b{re.escape(keyword)}\b", answer, re.IGNORECASE | re.UNICODE) is None
    ]
    report: dict[str, Any] = {
        "question": QUESTION,
        "chat_model": model.name,
        "answer": answer,
        "departments_total": len(keywords),
        "departments_present": len(keywords) - len(missing),
        "missing": missing,
        "keywords": {title: keyword for title, keyword in keywords},
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
        "finish_reason": result.finish_reason,
    }
    eval_a._write_json(report_path, report)

    print(
        f"działy: {report['departments_present']}/{report['departments_total']} "
        f"(braki: {missing}); tokeny in/out: {result.tokens_in}/{result.tokens_out}"
    )
    if not answer:
        pytest.fail(f"pusta odpowiedź modelu (raport: {report_path})")
