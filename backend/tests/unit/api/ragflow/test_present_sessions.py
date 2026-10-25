"""Testy prezentera sesji (CONTRACT C5) — klucze = złoto v0.27.2 (test czyta plik)."""

import json
from pathlib import Path

from app.api.ragflow.present.sessions import session_detail
from app.services.sessions import MessageView, SessionView

# Profil dziś nieużywany przez presenter (zarezerwowany dla E2-2).
PROFILE = "ragflow_0_27"
GOLDEN = Path(__file__).parents[3] / "contract" / "golden" / "v0.27.2" / "chats___sessions"
TIME_MS = 1700000000000


def _view(messages: list[MessageView]) -> SessionView:
    """Widok sesji z podanymi wiadomościami (avatar = icon czatu)."""
    return SessionView(
        id="sess1",
        chat_id="chat1",
        name="sesja",
        user_id="user1",
        create_time=TIME_MS,
        update_time=TIME_MS,
        messages=messages,
        avatar="icon.png",
    )


def _prologue() -> list[MessageView]:
    """Wiadomość prologue: assistant, seq 0, bez reference (złoto chat_session--03)."""
    return [
        MessageView(
            id="m0",
            seq=0,
            role="assistant",
            content="Hi! I'm your assistant. What can I do for you?",
            reference=None,
            created_at=1.0,
        )
    ]


def test_session_detail_keys_match_golden() -> None:
    golden = json.loads((GOLDEN / "chat_session--03.json").read_bytes())
    view = _view(_prologue())
    view = SessionView(
        id=view.id,
        chat_id=view.chat_id,
        name="wd_rec_session",
        user_id=view.user_id,
        create_time=view.create_time,
        update_time=view.update_time,
        messages=view.messages,
        avatar="",
    )
    d = session_detail(view, PROFILE)
    assert sorted(d) == sorted(golden["body"]["data"])
    assert d["messages"] == [
        {"role": "assistant", "content": "Hi! I'm your assistant. What can I do for you?"}
    ]
    assert d["reference"] == []
    assert d["create_time"] == TIME_MS
    assert d["update_time"] == TIME_MS
    assert isinstance(d["create_date"], str)


def test_message_shapes_by_role_and_seq() -> None:
    """C5: seq 0 + assistant → 2 klucze; user → 3; inne → 4 (created_at, id)."""
    messages = [
        MessageView(id="m0", seq=0, role="assistant", content="a", reference=None, created_at=1.0),
        MessageView(id="u1", seq=1, role="user", content="q", reference=None, created_at=2.0),
        MessageView(id="a1", seq=2, role="assistant", content="r", reference=None, created_at=1.5),
        MessageView(id="x1", seq=3, role="system", content="s", reference=None, created_at=2.5),
    ]
    d = session_detail(_view(messages), PROFILE)
    assert d["messages"] == [
        {"role": "assistant", "content": "a"},
        {"role": "user", "content": "q", "id": "u1"},
        {"role": "assistant", "content": "r", "created_at": 1.5, "id": "a1"},
        {"role": "system", "content": "s", "created_at": 2.5, "id": "x1"},
    ]


def test_reference_assistant_seq_positive_only() -> None:
    """reference = tylko assistant z seq > 0; None → {"chunks": [], "doc_aggs": []}."""
    reference = {"chunks": [{"id": "c1"}], "doc_aggs": [{"doc_id": "d1"}]}
    messages = [
        MessageView(
            id="m0", seq=0, role="assistant", content="a", reference=reference, created_at=1.0
        ),
        MessageView(id="u1", seq=1, role="user", content="q", reference=reference, created_at=2.0),
        MessageView(id="a1", seq=2, role="assistant", content="r", reference=None, created_at=1.5),
    ]
    d = session_detail(_view(messages), PROFILE)
    assert d["reference"] == [{"chunks": [], "doc_aggs": []}]


def test_reference_passthrough_when_present() -> None:
    reference = {"chunks": [{"id": "c1"}], "doc_aggs": []}
    messages = [
        MessageView(
            id="a1", seq=1, role="assistant", content="r", reference=reference, created_at=1.5
        ),
    ]
    d = session_detail(_view(messages), PROFILE)
    assert d["reference"] == [reference]


def test_avatar_only_with_flag() -> None:
    d = session_detail(_view(_prologue()), PROFILE)
    assert "avatar" not in d
    with_avatar = session_detail(_view(_prologue()), PROFILE, with_avatar=True)
    assert with_avatar["avatar"] == "icon.png"
    assert sorted(with_avatar) == sorted([*sorted(d), "avatar"])


def test_message_feedback_keys_only_when_set() -> None:
    """Złoto chat_extras--12: assistant z thumbup; brak oceny → brak kluczy (E2-1 CHAT)."""
    without = MessageView(
        id="m1", seq=1, role="assistant", content="r", reference=None, created_at=1.5
    )
    assert "thumbup" not in session_detail(_view([without]), PROFILE)["messages"][0]
    down = MessageView(
        id="m1",
        seq=1,
        role="assistant",
        content="r",
        reference=None,
        created_at=1.5,
        thumbup=False,
        feedback="nie tak",
    )
    up = MessageView(
        id="m1",
        seq=1,
        role="assistant",
        content="r",
        reference=None,
        created_at=1.5,
        thumbup=True,
    )
    assert session_detail(_view([down]), PROFILE)["messages"][0] == {
        "role": "assistant",
        "content": "r",
        "created_at": 1.5,
        "id": "m1",
        "thumbup": False,
        "feedback": "nie tak",
    }
    assert session_detail(_view([up]), PROFILE)["messages"][0] == {
        "role": "assistant",
        "content": "r",
        "created_at": 1.5,
        "id": "m1",
        "thumbup": True,
    }
