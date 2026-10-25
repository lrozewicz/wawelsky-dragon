"""Testy kodera SSE (CONTRACT C3, K4 §1.1-§1.6)."""

from collections.abc import AsyncIterator

from app.api.ragflow.sse import (
    TERMINATOR,
    StreamIds,
    encode_frame,
    native_frames,
    sse_native,
)
from app.core.errors import ValidationFailed
from app.domain.chat.events import (
    AnswerDelta,
    ChatEvent,
    ErrorEvent,
    Final,
    ThinkDelta,
    ThinkEnd,
    ThinkStart,
)


def _ids() -> StreamIds:
    return StreamIds("m1", "s1", "c1")


async def _gen(events: tuple[ChatEvent, ...]) -> AsyncIterator[ChatEvent]:
    for ev in events:
        yield ev


async def _gen_raise(events: tuple[ChatEvent, ...], exc: BaseException) -> AsyncIterator[ChatEvent]:
    for ev in events:
        yield ev
    raise exc


def test_encode_frame_sanitizes_nonfinite_floats_and_keeps_utf8() -> None:
    assert encode_frame({"a": float("nan"), "b": [float("inf")], "c": "ż"}) == (
        b'data:{"a":null,"b":[null],"c":"\xc5\xbc"}\n\n'
    )


def test_native_frames_answer_delta_without_chat_id_omits_key() -> None:
    frames = native_frames(AnswerDelta("Hej"), StreamIds("m1", "s1", None))
    assert frames == [
        b'data:{"code":0,"message":"","data":{"answer":"Hej","reference":{"chunks":[]},'
        b'"audio_binary":null,"final":false,"id":"m1","session_id":"s1"}}\n\n'
    ]


def test_native_frames_error_event_uses_code_500_envelope() -> None:
    frames = native_frames(ErrorEvent("fake error"), StreamIds("m1", "s1", None))
    assert frames == [
        b'data:{"code":500,"message":"fake error",'
        b'"data":{"answer":"**ERROR**: fake error","reference":[]}}\n\n'
    ]


def test_native_frames_think_flags_at_layout_position() -> None:
    assert native_frames(ThinkStart(), _ids()) == [
        b'data:{"code":0,"message":"","data":{"answer":"","reference":{"chunks":[]},'
        b'"audio_binary":null,"final":false,"start_to_think":true,'
        b'"id":"m1","session_id":"s1","chat_id":"c1"}}\n\n'
    ]
    assert native_frames(ThinkEnd(), _ids()) == [
        b'data:{"code":0,"message":"","data":{"answer":"","reference":{"chunks":[]},'
        b'"audio_binary":null,"final":false,"end_to_think":true,'
        b'"id":"m1","session_id":"s1","chat_id":"c1"}}\n\n'
    ]
    assert native_frames(ThinkDelta("t"), _ids()) == [
        b'data:{"code":0,"message":"","data":{"answer":"t","reference":{"chunks":[]},'
        b'"audio_binary":null,"final":false,"id":"m1","session_id":"s1","chat_id":"c1"}}\n\n'
    ]


def test_native_frames_final_key_order() -> None:
    ev = Final(
        answer="",
        reference={"total": 0, "chunks": [], "doc_aggs": []},
        prompt="P",
        created_at=1727000000.5,
        final_answer="",
        thinking=None,
        usage=(0, 0),
        empty=False,
    )
    assert native_frames(ev, _ids()) == [
        b'data:{"code":0,"message":"","data":{"answer":"","reference":{"total":0,"chunks":[],'
        b'"doc_aggs":[]},"prompt":"P","created_at":1727000000.5,"final":true,"audio_binary":null,'
        b'"id":"m1","session_id":"s1","chat_id":"c1"}}\n\n'
    ]


def test_native_frames_final_empty_yields_two_frames_without_created_at() -> None:
    ev = Final(
        answer="E!",
        reference={"total": 0, "chunks": [], "doc_aggs": []},
        prompt="Q",
        created_at=None,
        final_answer="E!",
        thinking=None,
        usage=(0, 0),
        empty=True,
    )
    assert native_frames(ev, _ids()) == [
        b'data:{"code":0,"message":"","data":{"answer":"E!","reference":{"chunks":[]},"prompt":"",'
        b'"audio_binary":null,"final":false,"id":"m1","session_id":"s1","chat_id":"c1"}}\n\n',
        b'data:{"code":0,"message":"","data":{"answer":"E!","reference":{"total":0,"chunks":[],'
        b'"doc_aggs":[]},"prompt":"Q","audio_binary":null,"final":true,'
        b'"id":"m1","session_id":"s1","chat_id":"c1"}}\n\n',
    ]


async def test_sse_native_masks_non_domain_exception() -> None:
    events = _gen_raise((AnswerDelta("a"),), RuntimeError("boom"))
    out = [frame async for frame in sse_native(events, StreamIds("m1", "s1", None))]
    assert out == [
        b'data:{"code":0,"message":"","data":{"answer":"a","reference":{"chunks":[]},'
        b'"audio_binary":null,"final":false,"id":"m1","session_id":"s1"}}\n\n',
        b'data:{"code":500,"message":"Internal server error",'
        b'"data":{"answer":"**ERROR**: Internal server error","reference":[]}}\n\n',
        TERMINATOR,
    ]


async def test_sse_native_keeps_wd_error_message() -> None:
    events = _gen_raise((), ValidationFailed("zły"))
    out = [frame async for frame in sse_native(events, StreamIds("m1", "s1", None))]
    assert out == [
        b'data:{"code":500,"message":"z\xc5\x82y",'
        b'"data":{"answer":"**ERROR**: z\xc5\x82y","reference":[]}}\n\n',
        TERMINATOR,
    ]


async def test_sse_native_empty_stream_is_only_terminator() -> None:
    out = [frame async for frame in sse_native(_gen(()), _ids())]
    assert out == [TERMINATOR]


async def test_sse_native_legacy_accumulates_answer_and_drops_flags() -> None:
    events: tuple[ChatEvent, ...] = (ThinkStart(), ThinkDelta("T."), ThinkEnd(), AnswerDelta("A"))
    out = [frame async for frame in sse_native(_gen(events), _ids(), legacy=True)]
    tail = b'"audio_binary":null,"final":false,"id":"m1","session_id":"s1","chat_id":"c1"}}'
    assert out == [
        b'data:{"code":0,"message":"","data":{"answer":"<think>","reference":{"chunks":[]},'
        + tail
        + b"\n\n",
        b'data:{"code":0,"message":"","data":{"answer":"<think>T.","reference":{"chunks":[]},'
        + tail
        + b"\n\n",
        b'data:{"code":0,"message":"","data":{"answer":"<think>T.</think>","reference":{"chunks":[]},'
        + tail
        + b"\n\n",
        b'data:{"code":0,"message":"","data":{"answer":"<think>T.</think>A",'
        b'"reference":{"chunks":[]},' + tail + b"\n\n",
        TERMINATOR,
    ]


async def test_sse_native_legacy_skips_empty_delta() -> None:
    events: tuple[ChatEvent, ...] = (AnswerDelta(""), AnswerDelta("x"))
    out = [frame async for frame in sse_native(_gen(events), _ids(), legacy=True)]
    assert out == [
        b'data:{"code":0,"message":"","data":{"answer":"x","reference":{"chunks":[]},'
        b'"audio_binary":null,"final":false,"id":"m1","session_id":"s1","chat_id":"c1"}}\n\n',
        TERMINATOR,
    ]


async def test_sse_native_legacy_final_uses_accumulated_answer() -> None:
    ev = Final(
        answer="",
        reference={"chunks": []},
        prompt="P",
        created_at=1.5,
        final_answer="A",
        thinking=None,
        usage=(0, 0),
        empty=False,
    )
    events: tuple[ChatEvent, ...] = (AnswerDelta("A"), ev)
    out = [frame async for frame in sse_native(_gen(events), _ids(), legacy=True)]
    assert out == [
        b'data:{"code":0,"message":"","data":{"answer":"A","reference":{"chunks":[]},'
        b'"audio_binary":null,"final":false,"id":"m1","session_id":"s1","chat_id":"c1"}}\n\n',
        b'data:{"code":0,"message":"","data":{"answer":"A","reference":{"chunks":[]},"prompt":"P",'
        b'"created_at":1.5,"final":true,"audio_binary":null,"id":"m1","session_id":"s1","chat_id":"c1"}}\n\n',
        TERMINATOR,
    ]


async def test_sse_native_legacy_final_empty_and_error_as_native() -> None:
    ev = Final(
        answer="E!",
        reference={"total": 0, "chunks": [], "doc_aggs": []},
        prompt="Q",
        created_at=None,
        final_answer="E!",
        thinking=None,
        usage=(0, 0),
        empty=True,
    )
    out = [frame async for frame in sse_native(_gen((ev, ErrorEvent("ups"))), _ids(), legacy=True)]
    assert out == [
        # Final(empty=True) i ErrorEvent — układy jak nie-legacy (K4 §1.6).
        b'data:{"code":0,"message":"","data":{"answer":"E!","reference":{"chunks":[]},"prompt":"",'
        b'"audio_binary":null,"final":false,"id":"m1","session_id":"s1","chat_id":"c1"}}\n\n',
        b'data:{"code":0,"message":"","data":{"answer":"E!","reference":{"total":0,"chunks":[],'
        b'"doc_aggs":[]},"prompt":"Q","audio_binary":null,"final":true,'
        b'"id":"m1","session_id":"s1","chat_id":"c1"}}\n\n',
        b'data:{"code":500,"message":"ups","data":{"answer":"**ERROR**: ups","reference":[]}}\n\n',
        TERMINATOR,
    ]
