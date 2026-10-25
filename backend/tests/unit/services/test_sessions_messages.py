"""Testy jednostkowe usługi sesji (E2-1 CHAT): parowanie wiadomości i id pary."""

from app.db.repositories.chat_messages import MessageRow
from app.services.sessions import SessionsService, _assistant_of_pair, _first_seq_of_pair

# Profil nie jest potrzebny — usługa nie dotyka warstwy HTTP.
_TIME_MS = 1700000000000


def _row(seq: int, role: str, message_id: str, *, thumbup: bool | None = None) -> MessageRow:
    """Wiersz wiadomości o zadanym seq/roli/id (reszta pól stała)."""
    return MessageRow(
        id=message_id,
        session_id="s" * 32,
        seq=seq,
        role=role,  # type: ignore[arg-type]
        content=f"treść {seq}",
        reference=None,
        prompt_tokens=None,
        completion_tokens=None,
        created_at=1.0,
        create_time=_TIME_MS,
        thumbup=thumbup,
    )


def test_messages_pair_shares_assistant_id() -> None:
    """Para user+assistant dzieli id asystenta; prologue i sierota zachowują własne (K4 §3.3)."""
    rows = [
        _row(0, "assistant", "prologue"),
        _row(1, "user", "user-1"),
        _row(2, "assistant", "assistant-1"),
        _row(3, "user", "user-2"),
    ]
    views = SessionsService._messages(rows)
    assert [view.id for view in views] == ["prologue", "assistant-1", "assistant-1", "user-2"]
    assert [view.seq for view in views] == [0, 1, 2, 3]


def test_pair_lookup_from_both_roles() -> None:
    """Usunięcie/feedback działa po id pary z dowolnej strony (upstream: oba wpisy dzielą id)."""
    rows = [_row(0, "assistant", "p"), _row(1, "user", "u"), _row(2, "assistant", "a")]
    assert _first_seq_of_pair(rows, "a") == 1
    assert _first_seq_of_pair(rows, "u") == 1
    assert _first_seq_of_pair(rows, "nie-ma") is None
    assert _assistant_of_pair(rows, "a") is not None
    assert _assistant_of_pair(rows, "u") is None
