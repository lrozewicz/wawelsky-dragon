"""Testy unit serializacji wiersza importu chunków (T12, DEC-341) — bez bazy.

Kolumna ``chunks.tags`` jest JSON-em, w którym DDL-default to ``[]`` (lista), a RAGFlow-owe
``tag_feas`` bywa obiektem. ``_params`` musi zapisać OBA kształty wprost, bez rzutowania na
``dict``: ``dict([])`` dawało cichy ``{}`` (utrata listy z bazy), a ``dict(["umowa"])`` —
``ValueError`` w workerze importu (500 zamiast importu).
"""

from typing import Any

from app.db.repositories.chunks_import import ChunkImportRow, _params

TIME_MS = 1790157600000


def _row(tags: Any) -> ChunkImportRow:
    """Wiersz importu z zadanym ``tags`` (pozostałe pola wypisane 1:1 jak z paczki)."""
    return ChunkImportRow(
        id="a" * 32,
        document_id="b" * 32,
        dataset_id="c" * 32,
        ordinal=0,
        chunk_type="text",
        content="treść chunka",
        content_llm=None,
        content_ft="tresc chunka",
        content_stem="tresc chunk",
        title_ft="umowa",
        keywords=["umowa"],
        questions=[],
        important_ft="umowa",
        question_ft="",
        tags=tags,
        positions=None,
        page_from=None,
        page_to=None,
        image_id=None,
        parent_id=None,
        available=True,
        token_count=5,
        embed_source="content",
    )


def test_params_serializes_list_tags_as_json_list() -> None:
    """``tags`` lista (DDL-default ``[]`` i lista z ingestii) → JSON-lista, nie ``{}`` (DEC-341)."""
    assert _params(_row([]), now_ms=TIME_MS)["tags"] == "[]"
    assert _params(_row(["umowa"]), now_ms=TIME_MS)["tags"] == '["umowa"]'


def test_params_serializes_object_tags_as_json_object() -> None:
    """``tags`` obiekt (tag_feas RAGFlow) nadal → JSON-obiekt bez zmiany (DEC-341)."""
    assert _params(_row({"autor": "Jan"}), now_ms=TIME_MS)["tags"] == '{"autor": "Jan"}'
