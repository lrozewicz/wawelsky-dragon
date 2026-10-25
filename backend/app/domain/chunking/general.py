"""Algorytm ``general``: scalanie bloków w drafty (CONTRACT WP E1-5 C6)."""

# Port z RAGFlow v0.27.2 rag/nlp/__init__.py (naive_merge); Apache-2.0, InfiniFlow; zob. NOTICE.

import html
import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.chunking.delimiter import parse_delimiter_field, split_paragraphs
from app.domain.chunking.limits import split_to_limit
from app.domain.chunking.tables import chunk_table
from app.domain.chunking.types import (
    Block,
    BlockKind,
    ChunkConfig,
    ChunkDraft,
    ChunkPreset,
    ChunkType,
    DelimiterSpec,
    Position,
)

# Kawałek: (text, html, kind, positions).
_Piece = tuple[str, str, BlockKind, tuple[Position, ...]]

_CHUNK_TYPES_BY_KIND: dict[str, ChunkType] = {"list": "list", "code": "code", "figure": "image"}


def _breadcrumb(path: tuple[str, ...]) -> str:
    return " > ".join(path)


def _bc_text(path: tuple[str, ...]) -> str:
    return _breadcrumb(path) + "\n" if path else ""


def _bc_html(path: tuple[str, ...]) -> str:
    return f'<p class="breadcrumb">{html.escape(_breadcrumb(path))}</p>' if path else ""


@dataclass
class _Current:
    """Bieżący otwarty chunk: ścieżka pierwszego bloku i jego kawałki."""

    path: tuple[str, ...]
    pieces: list[_Piece]


def _piece_html(piece: str, kind: BlockKind) -> str:
    escaped = html.escape(piece)
    if kind == "code":
        return f"<pre><code>{escaped}</code></pre>"
    return f"<p>{escaped}</p>"


def _emit(cur: _Current, cfg: ChunkConfig) -> ChunkDraft:
    """Draft z kawałków bieżącego chunku (C6): tekst, html, typ, pozycje bez duplikatów."""
    bc = _bc_text(cur.path)
    text = bc + "\n".join(piece[0] for piece in cur.pieces)
    body_html = _bc_html(cur.path) + "".join(piece[1] for piece in cur.pieces)
    positions = tuple(dict.fromkeys(p for piece in cur.pieces for p in piece[3]))
    kinds = {piece[2] for piece in cur.pieces}
    chunk_type: ChunkType = "text"
    if len(kinds) == 1:
        chunk_type = _CHUNK_TYPES_BY_KIND.get(kinds.pop(), "text")
    return ChunkDraft(
        ordinal=-1,
        text=text,
        html=body_html,
        chunk_type=chunk_type,
        heading_path=cur.path,
        positions=positions,
        page_from=None,
        page_to=None,
        tokens=cfg.count_tokens(text),
        questions=(),
        metadata={},
    )


def _pieces_budget(
    cur: _Current | None,
    path: tuple[str, ...],
    limit: int,
    spec: DelimiterSpec,
    cfg: ChunkConfig,
) -> int:
    """Budżet podziału akapitu: limit pomniejszony o breadcrumb (C6 pkt 4)."""
    if spec.has_wrapped:
        return cfg.max_tokens - cfg.count_tokens(_bc_text(path))
    target = cur.path if cur is not None else path
    return max(1, limit - cfg.count_tokens(_bc_text(target)))


def _piece_htmls(block: Block, pieces: list[str], single: bool) -> list[str]:
    """HTML kawałków: block.html, gdy blok dał dokładnie jeden kawałek równy tekstowi (C6)."""
    if single:
        return [block.html] * len(pieces)
    return [_piece_html(piece, block.kind) for piece in pieces]


def chunk_general(
    blocks: Sequence[Block], preset: ChunkPreset, cfg: ChunkConfig
) -> list[ChunkDraft]:
    """Blok po bloku: nagłówki-granice i tabele zamykają chunk, treść scalana do limitu (C6)."""
    limit = max(1, cfg.chunk_token_num * (100 - cfg.overlapped_percent) // 100)
    spec = parse_delimiter_field(cfg.delimiter)
    boundaries = [re.compile(pattern) for pattern in preset.boundary_patterns]
    drafts: list[ChunkDraft] = []
    cur: _Current | None = None

    def close() -> None:
        nonlocal cur
        if cur is not None:
            drafts.append(_emit(cur, cfg))
            cur = None

    def add_piece(
        text: str,
        piece_html: str,
        kind: BlockKind,
        positions: tuple[Position, ...],
        path: tuple[str, ...],
    ) -> None:
        nonlocal cur
        if cur is not None:
            joined = _bc_text(cur.path) + "\n".join([p[0] for p in cur.pieces] + [text])
            if cfg.count_tokens(joined) > limit:
                close()
        if cur is None:
            cur = _Current(path=path, pieces=[])
        cur.pieces.append((text, piece_html, kind, positions))

    def add_block(block: Block) -> None:
        """C6 pkt 4: kawałki akapitu; tryb backticków — każdy kawałek osobnym draftem."""
        nonlocal cur
        parts = split_paragraphs(block.text, spec)
        if not parts:
            return
        path = block.heading_path
        budget = _pieces_budget(cur, path, limit, spec, cfg)
        pieces = [k for part in parts for k in split_to_limit(part, budget, cfg.count_tokens)]
        single = len(pieces) == 1 and pieces[0] == block.text.strip()
        htmls = _piece_htmls(block, pieces, single)
        if spec.has_wrapped:
            close()
            for piece, piece_html in zip(pieces, htmls, strict=True):
                cur = _Current(path=path, pieces=[(piece, piece_html, block.kind, block.positions)])
                close()
        else:
            for piece, piece_html in zip(pieces, htmls, strict=True):
                add_piece(piece, piece_html, block.kind, block.positions, path)

    for block in blocks:
        if block.kind == "heading":
            if block.level in preset.split_on_headings:
                close()  # granica; nagłówek nie jest treścią
            else:
                add_piece(block.text, block.html, "paragraph", block.positions, block.heading_path)
        elif block.kind == "table":
            close()
            drafts.extend(chunk_table(block, cfg))
        else:
            if block.kind == "paragraph" and any(b.match(block.text) for b in boundaries):
                close()
            add_block(block)
    close()
    return drafts
