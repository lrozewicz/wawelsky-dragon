"""Mapowanie Scored + ChunkRow → RetrievedChunk (dług E2-1 D1): puste metadane → None.

Złoto upstream (rag/prompts/generator.py `chunks_format`, l. 62) emituje
``document_metadata: null`` dla dokumentu bez metadanych; WD brało ``{}`` z
``documents.meta_fields``.
"""

from app.db.repositories.retrieval import ChunkRow
from app.domain.retrieval.types import Candidate, QueryTerms, Scored
from app.services.retrieval import _to_chunk

_QT = QueryTerms(raw_terms=(), terms=(), bigrams=(), ft_raw="", ft_stem="")


def _row(**overrides: object) -> ChunkRow:
    """Wiersz chunku z domyślnym dokumentem bez metadanych."""
    params: dict = {
        "id": "c1",
        "document_id": "d1",
        "dataset_id": "ds1",
        "ordinal": 0,
        "document_name": "a.txt",
        "document_meta": {},
        "content": "Umowa najmu",
        "content_llm": None,
        "content_stem": "umowa najmu",
        "title_ft": "",
        "important_ft": "",
        "question_ft": "",
        "keywords": [],
        "questions": [],
        "positions": [],
        "chunk_type": "text",
    }
    params.update(overrides)
    return ChunkRow(**params)


def _scored() -> Scored:
    """Kandydat po fuzji dla wiersza z ``_row``."""
    return Scored(
        candidate=Candidate(
            chunk_id="c1",
            document_id="d1",
            document_name="a.txt",
            ordinal=0,
            vector_similarity=0.5,
            term_similarity=0.5,
        ),
        similarity=0.5,
    )


def test_document_metadata_empty_becomes_none() -> None:
    """Wejście: document_meta={} (dokument bez metadanych) → wyjście: document_metadata None."""
    assert _to_chunk(_scored(), _row(), _QT, False).document_metadata is None


def test_document_metadata_kept_when_present() -> None:
    """Wejście: document_meta={"author": "Jan"} → wyjście: metadane bez zmian."""
    chunk = _to_chunk(_scored(), _row(document_meta={"author": "Jan"}), _QT, False)
    assert chunk.document_metadata == {"author": "Jan"}
