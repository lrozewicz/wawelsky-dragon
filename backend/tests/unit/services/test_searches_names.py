"""Testy jednostkowe dopisku duplikatu nazwy wyszukiwarki (CONTRACT E4-4a §D4).

Semantyka upstream ``duplicate_name``/``_split_name_counter``
(``api/db/services/__init__.py`` v0.27.2, l. 20-110) na czystej funkcji ``unique_name``.
"""

from collections.abc import Awaitable, Callable

import pytest

from app.services.searches import unique_name

MAX_ATTEMPTS = 1000  # limit prób z §D4


def _taken(*names: str) -> Callable[[str], Awaitable[bool]]:
    """``taken`` na zbiorze zajętych nazw z listy argumentów."""

    async def check(candidate: str) -> bool:
        return candidate in names

    return check


async def test_free_name_is_returned_unchanged() -> None:
    """Nazwa wolna → bez zmian."""
    assert await unique_name("a", _taken()) == "a"


async def test_first_duplicate_gets_counter_one() -> None:
    """Zajęta ``a`` → ``a(1)`` (przykład z briefu)."""
    assert await unique_name("a", _taken("a")) == "a(1)"


async def test_counter_grows_from_existing_suffix() -> None:
    """Zajęte ``a`` i ``a(1)`` → ``a(2)`` (przykład z briefu)."""
    assert await unique_name("a", _taken("a", "a(1)")) == "a(2)"


async def test_existing_suffix_keeps_counting() -> None:
    """Zajęte ``a(9)`` → baza ``a`` z licznikiem 10 (nie ``a(9)(1)``)."""
    assert await unique_name("a(9)", _taken("a(9)")) == "a(10)"


async def test_suffix_base_is_stripped() -> None:
    """Baza z ``(n)`` traci końcowe spacje (upstream ``rstrip``)."""
    assert await unique_name("a (1)", _taken("a (1)")) == "a(2)"


async def test_parentheses_without_digits_are_part_of_the_base() -> None:
    """``a(2b)`` nie jest licznikiem → dopisek ``(1)`` do całej nazwy."""
    assert await unique_name("a(2b)", _taken("a(2b)")) == "a(2b)(1)"


async def test_taken_called_with_original_name_first() -> None:
    """``taken`` dostaje kolejno nazwę żądaną i dopisane kandydatury."""
    seen: list[str] = []

    async def check(candidate: str) -> bool:
        seen.append(candidate)
        return candidate in {"a", "a(1)"}

    assert await unique_name("a", check) == "a(2)"
    assert seen == ["a", "a(1)", "a(2)"]


async def test_runtime_error_after_max_attempts() -> None:
    """Zawsze zajęta nazwa → ``RuntimeError`` po 1000 próbach."""
    calls = 0

    async def check(_candidate: str) -> bool:
        nonlocal calls
        calls += 1
        return True

    with pytest.raises(RuntimeError):
        await unique_name("a", check)
    assert calls == MAX_ATTEMPTS
