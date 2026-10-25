"""Testy zdarzeń czatu i error_message (CONTRACT C1, K4 §1.5/§3.1)."""

from app.core.errors import ValidationFailed
from app.domain.chat.events import error_message


def test_error_message_returns_wd_error_message() -> None:
    assert error_message(ValidationFailed("x")) == "x"


def test_error_message_masks_other_exceptions() -> None:
    assert error_message(KeyError("k")) == "Internal server error"
