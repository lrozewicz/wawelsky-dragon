"""Testy completion_data (CONTRACT C5, K4 §1.7) — przypadki z briefu T4 dosłownie."""

from app.api.ragflow.present.completions import completion_data
from app.domain.chat.events import StreamIds
from app.services.chat import CompletionResult

PROFILE = "ragflow_0_27"


def _result(*, chat_id: str | None = "c", thinking: str | None = None) -> CompletionResult:
    return CompletionResult(
        ids=StreamIds("m", "s", chat_id),
        answer="A",
        thinking=thinking,
        reference={"x": float("nan")},
        prompt="P",
        created_at=1.5,
        usage=(1, 2),
    )


def test_completion_data_key_order_and_sanitize() -> None:
    d = completion_data(_result(), PROFILE)
    assert d == {
        "answer": "A",
        "reference": {"x": None},
        "prompt": "P",
        "created_at": 1.5,
        "audio_binary": None,
        "id": "m",
        "session_id": "s",
        "chat_id": "c",
    }
    assert list(d) == [
        "answer",
        "reference",
        "prompt",
        "created_at",
        "audio_binary",
        "id",
        "session_id",
        "chat_id",
    ]


def test_no_chat_id_key_when_none() -> None:
    d = completion_data(_result(chat_id=None), PROFILE)
    assert "chat_id" not in d
    assert list(d)[-1] == "session_id"


def test_thinking_last_key() -> None:
    d = completion_data(_result(thinking="T"), PROFILE)
    assert list(d)[-1] == "thinking"
    assert d["thinking"] == "T"
