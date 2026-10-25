"""Dispatch chunkowania: ``chunk_blocks`` (CONTRACT WP E1-5 C9)."""

from collections.abc import Sequence

from app.domain.chunking.finalize import apply_overlap, finalize, merge_small
from app.domain.chunking.general import chunk_general
from app.domain.chunking.special import (
    chunk_one,
    chunk_presentation,
    chunk_qa,
    chunk_table_rows,
    strip_page_furniture,
)
from app.domain.chunking.types import Block, ChunkConfig, ChunkDraft, ChunkPreset


def chunk_blocks(
    blocks: Sequence[Block], preset: ChunkPreset, cfg: ChunkConfig
) -> list[ChunkDraft]:
    """Punkt wejścia chunkera: stopki paper przed dispatchem; wynik pusty → fallback C9."""
    if not blocks:
        return []
    if preset.strip_page_furniture:
        blocks = strip_page_furniture(blocks)
    drafts = _dispatch(blocks, preset, cfg)
    if drafts:
        return drafts
    return _heading_fallback(blocks, cfg)


def _dispatch(blocks: Sequence[Block], preset: ChunkPreset, cfg: ChunkConfig) -> list[ChunkDraft]:
    """Wybór trybu: general (C6+C8) albo presety specjalne (C10, tam też finalize)."""
    if preset.mode == "general":
        return finalize(apply_overlap(merge_small(chunk_general(blocks, preset, cfg), cfg), cfg))
    if preset.mode == "presentation":
        return chunk_presentation(blocks, cfg)
    if preset.mode == "one":
        return chunk_one(blocks, cfg)
    if preset.mode == "qa":
        return chunk_qa(blocks, cfg)
    return chunk_table_rows(blocks, cfg)


def _heading_fallback(blocks: Sequence[Block], cfg: ChunkConfig) -> list[ChunkDraft]:
    """Fallback C9: wynik pusty przy niepustym wejściu (np. same nagłówki) → jeden draft."""
    text = "\n".join(b.text for b in blocks if b.text.strip())
    if not text:
        return []
    positions = tuple(dict.fromkeys(p for b in blocks for p in b.positions))
    draft = ChunkDraft(
        ordinal=-1,
        text=text,
        html="".join(b.html for b in blocks),
        chunk_type="text",
        heading_path=(),
        positions=positions,
        page_from=None,
        page_to=None,
        tokens=cfg.count_tokens(text),
        questions=(),
        metadata={},
    )
    return finalize([draft])
