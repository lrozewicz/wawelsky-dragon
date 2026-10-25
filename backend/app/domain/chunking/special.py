"""Presety specjalne: presentation, one, qa, table i stopki paper (CONTRACT WP E1-5 C10)."""

import re
from collections.abc import Mapping, Sequence
from html import escape

from app.domain.chunking.errors import DocumentTooLarge
from app.domain.chunking.finalize import apply_overlap, finalize, merge_small
from app.domain.chunking.general import chunk_general
from app.domain.chunking.limits import split_to_limit
from app.domain.chunking.presets import preset_for
from app.domain.chunking.types import Block, ChunkConfig, ChunkDraft, Position, TableData

# Para Q/A: (pytanie, odpowiedź, pozycje, heading_path).
_QaPair = tuple[str, str, tuple[Position, ...], tuple[str, ...]]

_Q_RE = re.compile(r"(?i)^\s*(q|question|pytanie)\s*[:：]\s*(.*)$")  # noqa: RUF001 — pełnośrednik z kontraktu C10.3
_A_RE = re.compile(r"(?i)^\s*(a|answer|odpowiedź)\s*[:：]\s*(.*)$")  # noqa: RUF001 — pełnośrednik z kontraktu C10.3
_PAGE_NO_RE = re.compile(r"(?i)\s*(page\s+|strona\s+)?\d+(\s*(/|of|z)\s*\d+)?\s*")
_DIGITS_RE = re.compile(r"\d+")

_FURNITURE_WORD_LIMIT = 12
_FURNITURE_SECTIONS = 3

_TEXT_QA_KINDS = ("paragraph", "list", "notes", "code")


def _general_naive(blocks: Sequence[Block], cfg: ChunkConfig) -> list[ChunkDraft]:
    """Ścieżka awaryjna „jak naive”: C6 + C8 (merge_small, overlap, finalize)."""
    drafts = chunk_general(blocks, preset_for("naive"), cfg)
    return finalize(apply_overlap(merge_small(drafts, cfg), cfg))


def _base_draft(
    text: str, fragment_html: str, cfg: ChunkConfig, positions: tuple[Position, ...]
) -> ChunkDraft:
    """Draft tekstowy bez breadcrumbu (C10): ordinal=-1, strony wypełnia finalize."""
    return ChunkDraft(
        ordinal=-1,
        text=text,
        html=fragment_html,
        chunk_type="text",
        heading_path=(),
        positions=positions,
        page_from=None,
        page_to=None,
        tokens=cfg.count_tokens(text),
        questions=(),
        metadata={},
    )


def _qa_draft(
    q: str, a: str, positions: tuple[Position, ...], path: tuple[str, ...], cfg: ChunkConfig
) -> ChunkDraft:
    """Draft pary Q/A (C10.3): tekst „Question: …\\tAnswer: …”, questions=(q,)."""
    text = f"Question: {q}\tAnswer: {a}"
    return ChunkDraft(
        ordinal=-1,
        text=text,
        html=f"<p>{escape(q)}</p><p>{escape(a)}</p>",
        chunk_type="qa",
        heading_path=path,
        positions=positions,
        page_from=None,
        page_to=None,
        tokens=cfg.count_tokens(text),
        questions=(q,),
        metadata={},
    )


def _table_row_draft(
    text: str,
    fragment_html: str,
    cfg: ChunkConfig,
    positions: tuple[Position, ...],
    metadata: Mapping[str, str],
) -> ChunkDraft:
    """Draft wiersza tabeli (C10.4): chunk_type „table”, metadata wg ról kolumn."""
    return ChunkDraft(
        ordinal=-1,
        text=text,
        html=fragment_html,
        chunk_type="table",
        heading_path=(),
        positions=positions,
        page_from=None,
        page_to=None,
        tokens=cfg.count_tokens(text),
        questions=(),
        metadata=metadata,
    )


# -- presentation (C10.1) --


def chunk_presentation(blocks: Sequence[Block], cfg: ChunkConfig) -> list[ChunkDraft]:
    """Slajdy: grupy kolejnych bloków o równym section; żaden blok bez section → naive."""
    if not any(block.section for block in blocks):
        return _general_naive(blocks, cfg)
    drafts: list[ChunkDraft] = []
    group: list[Block] = []
    for block in blocks:
        if group and group[0].section != block.section:
            drafts.extend(_slide_drafts(group, cfg))
            group = []
        group.append(block)
    if group:
        drafts.extend(_slide_drafts(group, cfg))
    return finalize(drafts)


def _slide_drafts(group: list[Block], cfg: ChunkConfig) -> list[ChunkDraft]:
    """Drafty slajdu: teksty nie-notes w kolejności + notes na końcu; podział ponad max_tokens."""
    main = [block for block in group if block.kind != "notes"]
    notes = [block for block in group if block.kind == "notes"]
    text = "\n".join([b.text for b in main] + [b.text for b in notes])
    if not text.strip():
        return []
    page_html = "".join(b.html for b in main) + "".join(b.html for b in notes)
    positions = tuple(dict.fromkeys(p for block in group for p in block.positions))
    if cfg.count_tokens(text) > cfg.max_tokens:
        return [
            _base_draft(piece, f"<p>{escape(piece)}</p>", cfg, positions)
            for piece in split_to_limit(text, cfg.max_tokens, cfg.count_tokens)
        ]
    return [_base_draft(text, page_html, cfg, positions)]


# -- one / picture (C10.2) --


def chunk_one(blocks: Sequence[Block], cfg: ChunkConfig) -> list[ChunkDraft]:
    """Cały dokument jednym chunkiem; ponad max_tokens → DocumentTooLarge (C10.2)."""
    text = "\n".join(b.text for b in blocks if b.text.strip())
    if not text:
        return []
    tokens = cfg.count_tokens(text)
    if tokens > cfg.max_tokens:
        raise DocumentTooLarge(tokens, cfg.max_tokens)
    positions = tuple(dict.fromkeys(p for block in blocks for p in block.positions))
    return finalize([_base_draft(text, "".join(b.html for b in blocks), cfg, positions)])


# -- qa (C10.3) --


def chunk_qa(blocks: Sequence[Block], cfg: ChunkConfig) -> list[ChunkDraft]:
    """Pary pytanie-odpowiedź: z tabel, potem z tekstu, awaryjnie z nagłówków (C10.3)."""
    pairs = _qa_table_pairs(blocks)
    pairs.extend(_qa_text_pairs(blocks))
    if not pairs:
        pairs = _qa_heading_pairs(blocks)
    if not pairs:
        return _general_naive(blocks, cfg)
    drafts = [
        _qa_draft(q.strip(), a.strip(), positions, path, cfg) for q, a, positions, path in pairs
    ]
    return finalize(drafts)


def _qa_cells(cells: Sequence[str]) -> tuple[str, str] | None:
    """Pierwsza niepusta komórka = q, druga = a; brak obu → None (jak upstream qa.py)."""
    q = ""
    a = ""
    for cell in cells:
        if not cell.strip():
            continue
        if not q:
            q = cell
        elif not a:
            a = cell
        else:
            break
    if q.strip() and a.strip():
        return (q, a)
    return None


def _qa_table_pairs(blocks: Sequence[Block]) -> list[_QaPair]:
    """Pary z tabel: [header] + rows (header tylko gdy niepusty); pozycje bloku tabeli."""
    pairs: list[_QaPair] = []
    for block in blocks:
        table: TableData | None = block.table
        if table is None:
            continue
        sequences: list[tuple[str, ...]] = [table.header] if table.header else []
        sequences.extend(table.rows)
        for cells in sequences:
            pair = _qa_cells(cells)
            if pair is not None:
                pairs.append((pair[0], pair[1], block.positions, ()))
    return pairs


def _qa_text_pairs(blocks: Sequence[Block]) -> list[_QaPair]:
    """Pary z linii Q:/A: bloków tekstowych; kontynuacja dopisywana do q albo a."""
    pairs: list[_QaPair] = []
    q: str | None = None
    a: str | None = None
    positions: tuple[Position, ...] = ()

    def save() -> None:
        if q is not None and a is not None and q.strip() and a.strip():
            pairs.append((q, a, positions, ()))

    for block in blocks:
        if block.kind not in _TEXT_QA_KINDS:
            continue
        for line in block.text.split("\n"):
            match_q = _Q_RE.match(line)
            match_a = _A_RE.match(line)
            if match_q:
                save()
                q = match_q.group(2)
                a = None
                positions = block.positions
            elif match_a and q is not None:
                a = match_a.group(2)
            elif a is not None:
                a += "\n" + line
            elif q is not None:
                q += "\n" + line
    save()
    return pairs


def _qa_heading_pairs(blocks: Sequence[Block]) -> list[_QaPair]:
    """Pary z nagłówków: heading = q, kolejne bloki nie-heading i nie-table = odpowiedź."""
    pairs: list[_QaPair] = []
    q: str | None = None
    path: tuple[str, ...] = ()
    answers: list[str] = []
    positions: list[Position] = []

    def save() -> None:
        if q is not None:
            joined = "\n".join(answers)
            if joined.strip():
                pairs.append((q, joined, tuple(dict.fromkeys(positions)), path))

    for block in blocks:
        if block.kind == "heading":
            save()
            q = block.text
            path = block.heading_path
            answers = []
            positions = []
        elif block.kind != "table" and q is not None:
            answers.append(block.text)
            positions.extend(block.positions)
    save()
    return pairs


# -- table (C10.4) --


def chunk_table_rows(blocks: Sequence[Block], cfg: ChunkConfig) -> list[ChunkDraft]:
    """Wiersze tabel jako osobne chunki wg ról kolumn; przebiegi tekstu jak naive (C10.4)."""
    roles: Mapping[str, str] = cfg.table_column_roles if cfg.table_column_mode == "manual" else {}
    drafts: list[ChunkDraft] = []
    run: list[Block] = []
    for block in blocks:
        if block.kind == "table":
            if run:
                drafts.extend(merge_small(chunk_general(run, preset_for("naive"), cfg), cfg))
                run = []
            drafts.extend(_row_drafts(block, roles, cfg))
        else:
            run.append(block)
    if run:
        drafts.extend(merge_small(chunk_general(run, preset_for("naive"), cfg), cfg))
    return finalize(drafts)


def _column_name(header: Sequence[str], index: int) -> str:
    """Nazwa kolumny jak w row_text (C7): header[i], a gdy pusty — column_<i+1>."""
    return header[index] if index < len(header) and header[index].strip() else f"column_{index + 1}"


def _row_text_and_metadata(
    header: Sequence[str], row: Sequence[str], roles: Mapping[str, str]
) -> tuple[str, dict[str, str]]:
    """Tekst z ról indexing|both, metadane z ról metadata|both; rola domyślna „both”."""
    texts: list[str] = []
    metadata: dict[str, str] = {}
    for index, value in enumerate(row):
        if not value.strip():
            continue
        name = _column_name(header, index)
        role = roles.get(name, "both")
        if role in ("indexing", "both"):
            texts.append(f"{name}: {value}")
        if role in ("metadata", "both"):
            metadata[name] = value
    return "; ".join(texts), metadata


def _row_drafts(block: Block, roles: Mapping[str, str], cfg: ChunkConfig) -> list[ChunkDraft]:
    """Drafty wierszy jednej tabeli; wiersz ponad max_tokens dzielony split_to_limit."""
    table = block.table
    if table is None:
        return []
    positions = tuple(dict.fromkeys(block.positions))
    drafts: list[ChunkDraft] = []
    for index, row in enumerate(table.rows):
        text, metadata = _row_text_and_metadata(table.header, row, roles)
        if not text:
            continue
        row_html = table.rows_html[index] if index < len(table.rows_html) else ""
        fragment_html = f"<table>{table.header_html}<tbody>{row_html}</tbody></table>"
        pieces = [text]
        if cfg.count_tokens(text) > cfg.max_tokens:
            pieces = split_to_limit(text, cfg.max_tokens, cfg.count_tokens)
        drafts.extend(
            _table_row_draft(piece, fragment_html, cfg, positions, metadata) for piece in pieces
        )
    return drafts


# -- strip_page_furniture (C10.5) --


def _furniture_key(text: str) -> str:
    """Klucz stopki: tekst znormalizowany, cyfry zastąpione przez „#”."""
    return _DIGITS_RE.sub("#", " ".join(text.lower().split()))


def _is_page_number(text: str) -> bool:
    return _PAGE_NO_RE.fullmatch(text) is not None


def strip_page_furniture(blocks: Sequence[Block]) -> list[Block]:
    """Usuwaj akapity-numery stron i krótkie akapity powtarzalne w ≥ 3 sekcjach page:* (C10.5)."""
    key_sections: dict[str, set[str]] = {}
    for block in blocks:
        if block.kind == "paragraph" and block.section:
            key_sections.setdefault(_furniture_key(block.text), set()).add(block.section)
    kept: list[Block] = []
    for block in blocks:
        if block.kind == "paragraph" and _is_page_number(block.text):
            continue
        if (
            block.kind == "paragraph"
            and block.section is not None
            and block.section.startswith("page:")
            and len(block.text.split()) <= _FURNITURE_WORD_LIMIT
            and len(key_sections.get(_furniture_key(block.text), ())) >= _FURNITURE_SECTIONS
        ):
            continue
        kept.append(block)
    return kept
