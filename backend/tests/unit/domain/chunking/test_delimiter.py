"""Przykłady z upstream RAGFlow v0.27.0 test/unit_test/rag/test_delim.py l. 64-259.

(CONTRACT WP E1-5 C3.)
"""

import pytest

from app.domain.chunking.delimiter import parse_delimiter_field, split_paragraphs

# (pole, delimiters, has_wrapped) — wszystkie wiersze tabeli C3, w kolejności z kontraktu.
_POLA_DELIMITEROW: list[tuple[str, tuple[str, ...], bool]] = [
    ("", (), False),
    (" ", (" ",), False),
    ("\n", ("\n",), False),
    ("\t", ("\t",), False),
    ("\r", ("\n",), False),
    ("!?", ("!", "?"), False),
    ("。；", ("。", "；"), False),  # noqa: RUF001 — pełnoszerokościowa interpunkcja to dane z tabeli C3
    ("`end`", ("end",), True),
    ("`###``##``#`", ("###", "##", "#"), True),
    ("`#`##`###`", ("###", "#"), True),
    ("`\n\n`", ("\n\n",), True),
    ("``", ("`",), False),
    ("\n`##`;", ("##", "\n", ";"), True),
    ("a`a`", ("a",), True),
    ("`##`#\n", ("##", "#", "\n"), True),
    ("`a`a`a`", ("a",), True),
    ("!?;", ("!", "?", ";"), False),
    ("\r\n", ("\n",), False),
    ("\r\n\r\n", ("\n",), False),
    ("`\r\n`", ("\n",), True),
    ("\n!?;。；！？", ("\n", "!", "?", ";", "。", "；", "！", "？"), False),  # noqa: RUF001
]


@pytest.mark.parametrize(
    ("pole", "oczekiwane_delimitery", "oczekiwane_has_wrapped"), _POLA_DELIMITEROW
)
def test_parse_delimiter_field(pole, oczekiwane_delimitery, oczekiwane_has_wrapped):
    """Parsowanie pola delimiterów — tabela C3 (upstream test_delim.py)."""
    spec = parse_delimiter_field(pole)
    assert spec.delimiters == oczekiwane_delimitery
    assert spec.has_wrapped is oczekiwane_has_wrapped


# (tekst, pole delimiterów, oczekiwane akapity) — przykłady C3 + gałęzie filtracji elementów.
_AKAPITY: list[tuple[str, str, list[str]]] = [
    ("a\nb\n\nc", "\n", ["a", "b", "c"]),
    ("Zdanie! Drugie? x", "!?", ["Zdanie", "Drugie", "x"]),
    ("A###B##C", "`###``##`", ["A", "B", "C"]),
    ("abc", "", ["abc"]),
    ("  ", "\n", []),
    ("  ", "", []),
    ("a\n \nb", "\n", ["a", "b"]),
    ("A\r\nB", "\n", ["A", "B"]),
]


@pytest.mark.parametrize(("tekst", "pole", "oczekiwane_akapity"), _AKAPITY)
def test_split_paragraphs(tekst, pole, oczekiwane_akapity):
    """Podział na akapity; delimiter nigdy nie trafia do wyniku (C3)."""
    spec = parse_delimiter_field(pole)
    assert split_paragraphs(tekst, spec) == oczekiwane_akapity
