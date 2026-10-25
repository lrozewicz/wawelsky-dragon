"""Typy chunkera (K5 §5.1, 05 §10)."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

BlockKind = Literal["heading", "paragraph", "list", "table", "code", "figure", "notes"]
ChunkType = Literal["text", "table", "list", "code", "image", "qa"]
PresetMode = Literal["general", "presentation", "one", "qa", "table"]
Position = tuple[int, int, int, int, int]


@dataclass(frozen=True)
class TableData:
    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    header_html: str
    rows_html: tuple[str, ...]


@dataclass(frozen=True)
class Block:
    kind: BlockKind
    text: str
    html: str
    level: int | None
    heading_path: tuple[str, ...]
    positions: tuple[Position, ...]
    section: str | None
    table: TableData | None


@dataclass(frozen=True)
class ChunkConfig:
    count_tokens: Callable[[str], int]
    chunk_token_num: int = 512
    delimiter: str = "\n"
    overlapped_percent: int = 0
    html4excel: bool = False
    max_tokens: int = 8000
    table_column_mode: Literal["auto", "manual"] = "auto"
    table_column_roles: Mapping[str, Literal["indexing", "metadata", "both"]] = field(
        default_factory=dict
    )


@dataclass(frozen=True)
class ChunkPreset:
    name: str
    split_on_headings: tuple[int, ...] = ()
    mode: PresetMode = "general"
    boundary_patterns: tuple[str, ...] = ()
    strip_page_furniture: bool = False


@dataclass(frozen=True)
class ChunkDraft:
    ordinal: int
    text: str
    html: str
    chunk_type: ChunkType
    heading_path: tuple[str, ...]
    positions: tuple[Position, ...]
    page_from: int | None
    page_to: int | None
    tokens: int
    questions: tuple[str, ...]
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class DelimiterSpec:
    # jak upstream parse_delimiter_field: dedup, najdłuższe pierwsze (sort stabilny)
    delimiters: tuple[str, ...]
    # jak upstream has_wrapped_delimiter: pole zawiera token w backtickach
    has_wrapped: bool
