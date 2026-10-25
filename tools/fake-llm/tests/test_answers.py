"""Testy jednostkowe treści odpowiedzi: message_text, answer_content, usage, fixtures (C5)."""

import base64
import hashlib
from pathlib import Path
from typing import Any

import pytest

from fake_llm import answers
from fake_llm.answers import ChatMessage, answer_content, message_text, usage
from fake_llm.tokens import tokenize

CHAT_MODEL = "fake-chat"
THINK_MODEL = "fake-chat-think"
VISION_MODEL = "fake-vision"
TEXT_LIMIT = 80
LONG_LENGTH = 2000
PROMPT_TOKENS_UMOWA_NAJMU = 2
FIXTURE_RED_TEXT = "czerwony kwadrat"
SYS = "Kontekst:\nID: 2\nDrugi fragment.\nID: 1\n  Pierwszy fragment o umowie najmu.  \n"
RED_BYTES = (Path(__file__).resolve().parent / "data" / "red.png").read_bytes()
RED_SHA8 = hashlib.sha256(RED_BYTES).hexdigest()[:8]
UNKNOWN_BYTES = b"abc"
UNKNOWN_SHA8 = hashlib.sha256(UNKNOWN_BYTES).hexdigest()[:8]


def _msg(role: str, content: str | list[dict[str, Any]] | None) -> ChatMessage:
    return ChatMessage(role=role, content=content)


def _data_url(bytes_: bytes) -> str:
    return "data:application/octet-stream;base64," + base64.b64encode(bytes_).decode("ascii")


def test_message_text_string() -> None:
    assert message_text(_msg("user", "ala")) == "ala"


def test_message_text_none() -> None:
    assert message_text(_msg("system", None)) == ""


def test_message_text_list_parts() -> None:
    parts = [
        {"type": "text", "text": "ala"},
        {"type": "text", "text": "kot"},
    ]
    assert message_text(_msg("user", parts)) == "ala\nkot"


def test_message_text_skips_non_text_parts() -> None:
    parts = [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,xxx"}},
        {"type": "text", "text": "x"},
    ]
    assert message_text(_msg("user", parts)) == "x"


def test_answer_content_plain() -> None:
    assert answer_content(CHAT_MODEL, [_msg("user", "Jaka jest stolica?")], None) == (
        "Odpowiedź testowa: Jaka jest stolica?"
    )


def test_answer_content_truncates_user_text() -> None:
    content = answer_content(CHAT_MODEL, [_msg("user", "a" * 100)], None)
    assert content == "Odpowiedź testowa: " + "a" * TEXT_LIMIT


def test_answer_content_no_user_message() -> None:
    content = answer_content(CHAT_MODEL, [_msg("system", "pouczenie")], None)
    assert content == "Odpowiedź testowa: "


def test_answer_content_knowledge_block() -> None:
    content = answer_content(CHAT_MODEL, [_msg("system", SYS), _msg("user", "pytanie")], None)
    assert content == "Na podstawie źródeł: Pierwszy fragment o umowie najmu. [ID:1]"


def test_answer_content_knowledge_lowest_id_across_messages() -> None:
    messages = [_msg("system", "ID: 5\npiąty"), _msg("system", "ID: 3\ntrzeci")]
    assert answer_content(CHAT_MODEL, messages, None).endswith(" trzeci [ID:3]")


def test_answer_content_knowledge_tie_first_occurrence() -> None:
    system = "ID: 7\npierwszy\nID: 7\ndrugi"
    content = answer_content(CHAT_MODEL, [_msg("system", system), _msg("user", "p")], None)
    assert content == "Na podstawie źródeł: pierwszy [ID:7]"


def test_answer_content_knowledge_block_without_newline() -> None:
    content = answer_content(CHAT_MODEL, [_msg("system", "ID: 4"), _msg("user", "p")], None)
    assert content == "Na podstawie źródeł:  [ID:4]"


@pytest.mark.parametrize(
    "tail",
    ["End of knowledge base.", "      The above is the knowledge base."],
)
def test_answer_content_knowledge_ignores_prompt_tail(tail: str) -> None:
    """Ostatni blok kończy się przed ogonem szablonu — niezależnie od jego brzmienia (E5-7 T4)."""
    system = (
        "Kontekst:\n      \n------\n"
        "\nID: 0\n├── Title: wawel.txt\n└── Content:\n"
        "Wawelski smok mieszkał w jamie pod Wawelem.\n" + tail
    )
    content = answer_content(CHAT_MODEL, [_msg("system", system), _msg("user", "p")], None)
    assert content == (
        "Na podstawie źródeł: ├── Title: wawel.txt\n└── Content:\n"
        "Wawelski smok mieszkał w jamie pod Wawelem. [ID:0]"
    )


def test_answer_content_knowledge_snippet_stripped_and_truncated() -> None:
    system = "ID: 0\n" + "x" * 100 + "  "
    content = answer_content(CHAT_MODEL, [_msg("system", system), _msg("user", "p")], None)
    assert content == "Na podstawie źródeł: " + "x" * TEXT_LIMIT + " [ID:0]"


def test_answer_content_knowledge_with_citation_prompt() -> None:
    """Ogon sklejony z promptem cytowań i jego przykładowe `ID:` nie wchodzą do próbki (E5-7 T4)."""
    system = (
        "Knowledge base:\n      \n------\n"
        "\nID: 0\n├── Title: wawel.txt\n└── Content:\n"
        "Wawelski smok mieszkał w jamie pod Wawelem.\n"
        "End of knowledge base.Do tekstu wejściowego dodaj cytowania. Format opisano poniżej.\n"
        "\n# Zasady cytowania\n\n<context>\nID: 45\n└── Content: W III kwartale 2024 rynek urósł."
        "\n</context>\n"
    )
    content = answer_content(CHAT_MODEL, [_msg("system", system), _msg("user", "p")], None)
    assert content == (
        "Na podstawie źródeł: ├── Title: wawel.txt\n└── Content:\n"
        "Wawelski smok mieszkał w jamie pod Wawelem. [ID:0]"
    )


def test_answer_content_knowledge_last_block_of_many_keeps_content() -> None:
    """Blok nieostatni (po nim separator `------`) nie traci ostatniej linii treści."""
    system = (
        "Knowledge base:\n      \n------\n"
        "\nID: 0\n├── Title: a.txt\n└── Content:\nAla ma kota.\n"
        "\n------\n"
        "\nID: 1\n├── Title: b.txt\n└── Content:\nKot ma Alę.\n"
        "End of knowledge base."
    )
    content = answer_content(CHAT_MODEL, [_msg("system", system), _msg("user", "p")], None)
    assert content == "Na podstawie źródeł: ├── Title: a.txt\n└── Content:\nAla ma kota. [ID:0]"


def test_answer_content_knowledge_last_block_drops_prompt_tail() -> None:
    """Ostatni blok sekcji wiedzy (najniższe ID) traci doklejony ogon szablonu."""
    system = (
        "Knowledge base:\n      \n------\n"
        "\nID: 5\n├── Title: a.txt\n└── Content:\nAla ma kota.\n"
        "\n------\n"
        "\nID: 3\n├── Title: b.txt\n└── Content:\nKot ma Alę.\n"
        "End of knowledge base."
    )
    content = answer_content(CHAT_MODEL, [_msg("system", system), _msg("user", "p")], None)
    assert content == "Na podstawie źródeł: ├── Title: b.txt\n└── Content:\nKot ma Alę. [ID:3]"


def test_answer_content_knowledge_content_starting_with_blank_line() -> None:
    """Pusta linia po `└── Content:` należy do treści (złota kontraktowe), nie kończy bloku."""
    system = (
        "Knowledge base:\n      \n------\n"
        "\nID: 0\n├── Title: a.txt\n└── Content:\n"
        "\nAla ma kota.\nEnd of knowledge base."
    )
    content = answer_content(CHAT_MODEL, [_msg("system", system), _msg("user", "p")], None)
    assert content == "Na podstawie źródeł: ├── Title: a.txt\n└── Content:\n\nAla ma kota. [ID:0]"


def test_answer_content_think() -> None:
    assert answer_content(THINK_MODEL, [_msg("user", "x")], None) == (
        "<think>Rozważam pytanie.</think>Odpowiedź testowa: x"
    )


def test_answer_content_think_with_knowledge_block() -> None:
    content = answer_content(THINK_MODEL, [_msg("system", SYS), _msg("user", "p")], None)
    assert content == (
        "<think>Rozważam pytanie.</think>Na podstawie źródeł: "
        "Pierwszy fragment o umowie najmu. [ID:1]"
    )


def test_answer_content_scenario_empty() -> None:
    assert answer_content(CHAT_MODEL, [_msg("user", "x")], "empty") == ""


def test_answer_content_scenario_empty_think() -> None:
    assert answer_content(THINK_MODEL, [_msg("user", "x")], "empty") == ""


def test_answer_content_scenario_no_citations() -> None:
    content = answer_content(CHAT_MODEL, [_msg("system", SYS), _msg("user", "p")], "no_citations")
    assert content == "Na podstawie źródeł: Pierwszy fragment o umowie najmu."
    assert "[ID:" not in content


def test_answer_content_scenario_long() -> None:
    content = answer_content(CHAT_MODEL, [_msg("user", "x")], "long")
    assert len(content) == LONG_LENGTH
    assert content.startswith("Odpowiedź testowa: x")


def test_answer_content_scenario_unknown_is_passthrough() -> None:
    assert answer_content(CHAT_MODEL, [_msg("user", "x")], "nieznany") == "Odpowiedź testowa: x"


def test_answer_content_vision_known_image() -> None:
    parts = [
        {"type": "text", "text": "co to?"},
        {"type": "image_url", "image_url": {"url": _data_url(RED_BYTES)}},
    ]
    content = answer_content(VISION_MODEL, [_msg("user", parts)], None)
    assert content == f"<p>OCR:{RED_SHA8}</p><p>{FIXTURE_RED_TEXT}</p>"


def test_answer_content_vision_unknown_image() -> None:
    parts = [{"type": "image_url", "image_url": {"url": _data_url(UNKNOWN_BYTES)}}]
    assert answer_content(VISION_MODEL, [_msg("user", parts)], None) == f"<p>OCR:{UNKNOWN_SHA8}</p>"


def test_answer_content_vision_url_encoded() -> None:
    parts = [{"type": "image_url", "image_url": {"url": "data:text/plain,hello%20world"}}]
    sha8 = hashlib.sha256(b"hello world").hexdigest()[:8]
    assert answer_content(VISION_MODEL, [_msg("user", parts)], None) == f"<p>OCR:{sha8}</p>"


def test_answer_content_vision_https_ignored() -> None:
    parts = [
        {"type": "text", "text": "x"},
        {"type": "image_url", "image_url": {"url": "https://example.com/obraz.png"}},
    ]
    assert answer_content(VISION_MODEL, [_msg("user", parts)], None) == "Odpowiedź testowa: x"


def test_answer_content_vision_images_across_messages() -> None:
    first = [{"type": "image_url", "image_url": {"url": _data_url(RED_BYTES)}}]
    second = [{"type": "image_url", "image_url": {"url": _data_url(UNKNOWN_BYTES)}}]
    content = answer_content(VISION_MODEL, [_msg("user", first), _msg("user", second)], None)
    assert content == (f"<p>OCR:{RED_SHA8}</p><p>{FIXTURE_RED_TEXT}</p><p>OCR:{UNKNOWN_SHA8}</p>")


def test_vision_fixtures_real_file() -> None:
    answers._vision_fixtures.cache_clear()
    assert answers._vision_fixtures() == {RED_SHA8: FIXTURE_RED_TEXT}
    answers._vision_fixtures.cache_clear()


def test_vision_fixtures_missing_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(answers, "_FIXTURES_PATH", Path("/nie/ma/vision.json"))
    answers._vision_fixtures.cache_clear()
    assert answers._vision_fixtures() == {}
    monkeypatch.undo()
    answers._vision_fixtures.cache_clear()


def test_usage_counts() -> None:
    content = answer_content(CHAT_MODEL, [_msg("user", "umowa najmu")], None)
    counters = usage([_msg("user", "umowa najmu")], content)
    assert counters["prompt_tokens"] == PROMPT_TOKENS_UMOWA_NAJMU
    assert counters["completion_tokens"] == len(tokenize(content))
    assert counters["total_tokens"] == counters["prompt_tokens"] + counters["completion_tokens"]
