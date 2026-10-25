"""Szablony komunikatów walidacji upstream i pomocnik Literal (C3)."""

from collections.abc import Iterable

# Upstream validation_utils.py:230 (v0.27.2).
MSG_FIELD_INVALID = "Field: <{field}> - Message: <{msg}> - Value: <{value}>"
# Komunikat WD (brak odpowiednika upstream).
MSG_COMPAT_INVALID = "Invalid compat profile: {value}. Expected '0.24' or '0.27'."


def literal_message(options: Iterable[str]) -> str:
    """Komunikat pydantic Literal — opcje posortowane, forma zależna od liczby (C3).

    1 → "Input should be 'a'"; 2 → "Input should be 'a' or 'b'";
    3+ → "Input should be 'a', 'b' or 'c'".
    """
    ordered = sorted(options)
    if len(ordered) == 1:
        return f"Input should be '{ordered[0]}'"
    head = ", ".join(f"'{option}'" for option in ordered[:-1])
    return f"Input should be {head} or '{ordered[-1]}'"
