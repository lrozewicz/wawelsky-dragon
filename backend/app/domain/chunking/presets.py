"""Presety chunkingu (CONTRACT WP E1-5 C4)."""

from app.domain.chunking.errors import UnsupportedChunkMethod
from app.domain.chunking.types import ChunkPreset

LAWS_PATTERNS: tuple[str, ...] = (
    r"(?i)^\s*art\.\s*\d+",
    r"^\s*§\s*\d+",
    r"(?i)^\s*rozdział\b",
    r"(?i)^\s*article\s+\d+",
    r"(?i)^\s*section\s+\d+",
)
PAPER_PATTERNS: tuple[str, ...] = (
    r"(?i)^\s*(\d+(\.\d+)*\.?\s+)?(abstract|introduction|related work|background|methods?"
    r"|methodology|experiments?"
    r"|results|discussion|conclusions?|references|acknowledg(e)?ments|streszczenie|wstęp|wprowadzenie"
    r"|metody|wyniki"
    r"|dyskusja|wnioski|bibliografia)\s*$",
)
ALL_LEVELS = (1, 2, 3, 4, 5, 6)
UNSUPPORTED = frozenset({"tag", "knowledge_graph", "resume", "audio"})

_PRESETS: dict[str, ChunkPreset] = {
    "naive": ChunkPreset(name="naive", split_on_headings=ALL_LEVELS),
    "email": ChunkPreset(name="email", split_on_headings=ALL_LEVELS),
    "manual": ChunkPreset(name="manual", split_on_headings=(1, 2, 3)),
    "book": ChunkPreset(name="book", split_on_headings=(1, 2)),
    "laws": ChunkPreset(name="laws", split_on_headings=ALL_LEVELS, boundary_patterns=LAWS_PATTERNS),
    "paper": ChunkPreset(
        name="paper",
        split_on_headings=ALL_LEVELS,
        boundary_patterns=PAPER_PATTERNS,
        strip_page_furniture=True,
    ),
    "presentation": ChunkPreset(name="presentation", mode="presentation"),
    "one": ChunkPreset(name="one", mode="one"),
    "picture": ChunkPreset(name="picture", mode="one"),
    "qa": ChunkPreset(name="qa", mode="qa"),
    "table": ChunkPreset(name="table", mode="table"),
}


def preset_for(chunk_method: str) -> ChunkPreset:
    """Preset dla chunk_method; wartość spoza tabeli C4 → UnsupportedChunkMethod (code 101)."""
    if chunk_method not in _PRESETS:
        raise UnsupportedChunkMethod(chunk_method)
    return _PRESETS[chunk_method]
