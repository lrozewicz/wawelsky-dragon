"""Finalizacja draftów: scalanie małych, overlap, numeracja i strony (CONTRACT WP E1-5 C8)."""

# Port z RAGFlow v0.27.2 rag/nlp/__init__.py (_apply_overlap_unconditional); Apache-2.0; NOTICE.

from collections.abc import Callable, Sequence
from dataclasses import replace

from app.domain.chunking.limits import split_sentences
from app.domain.chunking.types import ChunkConfig, ChunkDraft

MIN_CHUNK_TOKENS = 8


def _bc_prefix(path: tuple[str, ...]) -> str:
    return " > ".join(path) + "\n" if path else ""


def _body(draft: ChunkDraft) -> str:
    """Tekst draftu bez prefiksu breadcrumbu (C8)."""
    prefix = " > ".join(draft.heading_path) + "\n"
    if draft.heading_path and draft.text.startswith(prefix):
        return draft.text[len(prefix) :]
    return draft.text


def merge_small(drafts: list[ChunkDraft], cfg: ChunkConfig) -> list[ChunkDraft]:
    """Draft nie-tabela o mniej niż 8 tokenach scalany z poprzednim, inaczej z następnym (C8)."""
    merged: list[ChunkDraft] = []
    i = 0
    while i < len(drafts):
        draft = drafts[i]
        if draft.chunk_type == "table" or cfg.count_tokens(draft.text) >= MIN_CHUNK_TOKENS:
            merged.append(draft)
            i += 1
            continue
        with_prev = bool(merged) and merged[-1].chunk_type != "table"
        with_next = i + 1 < len(drafts) and drafts[i + 1].chunk_type != "table"
        if with_prev:
            neighbor = merged[-1]
            text = neighbor.text + "\n" + draft.text
            new_html = neighbor.html + draft.html
        elif with_next:
            neighbor = drafts[i + 1]
            text = draft.text + "\n" + neighbor.text
            new_html = draft.html + neighbor.html
        else:
            merged.append(draft)
            i += 1
            continue
        if cfg.count_tokens(text) > cfg.max_tokens:
            merged.append(draft)  # scalenie porzucone — mały draft zostaje sam
            i += 1
            continue
        replacement = replace(neighbor, text=text, html=new_html, tokens=cfg.count_tokens(text))
        if with_prev:
            merged[-1] = replacement
        else:
            merged.append(replacement)
            i += 1  # następny draft spożyty przez scalenie
        i += 1
    return merged


def _overlap_suffix(body: str, budget: int, count_tokens: Callable[[str], int]) -> str:
    """Najdłuższy SUFIKS listy zdań złączony spacją, o tokenach <= budget (C8)."""
    suffix = ""
    window: list[str] = []
    for sentence in reversed(split_sentences(body)):
        window.insert(0, sentence)
        candidate = " ".join(window)
        if count_tokens(candidate) > budget:
            break
        suffix = candidate
    return suffix


def _with_overlap(draft: ChunkDraft, prev: ChunkDraft, cfg: ChunkConfig) -> ChunkDraft:
    prev_body = _body(prev)
    budget = -(-cfg.count_tokens(prev_body) * cfg.overlapped_percent // 100)
    suffix = _overlap_suffix(prev_body, budget, cfg.count_tokens)
    if not suffix:
        return draft
    text = _bc_prefix(draft.heading_path) + suffix + "\n" + _body(draft)
    return replace(draft, text=text, tokens=cfg.count_tokens(text))


def apply_overlap(drafts: list[ChunkDraft], cfg: ChunkConfig) -> list[ChunkDraft]:
    """Overlap między sąsiednimi draftami nie-tabelami; liczony z ORYGINALNEGO poprzednika (C8)."""
    if cfg.overlapped_percent == 0:
        return drafts
    result: list[ChunkDraft] = []
    for i, draft in enumerate(drafts):
        current = draft
        if i > 0 and draft.chunk_type != "table" and drafts[i - 1].chunk_type != "table":
            current = _with_overlap(draft, drafts[i - 1], cfg)
        result.append(current)
    return result


def finalize(drafts: Sequence[ChunkDraft]) -> list[ChunkDraft]:
    """Ordinal 0..n-1 oraz page_from/page_to z min/max stron pozycji (C8)."""
    result: list[ChunkDraft] = []
    for ordinal, draft in enumerate(drafts):
        pages = [p[0] for p in draft.positions]
        result.append(
            replace(
                draft,
                ordinal=ordinal,
                page_from=min(pages) if pages else None,
                page_to=max(pages) if pages else None,
            )
        )
    return result
