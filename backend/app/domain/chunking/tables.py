"""Tabele: tekst wierszy i dzielenie tabeli na chunki (CONTRACT WP E1-5 C7)."""

import html
import logging
from collections.abc import Sequence

from app.domain.chunking.limits import split_to_limit
from app.domain.chunking.types import Block, ChunkConfig, ChunkDraft, TableData

logger = logging.getLogger(__name__)


def _breadcrumb(path: tuple[str, ...]) -> str:
    return " > ".join(path)


def _bc_text(path: tuple[str, ...]) -> str:
    return _breadcrumb(path) + "\n" if path else ""


def _bc_html(path: tuple[str, ...]) -> str:
    return f'<p class="breadcrumb">{html.escape(_breadcrumb(path))}</p>' if path else ""


def row_text(header: Sequence[str], row: Sequence[str]) -> str:
    """Pary "nazwa: wartość" dla kolumn z niepustą wartością, złączone "; " (C7)."""
    pairs: list[str] = []
    for i, value in enumerate(row):
        if not value.strip():
            continue
        name = header[i] if i < len(header) and header[i].strip() else f"column_{i + 1}"
        pairs.append(f"{name}: {value}")
    return "; ".join(pairs)


def _group_text(header: tuple[str, ...], rows: Sequence[tuple[str, ...]], html4excel: bool) -> str:
    """Tekst grupy wierszy; przy html4excel linia nagłówka na początku (gdy nagłówek niepusty)."""
    if not html4excel:
        return "\n".join(row_text(header, row) for row in rows)
    lines = [" | ".join(header)] if header else []
    lines.extend(" | ".join(row) for row in rows)
    return "\n".join(lines)


def table_text(table: TableData, html4excel: bool) -> str:
    """Tekst całej tabeli (C7): pary "kol: wart" albo linie " | " z nagłówkiem."""
    return _group_text(table.header, table.rows, html4excel)


def _draft(block: Block, text: str, fragment_html: str, cfg: ChunkConfig) -> ChunkDraft:
    return ChunkDraft(
        ordinal=-1,
        text=text,
        html=fragment_html,
        chunk_type="table",
        heading_path=block.heading_path,
        positions=block.positions,
        page_from=None,
        page_to=None,
        tokens=cfg.count_tokens(text),
        questions=(),
        metadata={},
    )


def _row_groups(t: TableData, bc: str, cfg: ChunkConfig) -> list[list[int]]:
    """Zachłanne grupowanie indeksów wierszy do limitu; nadmiarowy wiersz w grupie własnej."""
    groups: list[list[int]] = []
    current: list[int] = []
    for idx, row in enumerate(t.rows):
        single = bc + _group_text(t.header, [row], cfg.html4excel)
        if cfg.count_tokens(single) > cfg.chunk_token_num:
            if current:
                groups.append(current)
            groups.append([idx])
            current = []
            continue
        if current:
            candidate = [t.rows[i] for i in current] + [row]
            tekst = bc + _group_text(t.header, candidate, cfg.html4excel)
            if cfg.count_tokens(tekst) > cfg.chunk_token_num:
                groups.append(current)
                current = [idx]
                continue
        current.append(idx)
    if current:
        groups.append(current)
    return groups


def _split_html(t: TableData, group: list[int]) -> str:
    body = "".join(t.rows_html[i] for i in group)
    return "<table>" + t.header_html + "<tbody>" + body + "</tbody></table>"


def _group_drafts(
    t: TableData, block: Block, group: list[int], cfg: ChunkConfig
) -> list[ChunkDraft]:
    """Drafty jednej grupy; samotny wiersz ponad limit dzielony split_to_limit (C7 pkt 3)."""
    bc = _bc_text(block.heading_path)
    rows = [t.rows[i] for i in group]
    row_text_all = _group_text(t.header, rows, cfg.html4excel)
    fragment = _bc_html(block.heading_path) + _split_html(t, group)
    if len(group) == 1 and cfg.count_tokens(bc + row_text_all) > cfg.chunk_token_num:
        logger.warning("table row split", extra={"tokens": cfg.count_tokens(bc + row_text_all)})
        limit = cfg.chunk_token_num - cfg.count_tokens(bc)
        pieces = split_to_limit(row_text_all, limit, cfg.count_tokens)
        return [_draft(block, bc + piece, fragment, cfg) for piece in pieces]
    return [_draft(block, bc + row_text_all, fragment, cfg)]


def chunk_table(block: Block, cfg: ChunkConfig) -> list[ChunkDraft]:
    """Tabela → drafty (C7): jeden draft w limicie, inaczej dzielenie po wierszach."""
    bc = _bc_text(block.heading_path)
    bc_html = _bc_html(block.heading_path)
    if block.table is None:
        return [_draft(block, bc + block.text, bc_html + block.html, cfg)]
    t = block.table
    whole = bc + table_text(t, cfg.html4excel)
    if cfg.count_tokens(whole) <= cfg.chunk_token_num:
        return [_draft(block, whole, bc_html + block.html, cfg)]
    drafts: list[ChunkDraft] = []
    for group in _row_groups(t, bc, cfg):
        drafts.extend(_group_drafts(t, block, group, cfg))
    return drafts
