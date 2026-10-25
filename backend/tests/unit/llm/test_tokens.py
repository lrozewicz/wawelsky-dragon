"""Testy liczenia tokenów cl100k_base (kontrakt C6, K5 §3.6)."""

from app.llm.tokens import count_tokens, truncate_tokens


def test_empty_text() -> None:
    assert count_tokens("") == 0


def test_hello_world() -> None:
    expected = 2
    assert count_tokens("hello world") == expected


def test_special_token_is_plain_text() -> None:
    # disallowed_special=() — tag specjalny bez wyjątku, liczony jako zwykły tekst (> 1 token).
    assert count_tokens("<|endoftext|>") > 1


def test_truncate_to_one_token() -> None:
    assert truncate_tokens("hello world", 1) == "hello"


def test_truncate_zero_limit() -> None:
    assert truncate_tokens("hello world", 0) == ""


def test_truncate_negative_limit() -> None:
    assert truncate_tokens("hello world", -2) == ""


def test_truncate_above_limit_returns_text() -> None:
    assert truncate_tokens("hello world", 100) == "hello world"
