"""Wzbogacanie chunków: słowa kluczowe i pytania promptami przez bramkę LLM (kontrakt C5).

Moduł czysty — bez bazy; portem jest ``LLMGateway`` (K5 §3.3). Szablony to własne sformułowania
(E5-7 T2); parsery ``parse_keywords``/``parse_questions`` zależą tylko od formatu wyjścia z C5
(słowa po przecinku, pytania po jednym w linii), nie od brzmienia promptu.
"""

import asyncio
import re
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass

from app.core.errors import WDError
from app.llm.gateway import LLMGateway
from app.llm.types import ModelRef

# Szablony wzbogacania: własne sformułowania (E5-7 T2). Zmienne ``{{ topn }}``/``{{ content }}``
# i format wyjścia zostają — patrz CONTRACT E5-7 §1/§2.
KEYWORD_PROMPT = """\
## Instruction
You extract keywords from one text fragment.

## Rules
- Give at most {{ topn }} keywords or short phrases that best capture the fragment.
- Write every keyword in the language of the fragment — never translate it.
- Separate the keywords with English commas.
- Return the keywords only, with no extra commentary.

## Fragment
{{ content }}"""

QUESTION_PROMPT = """\
## Instruction
You write questions for one text fragment.

## Rules
- Produce at most {{ topn }} questions that together cover the fragment's main content.
- Do not ask two questions that overlap in meaning.
- Keep each question in the language of the fragment — never translate it.
- Put one question per line.
- Return the questions only, with no extra commentary.

## Fragment
{{ content }}"""

ENRICH_CONCURRENCY = 4

_THINK_PREFIX = re.compile(r"^.*</think>", re.DOTALL)
_BULLET_PREFIX = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s*")
_EDGE_CHARS = " \t\r\n\"'\\."  # białe znaki plus cudzysłowy, ukośnik i kropki na końcach tokenu
_ERROR_MARKER = "**ERROR**"


def render(template: str, *, topn: int, content: str) -> str:
    """Podstawia ``{{ topn }}`` i ``{{ content }}`` (najpierw topn — treść może zawierać ``{{``)."""
    return template.replace("{{ topn }}", str(topn)).replace("{{ content }}", content)


def _dedup(items: Iterable[str], topn: int) -> list[str]:
    """Pomija puste, deduplikuje bez wielkości liter (zostaje pierwsze wystąpienie), maks. topn."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if not item or item.lower() in seen:
            continue
        if len(result) >= topn:
            break
        seen.add(item.lower())
        result.append(item)
    return result


def _without_think(raw: str) -> str:
    """Usuwa prefiks do ostatniego ``</think>`` (odpowiedzi modeli reasoningowych)."""
    return _THINK_PREFIX.sub("", raw)


def parse_keywords(raw: str, topn: int) -> list[str]:
    """Parsuje odpowiedź modelu na listę słów kluczowych (przecinki zwykłe i pełna szerokość)."""
    cleaned = _without_think(raw)
    if _ERROR_MARKER in cleaned:
        return []
    # pełna szerokość przecinka w regexie celowa — brief wymaga podziału po obu przecinkach
    tokens = (token.strip(_EDGE_CHARS) for token in re.split(r"[,，]", cleaned))  # noqa: RUF001
    return _dedup(tokens, topn)


def parse_questions(raw: str, topn: int) -> list[str]:
    """Parsuje odpowiedź modelu na listę pytań (po liniach, bez wiodącej numeracji/punktora)."""
    cleaned = _without_think(raw)
    if _ERROR_MARKER in cleaned:
        return []
    lines = (_BULLET_PREFIX.sub("", line).strip() for line in cleaned.splitlines())
    return _dedup(lines, topn)


@dataclass(frozen=True)
class Enrichment:
    """Słowa kluczowe i pytania jednego chunku."""

    keywords: tuple[str, ...] = ()
    questions: tuple[str, ...] = ()


async def _chat(llm: LLMGateway, model: ModelRef, template: str, *, topn: int, content: str) -> str:
    """Jedno wywołanie czatu kształtem RAGFlow: system = renderowany prompt, user = ``Output: ``."""
    messages: Sequence[dict[str, str]] = [
        {"role": "system", "content": render(template, topn=topn, content=content)},
        {"role": "user", "content": "Output: "},
    ]
    result = await llm.chat(model, messages, temperature=0.2, cache=True)
    return result.text


async def enrich_chunks(  # noqa: PLR0913
    llm: LLMGateway,
    model: ModelRef,
    texts: Sequence[str],
    *,
    auto_keywords: int,
    auto_questions: int,
    concurrency: int = ENRICH_CONCURRENCY,
    check_cancel: Callable[[], Awaitable[None]] | None = None,
) -> tuple[list[Enrichment], list[str]]:
    """Wzbogaca teksty słowami kluczowymi/pytaniami; wyniki w kolejności ``texts``.

    Współbieżność pojedynczych wywołań czatu ogranicza wspólny semafor. ``WDError`` z czatu
    daje pusty wynik dla danego rodzaju i ostrzeżenie („chunk i: … failed (Typ)"); inne
    wyjątki przerywają całość. Oba limity 0 → puste wzbogacenia bez wywołań. ``check_cancel``
    (jeśli podany) wołany jest przed każdym czatem; ``TaskCancelled`` przerywa ``gather``.
    """
    if auto_keywords <= 0 and auto_questions <= 0:
        return [Enrichment()] * len(texts), []
    sem = asyncio.Semaphore(concurrency)

    async def one(i: int, text: str) -> tuple[Enrichment, list[str]]:
        keywords: tuple[str, ...] = ()
        questions: tuple[str, ...] = ()
        warnings: list[str] = []
        if auto_keywords > 0:
            try:
                async with sem:
                    if check_cancel is not None:
                        await check_cancel()
                    raw = await _chat(llm, model, KEYWORD_PROMPT, topn=auto_keywords, content=text)
                keywords = tuple(parse_keywords(raw, auto_keywords))
            except WDError as exc:
                warnings.append(f"chunk {i}: keywords failed ({type(exc).__name__})")
        if auto_questions > 0:
            try:
                async with sem:
                    if check_cancel is not None:
                        await check_cancel()
                    raw = await _chat(
                        llm, model, QUESTION_PROMPT, topn=auto_questions, content=text
                    )
                questions = tuple(parse_questions(raw, auto_questions))
            except WDError as exc:
                warnings.append(f"chunk {i}: questions failed ({type(exc).__name__})")
        return Enrichment(keywords=keywords, questions=questions), warnings

    outcomes = await asyncio.gather(*(one(i, text) for i, text in enumerate(texts)))
    enrichments = [enrichment for enrichment, _ in outcomes]
    warnings = [warning for _, chunk_warnings in outcomes for warning in chunk_warnings]
    return enrichments, warnings
