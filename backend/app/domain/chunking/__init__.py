"""Chunking — czysta domena podziału dokumentów (eksport publiczny wg CONTRACT WP E1-5 C9).

T1: wszystko poza ``chunk_blocks`` (ten eksport dopisze T3).
"""

from app.domain.chunking.chunker import chunk_blocks
from app.domain.chunking.delimiter import parse_delimiter_field
from app.domain.chunking.errors import DocumentTooLarge, UnsupportedChunkMethod
from app.domain.chunking.presets import preset_for
from app.domain.chunking.types import (
    Block,
    BlockKind,
    ChunkConfig,
    ChunkDraft,
    ChunkPreset,
    ChunkType,
    DelimiterSpec,
    TableData,
)

__all__ = [
    "Block",
    "BlockKind",
    "ChunkConfig",
    "ChunkDraft",
    "ChunkPreset",
    "ChunkType",
    "DelimiterSpec",
    "DocumentTooLarge",
    "TableData",
    "UnsupportedChunkMethod",
    "chunk_blocks",
    "parse_delimiter_field",
    "preset_for",
]
