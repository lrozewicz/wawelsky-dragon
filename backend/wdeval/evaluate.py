"""Pętla ewaluacji: orkiestracja ask/judge, werdykty i porównania ramion (kontrakt C14).

Port orkiestratora bety (``B/eval/run.py:run_evaluation``) na sygnaturę C14:
ramiona to nazwy (bez korpusów — wszystkie mierzą ten sam zestaw pozycji),
odpowiedź ramienia to ``Answer`` (tekst + chunki z referencji). Cytowania WD
``[ID:n]`` są przed sędzią tłumaczone na ``[n+1]`` (C6.3), żeby prompt sędziego
został bez zmian.

Adaptery produkcyjne (``make_ask``/``make_judge``) importują ``app.*`` dopiero
wewnątrz funkcji — reszta modułu testuje się bez bazy i bez sieci.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from wdeval.aggregate import Aggregate, ItemResult, aggregate_results
from wdeval.dataset import EvalItem
from wdeval.judge import JudgeRunner, Verdict
from wdeval.judge_env import JudgeEndpoint, make_env_chat
from wdeval.metrics import (
    ChunkView,
    answer_correct,
    classify_miss,
    doc_recall_at_k,
    fragment_recall_at_k,
)

if TYPE_CHECKING:
    from app.core.container import Container
    from app.domain.policy.principal import Principal
    from wdeval.llm_models import LiveModels

_CITATION_RE = re.compile(r"\[\d+\]")
_ID_CITATION_RE = re.compile(r"\[ID:\d+\]")
_COMPARISON_MIN_ARMS = 2  # poniżej dwóch ramion nie ma czego porównywać (jak w becie)


class DocumentNameGuardError(RuntimeError):
    """Nazwa ``source.file`` z datasetu nie została wgrana do ramienia.

    Bez tego strażnika każdy fragment zawężałby się do pustego zbioru chunków
    i cały dataset czytałby się jako ``parse-miss`` (recall 0), bez sygnału błędu.
    """


@dataclass(frozen=True)
class Answer:
    """Odpowiedź ramienia na pytanie: tekst czatu + chunki z referencji."""

    text: str
    chunks: list[ChunkView]


AskFn = Callable[[str, str], Awaitable[Answer]]  # (arm, question)
JudgeFn = Callable[[str, dict[str, str]], Awaitable[Verdict]]  # (kind, payload)
AllChunksFn = Callable[[str], Awaitable[list[ChunkView]]]  # (arm)


@dataclass(frozen=True)
class RunResult:
    """Wynik biegu: wyniki pozycji (kolejność ramiona x pozycja), agregaty i porównania."""

    results: list[tuple[EvalItem, ItemResult]]
    aggregates: list[Aggregate]
    comparisons: list[dict[str, Any]]


def to_beta_citations(answer: str) -> str:
    """Tłumaczy markery WD ``[ID:n]`` na cytowania bety ``[n+1]`` (kontrakt C6.3)."""
    return re.sub(r"\[ID:(\d+)\]", lambda m: f"[{int(m.group(1)) + 1}]", answer)


def _has_citation_marker(answer: str) -> bool:
    return bool(_ID_CITATION_RE.search(answer))


def _build_judge_context(chunks: list[ChunkView]) -> str:
    """Kontekst dla sędziego: źródła ponumerowane tak, jak oczekują prompty (format bety)."""
    return "\n\n".join(
        f"[Źródło {i + 1}] ({chunk.doc_name})\n{chunk.content}" for i, chunk in enumerate(chunks)
    )


def _build_comparisons(
    arms: list[str], measured_ids: dict[str, set[str]], *, total: int
) -> list[dict[str, Any]]:
    """Port ``_build_comparisons`` bety: jeden wpis, gdy ramion jest co najmniej dwa."""
    arm_names = sorted(set(arms))
    if len(arm_names) < _COMPARISON_MIN_ARMS:
        return []
    common = set.intersection(*(measured_ids.get(name, set()) for name in arm_names))
    return [
        {
            "arms": arm_names,
            "common_question_ids": sorted(common),
            "common_count": len(common),
            "total": total,
        }
    ]


async def run_evaluation(  # noqa: PLR0913 — sygnatura dosłownie z kontraktu C14
    items: list[EvalItem],
    arms: list[str],
    *,
    ask: AskFn,
    judge: JudgeFn,
    all_chunks: AllChunksFn,
    documents: dict[str, set[str]],
    k_list: list[int],
) -> RunResult:
    """Wykonaj bieg ewaluacyjny na wstrzykniętych zależnościach; deterministyczny
    przy deterministycznych atrapach (sens docstringu bety).

    Pozycje mierzone są sekwencyjnie, ramiona w kolejności wejścia. ``all_chunks``
    wołany RAZ NA RAMIĘ (``classify_miss`` potrzebuje wszystkich chunków KB).
    """
    if not arms:
        return RunResult(results=[], aggregates=[], comparisons=[])

    chunks_by_arm: dict[str, list[ChunkView]] = {arm: await all_chunks(arm) for arm in arms}

    # Strażnik nazw dokumentów: ``documents`` (co zasiano) i chunki w KB to dwa
    # niezależne źródła prawdy — patrz docstring ``DocumentNameGuardError``.
    for arm in arms:
        seeded = {name.casefold() for name in documents.get(arm, set())}
        missing = {
            source.file
            for item in items
            for source in item.sources
            if source.file.casefold() not in seeded
        }
        if missing:
            raise DocumentNameGuardError(
                f"ramię {arm}: brakujące dokumenty źródeł: {sorted(missing)}"
            )

    results: list[tuple[EvalItem, ItemResult]] = []
    measured_ids: dict[str, set[str]] = {}

    for arm in arms:
        all_kb_chunks = chunks_by_arm[arm]
        for item in items:
            ans = await ask(arm, item.question)
            chunks = ans.chunks

            fragment_recall = {k: fragment_recall_at_k(item, chunks, k) for k in k_list}
            doc_recall = {k: doc_recall_at_k(item, chunks, k) for k in k_list}

            verdicts: dict[str, Verdict] = {}
            empty_path: str | None = None
            miss_kind: str | None = None
            correct = False
            cited = to_beta_citations(ans.text)

            if item.answerable:
                correct = answer_correct(item, ans.text)
                miss_kind = classify_miss(item, chunks, all_kb_chunks)
                if ans.text.strip():
                    verdicts["grounded"] = await judge(
                        "grounded",
                        {
                            "question": item.question,
                            "context": _build_judge_context(chunks),
                            "answer": cited,
                        },
                    )
            else:
                empty_ok = await judge("empty_ok", {"question": item.question, "answer": cited})
                verdicts["empty_ok"] = empty_ok
                if not chunks:
                    empty_path = "no_chunks"
                elif empty_ok.value:
                    empty_path = "prose_refusal"

            if _has_citation_marker(ans.text):
                verdicts["citation_ok"] = await judge(
                    "citation_ok",
                    {
                        "question": item.question,
                        "context": _build_judge_context(chunks),
                        "answer": cited,
                    },
                )

            result = ItemResult(
                item_id=item.id,
                source=item.source,
                language=item.language,
                group=item.group,
                arm=arm,
                answer=ans.text,
                answer_correct=correct,
                fragment_recall=fragment_recall,
                doc_recall=doc_recall,
                miss_kind=miss_kind,
                verdicts=verdicts,
                empty_path=empty_path,
                retrieved_chunks=[c.key for c in chunks],
            )
            results.append((item, result))
            measured_ids.setdefault(arm, set()).add(item.id)

    aggregates = aggregate_results(results, k_list)
    comparisons = _build_comparisons(arms, measured_ids, total=len(items))
    return RunResult(results=results, aggregates=aggregates, comparisons=comparisons)


def make_ask(
    container: Container,
    principal: Principal,
    chat_ids: dict[str, str],
    chunk_index: dict[str, dict[str, ChunkView]],
) -> AskFn:
    """Adapter odpowiedzi: czat WD na konfiguracji ramienia; chunki z referencji.

    ``chunk_index[arm]`` mapuje id chunka WD na ``ChunkView``; chunk spoza indeksu
    to bieg zepsuty — ``RuntimeError`` z id, nie ciche pominięcie.
    """

    async def ask(arm: str, question: str) -> Answer:
        from app.services.chat import CompletionRequest  # noqa: PLC0415 — app.* dopiero tutaj

        result = await container.chat.complete_once(
            principal,
            CompletionRequest(
                chat_id=chat_ids[arm],
                session_id=None,
                messages=({"role": "user", "content": question},),
                quote=True,
            ),
        )
        refs: list[Any] = list(result.reference.get("chunks", []))
        index = chunk_index.get(arm, {})
        chunks: list[ChunkView] = []
        for ref in refs:
            chunk_id = ref["id"]
            view = index.get(chunk_id)
            if view is None:
                raise RuntimeError(f"chunk {chunk_id} poza indeksem ramienia {arm}")
            chunks.append(view)
        return Answer(text=result.answer, chunks=chunks)

    return ask


def make_judge(
    container: Container, models: LiveModels, endpoint: JudgeEndpoint | None = None
) -> JudgeFn:
    """Adapter sędziego (C2): bramka LLM WD albo osobny endpoint ``WD_JUDGE_*``.

    ``endpoint is None`` — ścieżka bramki bez zmian (parametr ``extra``, nie
    ``extra_body``). Inaczej sędzia woła wprost endpoint (``wdeval.judge_env``),
    a bramka zostaje tylko dla modeli odpowiadających.
    """
    if endpoint is not None:
        return JudgeRunner(
            model_name=models.judge,
            chat=make_env_chat(endpoint, models.judge_mode),
            mode=models.judge_mode,
        )

    async def chat(
        model_name: str,
        messages: list[dict[str, str]],
        *,
        temperature: float | None,
        extra_body: Any,
    ) -> str:
        gateway = container.llm
        registry = container.models
        if gateway is None or registry is None:
            raise RuntimeError("container not started")
        ref = await registry.resolve(model_name, "chat")
        result = await gateway.chat(ref, messages, temperature=temperature, extra=extra_body)
        return result.text

    runner = JudgeRunner(model_name=models.judge, chat=chat, mode=models.judge_mode)
    return runner
