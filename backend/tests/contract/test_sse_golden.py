"""Złoto SSE (K4 §5): bajtowa zgodność kodera z v0.27.2 (§1.4) i złotem WD (§1.2/§1.5/§1.6).

Oczekiwane ramki WD to LITERAŁY bajtowe wpisane ręcznie według tabel K4 — koder nie jest
porównywany z samym sobą. Złoto v0.27.2 bez normalizatora: tokeny <ID:…> podane jako wartości.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from app.api.ragflow.sse import TERMINATOR, StreamIds, sse_native
from app.domain.chat.events import ChatEvent, Final

pytestmark = pytest.mark.contract

GOLDEN = Path(__file__).parent / "golden"
WD = GOLDEN / "wd" / "sse"


async def _events(*evs: ChatEvent) -> AsyncIterator[ChatEvent]:
    for ev in evs:
        yield ev


def _empty_response() -> Final:
    """Zdarzenie ścieżki empty_response z wartościami K4 §1.4 (E, questions, brak created_at)."""
    text = "Sorry! No relevant content was found in the knowledge base!"
    return Final(
        answer=text,
        reference={"total": 0, "chunks": [], "doc_aggs": []},
        prompt="\n\n### Query:\nOdpowiedź testowa: Output:",
        created_at=None,
        final_answer=text,
        thinking=None,
        usage=(0, 0),
        empty=True,
    )


def _golden_bytes(*parts: str) -> bytes:
    """Bajty pliku złota wczytane przy zbieraniu testów (sync — poza pętlą async)."""
    return (GOLDEN.joinpath(*parts)).read_bytes()


@pytest.mark.parametrize(
    ("message_id", "expected"),
    [
        ("<ID:id#3>", _golden_bytes("v0.27.2", "chats___completions", "completion--09.sse")),
        ("<ID:id#5>", _golden_bytes("v0.27.2", "chat__completions", "completion--11.sse")),
    ],
)
async def test_empty_response_bytes_match_v0272_golden(message_id: str, expected: bytes) -> None:
    ids = StreamIds(message_id, "<ID:session#1>", "<ID:chat#1>")
    out = b"".join([frame async for frame in sse_native(_events(_empty_response()), ids)])
    assert out == expected


def _wd_frames(name: str) -> list[bytes]:
    """Ramki pliku złota WD (podział po b"\\n\\n"); plik musi kończyć się TERMINATORem."""
    raw = (WD / name).read_bytes()
    assert raw.endswith(TERMINATOR)
    parts = raw.split(b"\n\n")
    assert parts[-1] == b""
    return parts[:-1]


def test_wd_golden_think_answer() -> None:
    assert _wd_frames("think_answer.sse") == [
        b'data:{"code":0,"message":"","data":{"answer":"","reference":{"chunks":[]},'
        b'"audio_binary":null,"final":false,"start_to_think":true,'
        b'"id":"m-1","session_id":"s-1","chat_id":"c-1"}}',
        b'data:{"code":0,"message":"","data":{"answer":"Rozwa\xc5\xbcam.",'
        b'"reference":{"chunks":[]},"audio_binary":null,"final":false,'
        b'"id":"m-1","session_id":"s-1","chat_id":"c-1"}}',
        b'data:{"code":0,"message":"","data":{"answer":"","reference":{"chunks":[]},'
        b'"audio_binary":null,"final":false,"end_to_think":true,'
        b'"id":"m-1","session_id":"s-1","chat_id":"c-1"}}',
        b'data:{"code":0,"message":"","data":{"answer":"Odpowied\xc5\xba [ID:0]",'
        b'"reference":{"chunks":[]},"audio_binary":null,"final":false,'
        b'"id":"m-1","session_id":"s-1","chat_id":"c-1"}}',
        b'data:{"code":0,"message":"","data":{"answer":"","reference":{"chunks":[]},'
        b'"prompt":"","created_at":1727000000.5,"final":true,"audio_binary":null,'
        b'"id":"m-1","session_id":"s-1","chat_id":"c-1"}}',
        b'data:{"code":0,"message":"","data":true}',
    ]


def test_wd_golden_legacy_think_answer() -> None:
    # K4 §1.6: answer skumulowany (ThinkStart dopisuje "<think>", ThinkEnd "</think>"),
    # klucze start_to_think/end_to_think usunięte, finał z pełnym tekstem.
    assert _wd_frames("legacy_think_answer.sse") == [
        b'data:{"code":0,"message":"","data":{"answer":"<think>","reference":{"chunks":[]},'
        b'"audio_binary":null,"final":false,"id":"m-1","session_id":"s-1","chat_id":"c-1"}}',
        b'data:{"code":0,"message":"","data":{"answer":"<think>Rozwa\xc5\xbcam.",'
        b'"reference":{"chunks":[]},"audio_binary":null,"final":false,'
        b'"id":"m-1","session_id":"s-1","chat_id":"c-1"}}',
        b'data:{"code":0,"message":"","data":{"answer":"<think>Rozwa\xc5\xbcam.</think>",'
        b'"reference":{"chunks":[]},"audio_binary":null,"final":false,'
        b'"id":"m-1","session_id":"s-1","chat_id":"c-1"}}',
        b'data:{"code":0,"message":"","data":'
        b'{"answer":"<think>Rozwa\xc5\xbcam.</think>Odpowied\xc5\xba [ID:0]",'
        b'"reference":{"chunks":[]},"audio_binary":null,"final":false,'
        b'"id":"m-1","session_id":"s-1","chat_id":"c-1"}}',
        b'data:{"code":0,"message":"","data":'
        b'{"answer":"<think>Rozwa\xc5\xbcam.</think>Odpowied\xc5\xba [ID:0]",'
        b'"reference":{"chunks":[]},"prompt":"","created_at":1727000000.5,'
        b'"final":true,"audio_binary":null,"id":"m-1","session_id":"s-1","chat_id":"c-1"}}',
        b'data:{"code":0,"message":"","data":true}',
    ]


def test_wd_golden_error_midstream() -> None:
    # K4 §1.5: ramka błędu z code 500 (bez koperty 0, bez ids), potem terminator.
    assert _wd_frames("error_midstream.sse") == [
        b'data:{"code":0,"message":"","data":{"answer":"Cz\xc4\x99\xc5\x9b",'
        b'"reference":{"chunks":[]},"audio_binary":null,"final":false,'
        b'"id":"m-1","session_id":"s-1"}}',
        b'data:{"code":500,"message":"fake error",'
        b'"data":{"answer":"**ERROR**: fake error","reference":[]}}',
        b'data:{"code":0,"message":"","data":true}',
    ]


def test_wd_golden_empty_llm_answer() -> None:
    # Pusta odpowiedź LLM: brak ramek — tylko terminator (K4 §1.2).
    assert _wd_frames("empty_llm_answer.sse") == [
        b'data:{"code":0,"message":"","data":true}',
    ]
