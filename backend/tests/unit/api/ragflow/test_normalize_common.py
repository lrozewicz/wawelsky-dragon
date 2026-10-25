"""Testy normalize/common: Command, format_validation_error, parse_model, to_bool (C4)."""

import pydantic
import pytest

from app.api.ragflow.normalize.common import Command, format_validation_error, parse_model, to_bool
from app.core.errors import ValidationFailed

# Komunikat pydantic dla niepoparsanego int (stała, by linie nie przekroczyły limitu).
INT_MSG = "Input should be a valid integer, unable to parse string as an integer"


class M(Command):
    n: int


class Two(Command):
    a: int
    b: int


class Inner(Command):
    n: int


class Outer(Command):
    inner: Inner


def test_parse_model_ignores_extra_keys() -> None:
    """parse_model(M, {"n": 1, "extra": 2}) — klucz nadmiarowy ignorowany."""
    assert parse_model(M, {"n": 1, "extra": 2}) == M(n=1)


def test_command_is_frozen() -> None:
    """Command zamrożony — mutacja pola rzuca błąd walidacji."""
    model = parse_model(M, {"n": 1})
    with pytest.raises(pydantic.ValidationError):
        model.n = 2  # type: ignore[misc]


def test_format_validation_error_single_field() -> None:
    """Format upstream: Field/Message/Value w jednej linii."""
    with pytest.raises(pydantic.ValidationError) as exc_info:
        M.model_validate({"n": "x"})
    expected = f"Field: <n> - Message: <{INT_MSG}> - Value: <x>"
    assert format_validation_error(exc_info.value) == expected


def test_format_validation_error_truncates_long_value() -> None:
    """Wartość dłuższa niż 128 znaków → pierwsze 125 + '...'."""
    with pytest.raises(pydantic.ValidationError) as exc_info:
        M.model_validate({"n": "a" * 200})
    message = format_validation_error(exc_info.value)
    assert message == f"Field: <n> - Message: <{INT_MSG}> - Value: <{'a' * 125}...>"


def test_format_validation_error_joins_lines_with_newline() -> None:
    """Wiele błędów — po jednej linii MSG_FIELD_INVALID na błąd, złączone '\\n'."""
    with pytest.raises(pydantic.ValidationError) as exc_info:
        Two.model_validate({"a": "x", "b": "y"})
    message = format_validation_error(exc_info.value)
    assert message == (
        f"Field: <a> - Message: <{INT_MSG}> - Value: <x>\n"
        f"Field: <b> - Message: <{INT_MSG}> - Value: <y>"
    )


def test_format_validation_error_joins_loc_with_dots() -> None:
    """Zagnieżdżona ścieżka pola — loc łączone kropką, także segment numeryczny."""
    with pytest.raises(pydantic.ValidationError) as exc_info:
        Outer.model_validate({"inner": {"n": "x"}})
    message = format_validation_error(exc_info.value)
    assert message == f"Field: <inner.n> - Message: <{INT_MSG}> - Value: <x>"


def test_parse_model_raises_validation_failed_with_formatted_message() -> None:
    """ValidationError → ValidationFailed z komunikatem format_validation_error."""
    with pytest.raises(ValidationFailed) as exc_info:
        parse_model(M, {"n": "x"})
    assert exc_info.value.message == f"Field: <n> - Message: <{INT_MSG}> - Value: <x>"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("FALSE", False),
        (False, False),
        ("no", True),
        ("true", True),
        ("True", True),
        (0, True),
        ("false", False),
    ],
)
def test_to_bool(value: object, expected: bool) -> None:
    """to_bool: tylko łańcuch 'false' (bez znaczenia wielkości liter) jest False."""
    assert to_bool(value) is expected
