"""Typy domeny retrievalu (CONTRACT WP E1-7 M1, 06 §4)."""

from dataclasses import dataclass
from typing import Any, Literal

FusionMode = Literal["weighted", "rrf"]


@dataclass(frozen=True)
class QueryTerms:
    """Tokeny zapytania i łańcuchy FULLTEXT.

    raw_terms: tokeny pytania (NFC, lower, sekwencje znaków słownych, bez stopwords,
    dedup z zachowaniem kolejności); terms: unigramy po stemie jako (term, 0.4 * waga),
    dedup; bigrams: sąsiedne pary termów jako (f"{a} {b}", 0.6 * max(waga(a), waga(b)));
    ft_raw: " ".join(raw_terms), łańcuch AGAINST dla content_ft/title_ft/important_ft/
    question_ft; ft_stem: " ".join(term dla terms), łańcuch AGAINST dla content_stem.
    """

    raw_terms: tuple[str, ...]
    terms: tuple[tuple[str, float], ...]
    bigrams: tuple[tuple[str, float], ...]
    ft_raw: str
    ft_stem: str


ChunkTerms = frozenset[str]  # unigramy i bigramy ("a b") tokenów chunku


@dataclass(frozen=True)
class Candidate:
    """Kandydat przed scoringiem."""

    chunk_id: str
    document_id: str
    document_name: str
    ordinal: int  # chunks.ordinal — pozycja chunku w dokumencie (klucz wtórny remisów, C3)
    vector_similarity: float  # 1 - dist cosinusowy; 0.0 gdy brak strony wektorowej
    term_similarity: float
    rerank_score: float | None = None  # None = bez modelu rerank


@dataclass(frozen=True)
class Scored:
    """Kandydat po fuzji."""

    candidate: Candidate
    similarity: float


@dataclass(frozen=True)
class ThresholdConfig:
    """Progi odrzucania kandydatów."""

    min_vector_sim: float  # WD_MIN_VECTOR_SIM
    min_rerank_score: float  # WD_MIN_RERANK_SCORE


@dataclass(frozen=True)
class DocAgg:
    """Agregacja trafień per dokument."""

    doc_name: str
    doc_id: str
    count: int


@dataclass(frozen=True)
class RetrievedChunk:
    """Fragment zwracany przez API (06 §4 dosłownie)."""

    chunk_id: str
    content: str
    content_llm: str
    content_terms: str
    document_id: str
    document_name: str
    dataset_id: str
    image_id: str
    important_keywords: list[str]
    questions: list[str]
    tag_kwd: list[str]
    positions: list[list[int]]
    similarity: float
    vector_similarity: float
    term_similarity: float
    highlight: str | None
    doc_type: str
    url: str | None
    document_metadata: dict[str, Any] | None


@dataclass(frozen=True)
class RetrievalResult:
    """Wynik retrievalu; pusty: total=0, chunks=[], doc_aggs=[]."""

    total: int
    chunks: list[RetrievedChunk]
    doc_aggs: list[DocAgg]
    query_vector: list[float] | None = None
