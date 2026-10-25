"""Testy present/chunks i present/references w profilu 0.24.0 (brief E2-2a T2, CONTRACT C0 p. 1-2).

Profil 0.24 zwraca zbiory kluczy złota ``v0.24.0``: element listy bez ``doc_type_kwd``
i ``tag_kwd`` (chunks_list--06, chunks_extras--19), odpowiedź POST bez ``doc_type_kwd``
(chunks_extras--06), chunk retrievalu bez ``row_id`` i ``tag_kwd`` (retrieval--06).
``present/references.py`` jest testowany tutaj, bo brief T2 dopuszcza tylko te dwa nowe pliki
testów jednostkowych. Profil 0.27 porównany tym samym testem ze złotem ``v0.27.2``.
"""

import json
from pathlib import Path
from typing import Any

from app.api.ragflow.present.chunks import chunk_created, chunk_item, chunk_page
from app.api.ragflow.present.documents import document_full
from app.api.ragflow.present.references import chunk_retrieval
from app.core.timeutil import from_ms
from app.domain.retrieval.types import RetrievedChunk
from app.services.chunks import ChunkPage, ChunkRecord
from app.services.documents import DocumentRow

PROFILE_V024 = "ragflow_0_24"
PROFILE_V027 = "ragflow_0_27"
NOW_MS = 1790157600000  # → "2026-09-23 10:00:00" UTC (date())

GOLDEN_V024 = Path(__file__).resolve().parents[3] / "contract" / "golden" / "v0.24.0"
GOLDEN_V027 = Path(__file__).resolve().parents[3] / "contract" / "golden" / "v0.27.2"

ITEM_V024_KEYS = 10  # złoto chunks_list--06 → body.data.chunks[0]
CREATED_V024_KEYS = 8  # złoto chunks_extras--06 → body.data.chunk
CREATED_V027_KEYS = 9  # złoto v0.27.2 chunks_extras--06 → body.data.chunk
RETRIEVAL_V024_KEYS = 14  # złoto retrieval--06 → body.data.chunks[0]


def _chunk(**overrides: Any) -> ChunkRecord:
    """Pełny ChunkRecord do testów prezentertów (pola wg kontraktu C3.1)."""
    values: dict[str, Any] = dict(
        id="c" * 16,
        document_id="d" * 32,
        dataset_id="s" * 32,
        document_name="ragflow_intro.txt",
        ordinal=0,
        chunk_type="text",
        content="Ala ma kota",
        keywords=["kot"],
        questions=[],
        tags=["zwierzęta"],
        positions=[],
        image_id=None,
        available=True,
        token_count=3,
        create_time=NOW_MS,
        update_time=NOW_MS,
    )
    values.update(overrides)
    return ChunkRecord(**values)


def _doc(**overrides: Any) -> DocumentRow:
    """Dokument do ChunkPage (wzór: test_present_documents_v024._row)."""
    values: dict[str, Any] = dict(
        id="d" * 32,
        dataset_id="s" * 32,
        created_by="u" * 32,
        name="ragflow_intro.txt",
        suffix="txt",
        type="doc",
        size=1319,
        location="datasets/s/documents/d/ragflow_intro.txt",
        content_hash="c" * 32,
        source_type="local",
        source_ref=None,
        chunk_method="naive",
        parser_config={"chunk_token_num": 512},
        run="0",
        progress=0.0,
        progress_msg="",
        error=None,
        process_begin_at=None,
        process_duration=0.0,
        chunk_count=0,
        token_count=0,
        enabled=True,
        meta_fields={},
        thumbnail=None,
        create_time=NOW_MS,
        create_date=from_ms(NOW_MS),
        update_time=NOW_MS,
        update_date=from_ms(NOW_MS),
    )
    values.update(overrides)
    return DocumentRow(**values)


def _retrieved(**overrides: Any) -> RetrievedChunk:
    """Pełny RetrievedChunk do testów prezentertów (pola wg kontraktu M1)."""
    values: dict[str, Any] = dict(
        chunk_id="c" * 32,
        content="Treść fragmentu.",
        content_llm="Treść fragmentu.",
        content_terms="tre ś ć fragmentu",
        document_id="d" * 32,
        document_name="ragflow_intro.txt",
        dataset_id="s" * 32,
        image_id="",
        important_keywords=["smok"],
        questions=["Co wie o smoku?"],
        tag_kwd=["zwierzęta"],
        positions=[[2, 1, 1, 1, 1]],
        similarity=0.75,
        vector_similarity=0.8,
        term_similarity=0.7,
        highlight=None,
        doc_type="",
        url=None,
        document_metadata=None,
    )
    values.update(overrides)
    return RetrievedChunk(**values)


def _golden(version: Path, name: str, path: list[Any]) -> dict[str, Any]:
    """Węzeł body pliku złota po przejściu po ``path`` (np. ["data", "chunks", 0])."""
    node: Any = json.loads((version / name).read_text(encoding="utf-8"))["body"]
    for part in path:
        node = node[part]
    return node


def test_chunk_item_keys_match_golden_v024() -> None:
    """Lista w 0.24: dokładnie 10 kluczy złota --06 (bez doc_type_kwd/tag_kwd, wym. 2)."""
    golden = _golden(
        GOLDEN_V024, "datasets___documents___chunks/chunks_list--06.json", ["data", "chunks", 0]
    )
    data = chunk_item(_chunk(), PROFILE_V024)
    assert sorted(data.keys()) == sorted(golden.keys())
    assert len(golden) == ITEM_V024_KEYS
    assert "doc_type_kwd" not in data
    assert "tag_kwd" not in data


def test_chunk_item_v027_unchanged() -> None:
    """Lista w 0.27: bez zmian — 12 kluczy złota v0.27.2 (z doc_type_kwd/tag_kwd)."""
    golden = _golden(
        GOLDEN_V027, "datasets___documents___chunks/chunks_list--06.json", ["data", "chunks", 0]
    )
    data = chunk_item(_chunk(), PROFILE_V027)
    assert sorted(data.keys()) == sorted(golden.keys())
    assert data["doc_type_kwd"] == "text"
    assert data["tag_kwd"] == ["zwierzęta"]


def test_chunk_page_doc_v024() -> None:
    """data.doc strony w 0.24: document_full profilu 0.24 (25 kluczy, złoto --06)."""
    golden = _golden(
        GOLDEN_V024, "datasets___documents___chunks/chunks_list--06.json", ["data", "doc"]
    )
    data = chunk_page(ChunkPage(chunks=[_chunk()], total=1, doc=_doc()), PROFILE_V024)
    assert data["doc"] == document_full(_doc(), PROFILE_V024)
    assert sorted(data["doc"].keys()) == sorted(golden.keys())
    assert data["doc"]["parser_config"]["raptor"]["use_raptor"] is True


def test_chunk_created_keys_match_golden_v024() -> None:
    """POST chunku w 0.24: 8 kluczy złota --06 (bez doc_type_kwd, nigdy tag_kwd)."""
    for with_tags in (False, True):
        chunk = chunk_created(_chunk(), PROFILE_V024, with_tags=with_tags)["chunk"]
        assert len(chunk) == CREATED_V024_KEYS
        assert "doc_type_kwd" not in chunk
        assert "tag_kwd" not in chunk
    golden = _golden(
        GOLDEN_V024, "datasets___documents___chunks/chunks_extras--06.json", ["data", "chunk"]
    )
    chunk = chunk_created(_chunk(), PROFILE_V024, with_tags=False)["chunk"]
    assert sorted(chunk.keys()) == sorted(golden.keys())
    assert chunk["create_time"] == "2026-09-23 10:00:00"
    assert chunk["create_timestamp"] == NOW_MS / 1000


def test_chunk_created_v027_unchanged() -> None:
    """POST chunku w 0.27: bez zmian — 9 kluczy (z doc_type_kwd), tag_kwd na żądanie."""
    without = chunk_created(_chunk(), PROFILE_V027, with_tags=False)["chunk"]
    with_tags = chunk_created(_chunk(), PROFILE_V027, with_tags=True)["chunk"]
    assert len(without) == CREATED_V027_KEYS
    assert without["doc_type_kwd"] == "text"
    assert "tag_kwd" not in without
    assert with_tags["tag_kwd"] == ["zwierzęta"]


def test_chunk_retrieval_keys_match_golden_v024() -> None:
    """Retrieval w 0.24: 14 kluczy złota --06 (bez row_id/tag_kwd, wym. 2)."""
    golden = _golden(GOLDEN_V024, "retrieval/retrieval--06.json", ["data", "chunks", 0])
    data = chunk_retrieval(_retrieved(), PROFILE_V024)
    assert sorted(data.keys()) == sorted(golden.keys())
    assert len(golden) == RETRIEVAL_V024_KEYS
    assert "row_id" not in data
    assert "tag_kwd" not in data
    assert data["doc_type_kwd"] == ""


def test_chunk_retrieval_v027_unchanged() -> None:
    """Retrieval w 0.27: bez zmian — 16 kluczy złota v0.27.2 (z row_id/tag_kwd)."""
    golden = _golden(GOLDEN_V027, "retrieval/retrieval--06.json", ["data", "chunks", 0])
    data = chunk_retrieval(_retrieved(), PROFILE_V027)
    assert sorted(data.keys()) == sorted(golden.keys())
    assert data["row_id"] is None
    assert data["tag_kwd"] == ["zwierzęta"]
