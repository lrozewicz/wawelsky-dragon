"""Testy prezentera sesji v0.24 (CONTRACT C3) — klucze = złoto v0.24.0 (test czyta plik)."""

import json
from pathlib import Path
from typing import Any

from app.api.ragflow.present.sessions import session_detail
from app.services.sessions import MessageView, SessionView

PROFILE_V024 = "ragflow_0_24"
GOLDEN = Path(__file__).parents[3] / "contract" / "golden" / "v0.24.0" / "chats___sessions"
TIME_MS = 1700000000000
PROLOGUE = "Hi! I'm your assistant. What can I do for you?"


def _golden(name: str) -> Any:
    """``body.data`` pliku złota (obiekt albo lista sesji)."""
    return json.loads((GOLDEN / name).read_bytes())["body"]["data"]


def _view(messages: list[MessageView], *, avatar: str = "icon.png") -> SessionView:
    """Widok sesji z podanymi wiadomościami (avatar = icon czatu)."""
    return SessionView(
        id="s1",
        chat_id="chat1",
        name="wd_rec_session",
        user_id="",
        create_time=TIME_MS,
        update_time=TIME_MS,
        messages=messages,
        avatar=avatar,
    )


def _prologue(content: str = PROLOGUE) -> MessageView:
    """Prolog: assistant, seq 0, bez referencji."""
    return MessageView(
        id="m0", seq=0, role="assistant", content=content, reference=None, created_at=1.0
    )


def _pair(seq: int, reference: dict[str, Any] | None) -> list[MessageView]:
    """Para pytanie/odpowiedź; ``seq`` = seq pytania (odpowiedź ``seq + 1``)."""
    return [
        MessageView(
            id=f"u{seq}", seq=seq, role="user", content="Pytanie?", reference=None, created_at=2.0
        ),
        MessageView(
            id=f"a{seq}",
            seq=seq + 1,
            role="assistant",
            content="Odpowiedź.",
            reference=reference,
            created_at=3.0,
        ),
    ]


def _stored_chunk() -> dict[str, Any]:
    """Chunk referencji w kształcie naszej bazy (``chunk_ref``, K4 §1.2)."""
    return {
        "id": "c1",
        "content": "Legenda o smoku wawelskim.",
        "document_id": "d1",
        "document_name": "ragflow_intro.txt",
        "dataset_id": "s1",
        "image_id": "",
        "positions": [[1, 0, 0, 0, 0]],
        "url": None,
        "similarity": 0.75,
        "vector_similarity": 0.8,
        "term_similarity": 0.7,
        "row_id": None,
        "doc_type": "",
        "document_metadata": None,
    }


# Chunk referencji v0.24 (upstream ``list_session``): dokładnie 7 kluczy.
CHUNK_REFERENCE: dict[str, Any] = {
    "id": "c1",
    "content": "Legenda o smoku wawelskim.",
    "document_id": "d1",
    "document_name": "ragflow_intro.txt",
    "dataset_id": "s1",
    "image_id": "",
    "positions": [[1, 0, 0, 0, 0]],
}


def _reference(*chunks: dict[str, Any]) -> dict[str, Any]:
    return {"total": len(chunks), "chunks": list(chunks), "doc_aggs": []}


def test_create_session_keys_match_golden() -> None:
    """Złoto --03 (POST /sessions): klucze i prolog; bez ``reference`` i ``avatar`` w danych."""
    golden = _golden("chat_session--03.json")
    d = session_detail(_view([_prologue()]), PROFILE_V024)
    assert sorted(d) == sorted(golden)
    assert d["messages"] == golden["messages"]
    assert "reference" not in d
    assert d["create_time"] == TIME_MS
    assert d["update_time"] == TIME_MS
    assert isinstance(d["create_date"], str)
    assert d["user_id"] == ""


def test_list_session_item_keys_match_golden() -> None:
    """Złoto --04 (GET /sessions): ten sam kształt elementu listy."""
    golden = _golden("chat_session--04.json")[0]
    d = session_detail(_view([_prologue()]), PROFILE_V024)
    assert sorted(d) == sorted(golden)
    assert d["messages"] == golden["messages"]


def test_avatar_never_emitted_in_profile_0_24() -> None:
    """C0 p. 4: profil 0.24 nie ma ``avatar`` także przy ``with_avatar=True``."""
    assert "avatar" not in session_detail(_view([_prologue()]), PROFILE_V024, with_avatar=True)


def test_reference_goes_to_assistant_answer_not_prologue() -> None:
    """Brief T3 p. 3: prolog + jedna para z jedną referencją → referencja przy odpowiedzi pary."""
    messages = [_prologue(), *_pair(1, _reference(_stored_chunk()))]
    d = session_detail(_view(messages), PROFILE_V024)
    assert "reference" not in d["messages"][0]
    assert "reference" not in d["messages"][1]
    assert d["messages"][2]["reference"] == [CHUNK_REFERENCE]
    assert d["messages"][2]["role"] == "assistant"


def test_reference_follows_message_order_for_each_pair() -> None:
    """C3: n-ta niepusta referencja → n-ta wiadomość roli ≠ user (poza prologiem)."""
    first = _stored_chunk()
    second = {**first, "id": "c2"}
    messages = [_prologue(), *_pair(1, _reference(first)), *_pair(3, _reference(second))]
    d = session_detail(_view(messages), PROFILE_V024)
    assert d["messages"][2]["reference"] == [CHUNK_REFERENCE]
    assert d["messages"][4]["reference"] == [{**CHUNK_REFERENCE, "id": "c2"}]
    assert "reference" not in d["messages"][1]
    assert "reference" not in d["messages"][3]


def test_reference_uses_legacy_chunk_keys() -> None:
    """C3: fallbacki upstream na stare nazwy kluczy chunków (chunk_id/doc_id/docnm_kwd…)."""
    legacy = {
        "chunk_id": "c9",
        "content_with_weight": "Treść.",
        "doc_id": "d9",
        "docnm_kwd": "plik.txt",
        "kb_id": "s9",
        "img_id": "img9",
        "position_int": [[2, 1, 1, 0, 0]],
    }
    d = session_detail(_view([_prologue(), *_pair(1, _reference(legacy))]), PROFILE_V024)
    assert d["messages"][2]["reference"] == [
        {
            "id": "c9",
            "content": "Treść.",
            "document_id": "d9",
            "document_name": "plik.txt",
            "dataset_id": "s9",
            "image_id": "img9",
            "positions": [[2, 1, 1, 0, 0]],
        }
    ]


def test_reference_empty_chunks_still_emits_empty_list() -> None:
    """C3/upstream: referencja bez ``chunks`` → pusta lista przy wiadomości (a nie brak klucza)."""
    d = session_detail(_view([_prologue(), *_pair(1, {"total": 0, "doc_aggs": []})]), PROFILE_V024)
    assert d["messages"][2]["reference"] == []


def test_session_without_reference_has_no_reference_key() -> None:
    """C3: brak referencji → wiadomości bez klucza ``reference`` (także odpowiedź)."""
    d = session_detail(_view([_prologue(), *_pair(1, None)]), PROFILE_V024)
    assert all("reference" not in m for m in d["messages"])


def test_profile_0_27_unchanged() -> None:
    """C0 p. 1: profil 0.27 bez zmian (klucz ``reference`` na górze, ``avatar`` wg flagi)."""
    view = _view([_prologue(), *_pair(1, _reference(_stored_chunk()))])
    d = session_detail(view, "ragflow_0_27")
    assert "reference" in d
    assert "avatar" not in d
    assert session_detail(view, "ragflow_0_27", with_avatar=True)["avatar"] == "icon.png"
    assert "reference" not in d["messages"][2]
