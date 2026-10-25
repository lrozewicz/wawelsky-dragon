"""Testy present/chunks: zbiory kluczy i wartości wg złota v0.27.2 (kontrakt E1-9a C3.4)."""

import json
from pathlib import Path
from typing import Any

from app.api.ragflow.present.chunks import chunk_created, chunk_item, chunk_page, chunk_source
from app.api.ragflow.present.documents import document_full
from app.core.timeutil import from_ms
from app.services.chunks import ChunkPage, ChunkRecord
from app.services.documents import DocumentRow

PROFILE = "ragflow_0_27"
NOW_MS = 1790157600000  # → "2026-09-23 10:00:00" UTC (date())
ITEM_KEYS = 12  # klucze elementu listy (złoto chunks_list--06)
FULL_KEYS = 26  # klucze data.doc (document_full)
CREATED_KEYS = 9  # klucze data.chunk po POST bez tag_kwd w żądaniu (złoto chunks_extras--06)
SOURCE_KEYS = 10  # klucze data GET …/chunks/{id} (złoto chunks_extras--08)

GOLDEN = Path(__file__).resolve().parents[3] / "contract" / "golden" / "v0.27.2"


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
    """Dokument do ChunkPage (wzór: test_present_documents._row)."""
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


def _golden(name: str, path: list[Any]) -> Any:
    """Węzeł body pliku złota po przejściu po ``path`` (np. ["data", "chunks", 0])."""
    node: Any = json.loads((GOLDEN / name).read_text(encoding="utf-8"))["body"]
    for part in path:
        node = node[part]
    return node


def test_chunk_item_keys_match_golden() -> None:
    """chunk_item() ma dokładnie zbiór kluczy data.chunks[0] złota listy (--06, wym. 1)."""
    golden = _golden("datasets___documents___chunks/chunks_list--06.json", ["data", "chunks", 0])
    assert sorted(chunk_item(_chunk(), PROFILE).keys()) == sorted(golden.keys())
    assert len(golden) == ITEM_KEYS


def test_chunk_item_values() -> None:
    """Mapowania C3.4: docnm_kwd ← document_name, image_id "", keywords→important_keywords."""
    data = chunk_item(_chunk(), PROFILE)
    assert data["doc_type_kwd"] == "text"
    assert data["docnm_kwd"] == "ragflow_intro.txt"
    assert data["image_id"] == ""
    assert data["important_keywords"] == ["kot"]
    assert data["tag_kwd"] == ["zwierzęta"]
    assert data["positions"] == []
    assert data["questions"] == []
    assert data["available"] is True
    assert data["content"] == "Ala ma kota"
    assert data["id"] == "c" * 16
    assert data["document_id"] == "d" * 32
    assert data["dataset_id"] == "s" * 32


def test_chunk_item_doc_type_table_and_image() -> None:
    """chunk_type table/image przechodzi dosłownie, pozostałe → "text" (wym. 2)."""
    assert chunk_item(_chunk(chunk_type="table"), PROFILE)["doc_type_kwd"] == "table"
    assert chunk_item(_chunk(chunk_type="image"), PROFILE)["doc_type_kwd"] == "image"
    assert chunk_item(_chunk(chunk_type="naive"), PROFILE)["doc_type_kwd"] == "text"


def test_chunk_page_shape() -> None:
    """chunk_page: klucze chunks/doc/total; doc = document_full (26 kluczy, wym. 1)."""
    page = ChunkPage(chunks=[_chunk()], total=1, doc=_doc())
    data = chunk_page(page, PROFILE)
    assert sorted(data.keys()) == ["chunks", "doc", "total"]
    assert data["total"] == 1
    assert data["doc"] == document_full(_doc(), PROFILE)
    assert len(data["doc"]) == FULL_KEYS
    golden_doc = _golden("datasets___documents___chunks/chunks_list--06.json", ["data", "doc"])
    assert sorted(data["doc"].keys()) == sorted(golden_doc.keys())


def test_chunk_created_shape() -> None:
    """chunk_created: 9 kluczy bez tag_kwd; create_time date, timestamp float (CHK:1158)."""
    chunk = chunk_created(_chunk(), PROFILE, with_tags=False)["chunk"]
    assert sorted(chunk.keys()) == sorted(
        [
            "id",
            "content",
            "document_id",
            "dataset_id",
            "important_keywords",
            "questions",
            "create_time",
            "create_timestamp",
            "doc_type_kwd",
        ]
    )
    assert len(chunk) == CREATED_KEYS
    assert chunk["create_time"] == "2026-09-23 10:00:00"
    assert chunk["create_timestamp"] == NOW_MS / 1000
    assert isinstance(chunk["create_timestamp"], float)
    assert chunk["doc_type_kwd"] == "text"
    assert chunk["important_keywords"] == ["kot"]


def test_chunk_created_with_tags() -> None:
    """chunk_created z tag_kwd w żądaniu: 10 kluczy, tag_kwd = tags (CHK:1158-1174)."""
    chunk = chunk_created(_chunk(), PROFILE, with_tags=True)["chunk"]
    assert len(chunk) == CREATED_KEYS + 1
    assert chunk["tag_kwd"] == ["zwierzęta"]


def test_chunk_source_keys_match_golden() -> None:
    """chunk_source() ma dokładnie zbiór kluczy data złota GET chunka (--08, wym. 1).

    Chunek złota --08 nie ma tagów, więc ``tag_kwd`` nie występuje (klucz magazynu).
    """
    golden = _golden("datasets___documents___chunks___/chunks_extras--08.json", ["data"])
    assert sorted(chunk_source(_chunk(tags=[]), PROFILE).keys()) == sorted(golden.keys())
    assert len(golden) == SOURCE_KEYS


def test_chunk_source_tag_kwd_only_with_tags() -> None:
    """chunk_source() wystawia ``tag_kwd``, gdy chunk ma tagi (upstream CHK:639-656, FIXA p. 2)."""
    data = chunk_source(_chunk(tags=["zwierzęta", "smok"]), PROFILE)
    assert len(data) == SOURCE_KEYS + 1
    assert data["tag_kwd"] == ["zwierzęta", "smok"]


def test_chunk_source_values() -> None:
    """Mapowania surowego dokumentu: content_with_weight ← content, kb_id ← dataset_id (CHK:586)."""
    data = chunk_source(_chunk(), PROFILE)
    assert data["content_with_weight"] == "Ala ma kota"
    assert data["create_time"] == "2026-09-23 10:00:00"
    assert data["create_timestamp_flt"] == NOW_MS / 1000
    assert data["doc_id"] == "d" * 32
    assert data["doc_type_kwd"] == "text"
    assert data["docnm_kwd"] == "ragflow_intro.txt"
    assert data["id"] == "c" * 16
    assert data["important_kwd"] == ["kot"]
    assert data["kb_id"] == "s" * 32
    assert data["question_kwd"] == []
