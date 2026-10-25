"""Testy unit czystych funkcji repozytoriów chunków (brief T3a, DEC-021) — bez bazy."""

import pytest

from app.db.repositories.chunk_vectors import _upsert_sql
from app.db.repositories.chunks import ChunkRecord, _json_list, _record, update_content

TIME_CREATE = 1790157600000
TIME_UPDATE = 1790157600001


def _chunk_row() -> dict:
    """Wiersz jak z SELECT list_for_document: JSON jako str, positions NULL (C3.1)."""
    return {
        "id": "a" * 16,
        "document_id": "b" * 32,
        "dataset_id": "c" * 32,
        "document_name": "umowa.txt",
        "ordinal": 2,
        "chunk_type": "text",
        "content": "treść",
        "keywords": '["a", "b"]',
        "questions": "[]",
        "tags": '["t"]',
        "positions": None,
        "image_id": None,
        "available": 1,
        "token_count": 5,
        "create_time": TIME_CREATE,
        "update_time": TIME_UPDATE,
    }


def test_json_list_parses_str_and_passes_through_list() -> None:
    """JSON jako str → lista; już sparsowana lista wraca ten sam obiekt (wzór documents)."""
    assert _json_list('["a"]') == ["a"]
    parsed = ["a"]
    assert _json_list(parsed) is parsed


def test_record_maps_row_with_null_positions() -> None:
    """_record: JSON str → listy, NULL positions → [], TINYINT → bool, czasy → int (C3.1)."""
    record = _record(_chunk_row())  # type: ignore[arg-type]
    assert isinstance(record, ChunkRecord)
    assert record.id == "a" * 16
    assert record.document_name == "umowa.txt"
    assert record.keywords == ["a", "b"]
    assert record.questions == []
    assert record.tags == ["t"]
    assert record.positions == []
    assert record.available is True
    assert record.image_id is None
    assert (record.create_time, record.update_time) == (TIME_CREATE, TIME_UPDATE)


def test_record_positions_from_json_str_and_copy_of_lists() -> None:
    """_record: positions z JSON str → lista list; z listy → NOWE listy wewnętrzne (C3.1)."""
    from_json = _record(_chunk_row() | {"positions": "[[1, 2], [3, 4]]"})  # type: ignore[arg-type]
    assert from_json.positions == [[1, 2], [3, 4]]
    row = _chunk_row() | {"positions": [[5, 6]]}
    record = _record(row)  # type: ignore[arg-type]
    assert record.positions == [[5, 6]]
    assert record.positions[0] is not row["positions"][0]


def test_upsert_sql_uses_table_name_and_on_duplicate() -> None:
    """_upsert_sql: tabela z table_name(dim), VEC_FromText, ON DUPLICATE KEY UPDATE (C3.1)."""
    sql = _upsert_sql(1024)
    assert "INSERT INTO chunk_vec_d1024" in sql
    assert "VEC_FromText(:v)" in sql
    assert "ON DUPLICATE KEY UPDATE embedding = VALUES(embedding)" in sql


def test_upsert_sql_rejects_invalid_dimension() -> None:
    """_upsert_sql: nieprawidłowy wymiar → ValueError (walidacja w table_name)."""
    with pytest.raises(ValueError, match="invalid embedding dimension"):
        _upsert_sql(0)


async def test_update_content_rejects_column_before_session_use() -> None:
    """update_content: kolumna spoza białej listy → ValueError zanim sesja jest dotykana (C3.1)."""
    with pytest.raises(ValueError, match="column not allowed: ordinal"):
        await update_content(None, "a" * 16, {"ordinal": 1}, now_ms=0)  # type: ignore[arg-type]
