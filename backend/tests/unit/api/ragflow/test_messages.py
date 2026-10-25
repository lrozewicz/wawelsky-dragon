"""Testy komunikatów walidacji (C3, przykłady briefu dosłownie)."""

from app.api.ragflow.messages import MSG_COMPAT_INVALID, MSG_FIELD_INVALID, literal_message


def test_literal_message_two_options_sorted() -> None:
    """Dwie opcje — posortowane, forma 'a' or 'b'."""
    assert literal_message(["update_time", "create_time"]) == (
        "Input should be 'create_time' or 'update_time'"
    )


def test_literal_message_single_option() -> None:
    """Jedna opcja — bez spójnika."""
    assert literal_message(["a"]) == "Input should be 'a'"


def test_literal_message_three_options_sorted() -> None:
    """Trzy opcje — posortowane, przecinki i 'or' przed ostatnią."""
    assert literal_message(["c", "a", "b"]) == "Input should be 'a', 'b' or 'c'"


def test_message_templates() -> None:
    """Szablony dosłownie z kontraktu C3."""
    assert MSG_FIELD_INVALID == "Field: <{field}> - Message: <{msg}> - Value: <{value}>"
    assert MSG_COMPAT_INVALID.format(value="1.0") == (
        "Invalid compat profile: 1.0. Expected '0.24' or '0.27'."
    )
