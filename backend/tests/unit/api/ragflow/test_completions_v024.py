"""Testy kształtu completions w profilu v0.24 (CONTRACT E2-2b C0 p. 5, brief T2 p. 5).

Profil ``ragflow_0_27`` musi zostać bez zmian (pełne przypadki: ``test_present_completions``
i ``tests/unit/chat/test_sse``).
"""

from collections.abc import AsyncIterator

from app.api.ragflow.present.completions import completion_data
from app.api.ragflow.sse import TERMINATOR, TERMINATOR_V024, StreamIds, native_frames, sse_native
from app.domain.chat.events import AnswerDelta, ChatEvent, Final
from app.services.chat import CompletionResult

PROFILE_V024 = "ragflow_0_24"
PROFILE_V027 = "ragflow_0_27"

CHUNK: dict[str, object] = {
    "id": "k1",
    "content": "C",
    "dataset_id": "d",
    "document_id": "doc",
    "document_name": "n.txt",
    "image_id": "",
    "positions": [],
    "url": None,
    "similarity": 0.5,
    "vector_similarity": 0.4,
    "term_similarity": 0.1,
    "doc_type": "",
    "row_id": None,
    "document_metadata": {"a": 1},
}


def _ids(chat_id: str | None = "c") -> StreamIds:
    return StreamIds("m1", "s1", chat_id)


def _completion_result() -> CompletionResult:
    return CompletionResult(
        ids=_ids(),
        answer="A",
        thinking=None,
        reference={"total": 1, "chunks": [CHUNK], "doc_aggs": []},
        prompt="P",
        created_at=1.5,
        usage=(1, 2),
    )


async def _gen(events: tuple[ChatEvent, ...]) -> AsyncIterator[ChatEvent]:
    for ev in events:
        yield ev


def test_completion_data_v024_drops_chat_id_and_chunk_extras() -> None:
    """JSON v0.24: brak ``chat_id`` w ``data`` i ``row_id``/``document_metadata`` w chunkach."""
    data = completion_data(_completion_result(), PROFILE_V024)
    assert "chat_id" not in data
    assert list(data) == [
        "answer",
        "reference",
        "prompt",
        "created_at",
        "audio_binary",
        "id",
        "session_id",
    ]
    assert data["reference"]["chunks"] == [
        {k: v for k, v in CHUNK.items() if k not in {"row_id", "document_metadata"}}
    ]


def test_completion_data_v027_keeps_chat_id_and_chunk_keys() -> None:
    """Profil v0.27 bez zmian: ``chat_id`` i pełny chunk (bajty K4 §1.7)."""
    data = completion_data(_completion_result(), PROFILE_V027)
    assert data["chat_id"] == "c"
    assert data["reference"]["chunks"] == [CHUNK]


def test_native_frames_v024_envelope_without_message_and_chat_id() -> None:
    """Ramka v0.24: koperta ``{"code":0,"data":…}`` i ogon bez ``chat_id`` (completion--09.sse)."""
    assert native_frames(AnswerDelta("Hej"), _ids(), PROFILE_V024) == [
        b'data:{"code":0,"data":{"answer":"Hej","reference":{"chunks":[]},"audio_binary":null,'
        b'"final":false,"id":"m1","session_id":"s1"}}\n\n'
    ]


def test_native_frames_v027_bytes_unchanged() -> None:
    """Ten sam event w v0.27 daje bajty K4 (koperta z ``message``, ogon z ``chat_id``)."""
    frames = native_frames(AnswerDelta("Hej"), _ids(), PROFILE_V027)
    assert frames == [
        b'data:{"code":0,"message":"","data":{"answer":"Hej","reference":{"chunks":[]},'
        b'"audio_binary":null,"final":false,"id":"m1","session_id":"s1","chat_id":"c"}}\n\n'
    ]
    assert native_frames(AnswerDelta("Hej"), _ids()) == frames


def _empty_final() -> Final:
    return Final(
        answer="E!",
        reference={"total": 0, "chunks": [], "doc_aggs": []},
        prompt="Q",
        created_at=None,
        final_answer="E!",
        thinking=None,
        usage=(0, 0),
        empty=True,
    )


def test_native_frames_v024_empty_response_is_single_final_frame() -> None:
    """v0.24 przy pustej odpowiedzi emituje tylko ramkę ``final:true`` (C0 p. 5, brief 2c)."""
    assert native_frames(_empty_final(), _ids(), PROFILE_V024) == [
        b'data:{"code":0,"data":{"answer":"E!","reference":{"total":0,"chunks":[],"doc_aggs":[]},'
        b'"prompt":"Q","audio_binary":null,"final":true,"id":"m1","session_id":"s1"}}\n\n'
    ]


def test_native_frames_v027_empty_response_keeps_two_frames() -> None:
    """v0.27 bez zmian: ramka ``final:false`` poprzedza ramkę finalną (K4 §1.4)."""
    first, last = native_frames(_empty_final(), _ids(), PROFILE_V027)
    assert b'"final":false' in first
    assert b'"final":true' in last


def test_native_frames_v024_final_reference_without_chunk_extras() -> None:
    """Ramka finalna v0.24 niesie referencję bez ``row_id``/``document_metadata`` w chunkach."""
    ev = Final(
        answer="A",
        reference={"total": 1, "chunks": [CHUNK], "doc_aggs": []},
        prompt="P",
        created_at=1.5,
        final_answer="A",
        thinking=None,
        usage=(0, 0),
        empty=False,
    )
    (frame,) = native_frames(ev, _ids(), PROFILE_V024)
    assert b'"row_id"' not in frame
    assert b'"document_metadata"' not in frame
    assert b'"id":"k1"' in frame


async def test_sse_native_v024_terminator_without_message() -> None:
    """Terminator v0.24 to ``data:{"code":0,"data":true}`` (completion--09.sse)."""
    out = [frame async for frame in sse_native(_gen(()), _ids(), profile=PROFILE_V024)]
    assert out == [TERMINATOR_V024]
    assert [frame async for frame in sse_native(_gen(()), _ids())] == [TERMINATOR]
