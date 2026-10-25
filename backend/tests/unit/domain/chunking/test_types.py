"""Testy typów chunkingu (CONTRACT WP E1-5 C2) i eksportu pakietu (C9)."""

import dataclasses

import pytest

from app.domain import chunking
from app.domain.chunking.types import Block, ChunkConfig, ChunkDraft, ChunkPreset, TableData

# Domyślne wartości pól ChunkConfig — nazwane stałe zamiast liczb magicznych (PLR2004).
DEFAULT_CHUNK_TOKEN_NUM = 512
DEFAULT_MAX_TOKENS = 8000

_EXPORTS_C9 = {
    "Block",
    "BlockKind",
    "ChunkConfig",
    "ChunkDraft",
    "ChunkPreset",
    "ChunkType",
    "DelimiterSpec",
    "TableData",
    "UnsupportedChunkMethod",
    "DocumentTooLarge",
    "chunk_blocks",
    "parse_delimiter_field",
    "preset_for",
}


def _identity(text: str) -> int:
    return len(text)


def _config() -> ChunkConfig:
    return ChunkConfig(count_tokens=_identity)


def _preset() -> ChunkPreset:
    return ChunkPreset(name="naive")


def _table() -> TableData:
    return TableData(header=("A",), rows=(("x",),), header_html="<thead></thead>", rows_html=())


def _block() -> Block:
    return Block(
        kind="paragraph",
        text="tekst",
        html="<p>tekst</p>",
        level=None,
        heading_path=(),
        positions=(),
        section=None,
        table=None,
    )


def _draft() -> ChunkDraft:
    return ChunkDraft(
        ordinal=0,
        text="t",
        html="<p>t</p>",
        chunk_type="text",
        heading_path=(),
        positions=(),
        page_from=None,
        page_to=None,
        tokens=0,
        questions=(),
        metadata={},
    )


def test_chunk_config_defaults():
    """ChunkConfig ma dokładnie domyślne wartości z C2."""
    cfg = ChunkConfig(count_tokens=_identity)
    assert cfg.count_tokens is _identity
    assert cfg.chunk_token_num == DEFAULT_CHUNK_TOKEN_NUM
    assert cfg.delimiter == "\n"
    assert cfg.overlapped_percent == 0
    assert cfg.html4excel is False
    assert cfg.max_tokens == DEFAULT_MAX_TOKENS
    assert cfg.table_column_mode == "auto"
    assert cfg.table_column_roles == {}


@pytest.mark.parametrize(
    ("factory", "field_name"),
    [
        (_config, "chunk_token_num"),
        (_preset, "name"),
        (_table, "header"),
        (_block, "text"),
        (_draft, "text"),
    ],
)
def test_dataclasses_are_frozen(factory, field_name):
    """Wszystkie typy z C2 są frozen: przypisanie pola → FrozenInstanceError."""
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(factory(), field_name, "zmienione")


def test_public_exports_c9():
    """Eksport pakietu = lista C9 (bez chunk_blocks — dopisze T3); nazwy są dostępne."""
    assert set(chunking.__all__) == _EXPORTS_C9
    for name in chunking.__all__:
        assert getattr(chunking, name) is not None
