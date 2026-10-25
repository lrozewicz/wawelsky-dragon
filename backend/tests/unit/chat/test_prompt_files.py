"""Pliki promptów: własny tekst (sha256 treści) i nagłówek komentarza (brief T2 → E5-7 T1)."""

import hashlib
from pathlib import Path

import app.prompts
from app.prompts import load_prompt

PROMPTS_DIR = Path(app.prompts.__file__).parent

# sha256 treści własnych promptów Wawelskiego Smoka (E5-7 T1), policzone z ``load_prompt``.
CITATION_CONTENT_SHA256 = "fef506d5b5d72cc15bd25cbea3ab0431e913a5d0ad84e376d0741708bc217c58"
FULL_QUESTION_CONTENT_SHA256 = "9a419bc4bbfbfb340ff5149b52c037d5c7acb998687ac606d77d64ae8342f76c"

ALL_PROMPTS = (
    "ask_summary",
    "citation_prompt",
    "cross_languages_sys_prompt",
    "cross_languages_user_prompt",
    "full_question_prompt",
    "meta_data",
    "meta_filter",
    "related_question",
)


def raw(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def test_citation_prompt_content_pinned() -> None:
    content = load_prompt("citation_prompt")
    assert hashlib.sha256(content.encode()).hexdigest() == CITATION_CONTENT_SHA256


def test_full_question_prompt_content_pinned() -> None:
    content = load_prompt("full_question_prompt")
    assert hashlib.sha256(content.encode()).hexdigest() == FULL_QUESTION_CONTENT_SHA256


def test_own_comment_header() -> None:
    for name in ALL_PROMPTS:
        text = raw(name)
        assert text.startswith("<!--\n"), name
        assert "Własny tekst Wawelskiego Smoka" in text, name
        assert "InfiniFlow" not in text, name
        assert "rag/prompts/" not in text, name
        assert "port 1:1" not in text, name
