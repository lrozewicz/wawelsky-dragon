"""Testy separacji bloku <think> (kontrakt C5: split_think i ThinkStreamParser)."""

from typing import Final, Literal

import pytest

from app.llm.think import ThinkStreamParser, split_think

Event = tuple[Literal["reasoning", "text"], str]


def _run_stream(chunks: list[str]) -> list[Event]:
    parser = ThinkStreamParser()
    events: list[Event] = []
    for chunk in chunks:
        events.extend(parser.feed(chunk))
    events.extend(parser.flush())
    return events


def _join(events: list[Event]) -> tuple[str, str]:
    reasoning = "".join(value for kind, value in events if kind == "reasoning")
    text = "".join(value for kind, value in events if kind == "text")
    return reasoning, text


def _assert_nonempty_and_ordered(events: list[Event]) -> None:
    """Żaden fragment nie jest pusty; wszystkie reasoning przed pierwszym text."""
    assert all(value for _, value in events)
    seen_text = False
    for kind, _ in events:
        if kind == "text":
            seen_text = True
        else:
            assert not seen_text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "<think>Rozważam pytanie.</think>Odpowiedź testowa: x",
            ("Rozważam pytanie.", "Odpowiedź testowa: x"),
        ),
        ("  \n<think> a </think>\n\nb", ("a", "b")),
        ("abc <think>x</think> d", (None, "abc <think>x</think> d")),
        ("<think>niedomknięte", (None, "<think>niedomknięte")),
        ("<think></think>abc", ("", "abc")),
        ("", (None, "")),
    ],
)
def test_split_think(text: str, expected: tuple[str | None, str]) -> None:
    assert split_think(text) == expected


# (chunki, reasoning sklejony, text sklejony); każdy przypadek kończy flush()
_STREAM_CASES: Final[list[tuple[list[str], str, str]]] = [
    (["<think>Rozwa", "żam pytanie.</thi", "nk>Odpo", "wiedź"], "Rozważam pytanie.", "Odpowiedź"),
    (
        ["<", "t", "h", "i", "n", "k", ">", "r", "<", "/", "t", "h", "i", "n", "k", ">", "t"],
        "r",
        "t",
    ),
    (["Odpowiedź ", "<think>x</think>"], "", "Odpowiedź <think>x</think>"),
    (["<th", "is is text"], "", "<this is text"),
    (["  ", "<think>a</think>", "  ", "b"], "a", "b"),
    (["<think>a</think>b  c"], "a", "b  c"),
    (["<thi"], "", "<thi"),
    (["<think>abc</th"], "abc</th", ""),
    ([], "", ""),
    # niedomknięty <think> w strumieniu: reasoning = reszta, text = "" (odchyłka od split_think)
    (["<think>abc"], "abc", ""),
    # puste chunki nie emitują zdarzeń i nie zmieniają wyniku
    (["", "<think>a", "", "b</think>c", ""], "ab", "c"),
    # białe znaki po </think> odrzucane także w kolejnym chunku
    (["<think>a</think>", "  b"], "a", "b"),
]


@pytest.mark.parametrize(("chunks", "reasoning", "text"), _STREAM_CASES)
def test_stream(chunks: list[str], reasoning: str, text: str) -> None:
    events = _run_stream(chunks)
    _assert_nonempty_and_ordered(events)
    assert _join(events) == (reasoning, text)


_INVARIANT_TEXTS: Final[list[str]] = [
    "<think>Rozważam pytanie.</think>Odpowiedź testowa: Jak się masz?",
    "Bez bloku myślenia.",
    "  <think>\nwiele\nlinii\n</think>\n\nTreść",
    "Tekst z <think>w środku</think>.",
]


@pytest.mark.parametrize("text", _INVARIANT_TEXTS)
def test_stream_matches_split_think_for_every_chunking(text: str) -> None:
    expected_reasoning, expected_text = split_think(text)
    for n in range(1, len(text) + 1):
        chunks = [text[i : i + n] for i in range(0, len(text), n)]
        reasoning, text_out = _join(_run_stream(chunks))
        assert reasoning.strip() == (expected_reasoning or ""), f"n={n}"
        assert text_out == expected_text, f"n={n}"
