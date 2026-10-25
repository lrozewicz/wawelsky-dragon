"""StreamIds — jedna definicja w app.domain.chat.events (K4 §6 p. 5)."""

import dataclasses

import pytest

from app.api.ragflow import sse
from app.domain.chat import events
from app.services import chat


def test_single_definition() -> None:
    assert sse.StreamIds is events.StreamIds
    assert chat.StreamIds is events.StreamIds


def test_frozen() -> None:
    ids = events.StreamIds("m", None, None)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ids.message_id = "x"


def test_fields_order() -> None:
    assert [f.name for f in dataclasses.fields(events.StreamIds)] == [
        "message_id",
        "session_id",
        "chat_id",
    ]
