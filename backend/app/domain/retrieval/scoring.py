"""Scoring kandydatów: term_similarity, fuzja, progi, agregacje (CONTRACT WP E1-7 M3)."""

from collections.abc import Sequence
from itertools import pairwise

from app.domain.retrieval.types import (
    Candidate,
    ChunkTerms,
    DocAgg,
    FusionMode,
    QueryTerms,
    Scored,
    ThresholdConfig,
)

RRF_K = 60


def chunk_terms(
    content_stem: str, title_stem: str, important_stem: str, question_stem: str
) -> ChunkTerms:
    """Zbiór unigramów i bigramów ("a b") tokenów chunku.

    Port ``rag/nlp/search.py:516 i :548``: content deduplikowany, tytuł x2, ważne słowa x5,
    pytania x6; bigramy liczone po łańcuchu powtórzeń (także na granicach sekcji).
    """
    tokens = list(dict.fromkeys(content_stem.split()))
    tokens += title_stem.split() * 2
    tokens += important_stem.split() * 5
    tokens += question_stem.split() * 6
    return frozenset(tokens) | {f"{a} {b}" for a, b in pairwise(tokens)}


def term_similarity(q: QueryTerms, chunk: ChunkTerms) -> float:
    """Udział wagi termów zapytania obecnych w chunku; pusta suma wag → 0.0 (R0 p. 9)."""
    total = sum(w for _, w in q.terms) + sum(w for _, w in q.bigrams)
    if total == 0:
        return 0.0
    hit = sum(w for t, w in q.terms if t in chunk) + sum(w for b, w in q.bigrams if b in chunk)
    return hit / total


def _ranks(values: Sequence[float]) -> list[int]:
    """Rangi 1-based malejąco; remis → kolejność wejścia (sort Pythona jest stabilny)."""
    order = sorted(range(len(values)), key=lambda i: values[i], reverse=True)
    ranks = [0] * len(values)
    for place, index in enumerate(order):
        ranks[index] = place + 1
    return ranks


def _rrf_raws(cands: Sequence[Candidate]) -> list[float]:
    """Suma 1/(RRF_K + ranga) po vector/term_similarity i (gdy MA każdy kandydat) rerank_score."""
    n = len(cands)
    raw = [0.0] * n
    fields: list[list[float]] = [
        [c.vector_similarity for c in cands],
        [c.term_similarity for c in cands],
    ]
    reranks = [c.rerank_score for c in cands]
    if all(score is not None for score in reranks):
        fields.append([score for score in reranks if score is not None])
    for values in fields:
        for i, rank in enumerate(_ranks(values)):
            raw[i] += 1.0 / (RRF_K + rank)
    return raw


def rank_key(scored: Scored) -> tuple[float, str, int, str]:
    """Klucz porządku wyników: ``(-similarity, document_name, ordinal, chunk_id)`` (C3).

    Remisy similarity rozstrzyga nazwa dokumentu, pozycja chunku, a na końcu id —
    kolejność jest deterministyczna i niezależna od kolejności wstawienia i losowych id.
    """
    c = scored.candidate
    return (-scored.similarity, c.document_name, c.ordinal, c.chunk_id)


def fuse(cands: Sequence[Candidate], w: float, mode: FusionMode) -> list[Scored]:
    """Fuzja kandydatów; wynik posortowany malejąco po similarity z kluczem wtórnym ``rank_key``.

    ``weighted``: similarity = (1 - w) * term + w * (rerank gdy jest, inaczej vector).
    ``rrf``: rangi 1-based (remis → kolejność wejścia), suma 1/(RRF_K + ranga),
    min-max w obrębie wywołania; remis ogólny → 1.0 dla każdego. ``w`` ignorowane.
    """
    if not cands:
        return []
    if mode == "rrf":
        raws = _rrf_raws(cands)
        low, high = min(raws), max(raws)
        span = high - low
        scored = [
            Scored(c, 1.0 if span == 0 else (raw - low) / span)
            for c, raw in zip(cands, raws, strict=True)
        ]
    else:
        scored = [
            Scored(
                c,
                (1 - w) * c.term_similarity
                + w * (c.rerank_score if c.rerank_score is not None else c.vector_similarity),
            )
            for c in cands
        ]
    return sorted(scored, key=rank_key)


def apply_thresholds(
    scored: Sequence[Scored], cfg: ThresholdConfig, w: float, user_threshold: float
) -> list[Scored]:
    """Filtry progów (06 §3.6); kolejność zachowana.

    Odrzuca gdy: (1) brak trafienia termowego i cosinus < min_vector_sim;
    (2) rerank < min_rerank_score; (3) similarity < progu końcowego
    (0.0 przy ``w <= 0``, inaczej próg użytkownika) — port ``rag/nlp/search.py:690-693``.
    """
    post = 0.0 if w <= 0 else user_threshold
    valid: list[Scored] = []
    for s in scored:
        c = s.candidate
        if c.term_similarity <= 0 and c.vector_similarity < cfg.min_vector_sim:
            continue
        if c.rerank_score is not None and c.rerank_score < cfg.min_rerank_score:
            continue
        if s.similarity < post:
            continue
        valid.append(s)
    return valid


def doc_aggs(scored: Sequence[Scored]) -> list[DocAgg]:
    """Agregacja po dokumentach: licznik malejąco, remis → kolejność pierwszego wystąpienia."""
    counts: dict[str, tuple[str, int]] = {}
    for s in scored:
        c = s.candidate
        name, count = counts.get(c.document_id, (c.document_name, 0))
        counts[c.document_id] = (name, count + 1)
    aggs = [
        DocAgg(doc_name=name, doc_id=doc_id, count=count)
        for doc_id, (name, count) in counts.items()
    ]
    return sorted(aggs, key=lambda a: -a.count)
