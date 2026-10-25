"""Testy jednostkowe ``POST /api/v1/sessions/ask`` (CONTRACT E2-2b C0 p. 6, C4; brief T6a p. 4).

Koder ramek ask — bajtowo (klucze, kolejność, brak ``row_id``/``document_metadata``)
i walidacja ciała z komunikatami upstream (``ask_about``, kody 102 obsługuje trasa).
"""

import json
from collections.abc import AsyncIterator

from app.api.ragflow.routes.legacy_v024 import _ask_args
from app.api.ragflow.sse import TERMINATOR, ask_frames, sse_ask
from app.domain.chat.events import AnswerDelta, ChatEvent, ErrorEvent, Final

# Chunki referencji przychodzą z ``build_reference`` (14 kluczy); ask emituje 12 (C0 p. 6).
CHUNK: dict[str, object] = {
    "id": "k1",
    "content": "Wawelski",
    "document_id": "doc1",
    "document_name": "wawel.txt",
    "dataset_id": "ds1",
    "image_id": "",
    "positions": [[2, 1, 1, 1, 1]],
    "url": None,
    "similarity": 0.5,
    "vector_similarity": 0.4,
    "term_similarity": 0.6,
    "row_id": None,
    "doc_type": "",
    "document_metadata": None,
}
CHUNK_V024: dict[str, object] = {
    key: value for key, value in CHUNK.items() if key not in {"row_id", "document_metadata"}
}
REFERENCE: dict[str, object] = {
    "total": 1,
    "chunks": [CHUNK],
    "doc_aggs": [{"doc_name": "wawel.txt", "doc_id": "doc1", "count": 1}],
}


def _frame(obj: object) -> bytes:
    """Ramka SSE jak ``encode_frame`` — niezależne od kodera odtworzenie złota."""
    body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return b"data:" + body + b"\n\n"


def _final() -> Final:
    return Final(
        answer="",
        reference=REFERENCE,
        prompt="",
        created_at=None,
        final_answer="",
        thinking=None,
        usage=(0, 0),
        empty=False,
    )


async def _gen(events: tuple[ChatEvent, ...]) -> AsyncIterator[ChatEvent]:
    for event in events:
        yield event


def test_ask_delta_frame_bytes() -> None:
    """Delta: koperta z ``message:""``, ``reference:{}`` i ``final:false``, bez ids."""
    expected = _frame(
        {"code": 0, "message": "", "data": {"answer": "smok", "reference": {}, "final": False}}
    )
    assert ask_frames(AnswerDelta("smok")) == [expected]


def test_ask_final_frame_bytes_drops_chunk_extras() -> None:
    """Finalna: ``answer=""``, ``reference`` bez ``row_id``/``document_metadata`` (C0 p. 6)."""
    expected = _frame(
        {
            "code": 0,
            "message": "",
            "data": {
                "answer": "",
                "reference": {
                    "total": 1,
                    "chunks": [CHUNK_V024],
                    "doc_aggs": [{"doc_name": "wawel.txt", "doc_id": "doc1", "count": 1}],
                },
                "final": True,
            },
        }
    )
    assert ask_frames(_final()) == [expected]


def test_ask_error_frame_bytes() -> None:
    """Błąd strumienia: koperta ``code 500`` + ``**ERROR**`` (upstream ask_about)."""
    expected = _frame(
        {
            "code": 500,
            "message": "boom",
            "data": {"answer": "**ERROR**: boom", "reference": []},
        }
    )
    assert ask_frames(ErrorEvent("boom")) == [expected]


async def test_sse_ask_frames_then_terminator() -> None:
    """Strumień: ramki zdarzeń i terminator v0.27 (``message:""``) na końcu."""
    frames = [frame async for frame in sse_ask(_gen((AnswerDelta("a"), _final())))]
    assert frames[-1] == TERMINATOR
    assert frames[-2] == ask_frames(_final())[0]
    assert frames[0] == ask_frames(AnswerDelta("a"))[0]


def test_ask_args_question_required() -> None:
    """Brak/puste ``question`` → komunikat upstream (``ask_about``)."""
    assert _ask_args({}) == "`question` is required."
    assert _ask_args({"question": ""}) == "`question` is required."


def test_ask_args_dataset_ids_required() -> None:
    """Brak/pusta lista ``dataset_ids`` → komunikat upstream."""
    assert _ask_args({"question": "q"}) == "`dataset_ids` is required."
    assert _ask_args({"question": "q", "dataset_ids": []}) == "`dataset_ids` is required."


def test_ask_args_dataset_ids_must_be_list() -> None:
    """``dataset_ids`` nie-listą → komunikat upstream."""
    assert _ask_args({"question": "q", "dataset_ids": "x"}) == "`dataset_ids` should be a list."


def test_ask_args_valid() -> None:
    """Poprawne ciało → (question, krotka id)."""
    assert _ask_args({"question": "q", "dataset_ids": ["a", "b"]}) == ("q", ("a", "b"))
