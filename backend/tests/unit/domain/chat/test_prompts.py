"""Testy promptów czatu: bloki wiedzy, system, wiadomości, fit_messages, tekst P (brief T2)."""

import pytest

from app.core.errors import ValidationFailed
from app.domain.chat import prompts
from app.domain.chat.config import DEFAULT_PROMPT_CONFIG
from app.domain.chat.prompts import (
    CITATION_SUFFIX,
    PROMPT_MAX_BYTES,
    Timings,
    build_kb_blocks,
    build_messages,
    build_prompt_text,
    build_system,
    citation_prompt,
    clean_history_content,
    conversation_text,
    empty_prompt_text,
    fit_messages,
    render_full_question,
)
from app.domain.retrieval.types import RetrievedChunk
from app.llm.tokens import count_tokens, truncate_tokens
from app.prompts import load_prompt


def tok(s: str) -> int:
    """Liczba tokenów liczona rozbiciem na słowa (brief T2, chyba że napisano inaczej)."""
    return len(s.split())


BIG = " ".join(["t"] * 2000)  # 2000 „tokenów”


def chunk(
    content: str = "Ala ma kota",
    *,
    content_llm: str = "",
    document_name: str = "a.txt",
    url: str | None = None,
    metadata: dict[str, object] | None = None,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="c1",
        content=content,
        content_llm=content_llm,
        content_terms="",
        document_id="d1",
        document_name=document_name,
        dataset_id="k1",
        image_id="",
        important_keywords=[],
        questions=[],
        tag_kwd=[],
        positions=[],
        similarity=0.9,
        vector_similarity=0.8,
        term_similarity=0.7,
        highlight=None,
        doc_type="",
        url=url,
        document_metadata=metadata,
    )


# --- build_kb_blocks -------------------------------------------------------


def test_build_kb_blocks_single() -> None:
    blocks = build_kb_blocks([chunk(metadata={"autor": "Jan\n\nNowak"})], 100, count_tokens=tok)
    assert blocks == ["\nID: 0\n├── Title: a.txt\n├── autor: Jan Nowak\n└── Content:\nAla ma kota"]


def test_build_kb_blocks_budget_break() -> None:
    sixty = " ".join(["t"] * 60)
    blocks = build_kb_blocks([chunk(sixty), chunk(sixty)], 100, count_tokens=tok)
    assert len(blocks) == 1


def test_build_kb_blocks_empty_skipped_numbering_without_holes() -> None:
    blocks = build_kb_blocks([chunk("a b"), chunk(""), chunk("c d")], 100, count_tokens=tok)
    assert [b.splitlines()[1] for b in blocks] == ["ID: 0", "ID: 1"]


def test_build_kb_blocks_prefers_content_llm() -> None:
    blocks = build_kb_blocks([chunk(content_llm="<b>LLM</b>")], 100, count_tokens=tok)
    assert blocks == ["\nID: 0\n├── Title: a.txt\n└── Content:\nLLM"]


def test_build_kb_blocks_strips_html_from_content_llm() -> None:
    """CONTRACT E4-7c: blok kończy się "Content:\\nx" (HTML znika, atrybuty też)."""
    blocks = build_kb_blocks([chunk(content_llm='<p data-bbox="1">x</p>')], 100, count_tokens=tok)
    assert blocks == ["\nID: 0\n├── Title: a.txt\n└── Content:\nx"]


def test_build_kb_blocks_budget_counts_converted_text() -> None:
    """Budżet tokenów liczony z tekstu po konwersji, nie z HTML (CONTRACT, Prompt/budżet)."""
    html_chunk = chunk(content_llm='<p data-bbox="1">x</p>')
    blocks = build_kb_blocks([html_chunk, html_chunk], 2, count_tokens=len)
    assert len(blocks) == 1
    assert blocks[0].endswith("Content:\nx")


def test_build_kb_blocks_url_and_metadata_types() -> None:
    blocks = build_kb_blocks(
        [chunk(url="https://x", metadata={"n": 3, "puste": "", "brak": None})],
        100,
        count_tokens=tok,
    )
    assert blocks == [
        "\nID: 0\n├── Title: a.txt\n├── URL: https://x\n├── n: 3\n└── Content:\nAla ma kota"
    ]


# --- build_system ----------------------------------------------------------


def test_build_system_knowledge_date() -> None:
    out = build_system(
        "Wiedza:{knowledge} Data:{date} X:{nieznana}",
        ["\nID: 0\nA"],
        [{"key": "knowledge", "optional": False}, {"key": "date", "optional": True}],
        {"date": "2026-09-27 10:00:00"},
    )
    assert out == "Wiedza:\n------\n\nID: 0\nA Data:2026-09-27 10:00:00 X:"


def test_build_system_appends_knowledge() -> None:
    out = build_system("Bez miejsca", ["\nID: 0\nA"], [], {})
    assert out == "Bez miejsca\n------\n\nID: 0\nA"


def test_build_system_optional_missing_becomes_space() -> None:
    out = build_system("S {date}", [], [{"key": "date", "optional": True}], {})
    assert out == "S  "


def test_build_system_missing_required() -> None:
    with pytest.raises(ValidationFailed) as exc:
        build_system("S", [], [{"key": "lang", "optional": False}], {})
    assert exc.value.message == "Miss parameter: lang"


# --- notatka „kilka miar” (brief T6) ---------------------------------------


def test_multi_measure_note_default_off() -> None:
    out = build_system(
        "S {knowledge}",
        ["\nID: 0\nA"],
        [{"key": "knowledge", "optional": False}],
        {},
    )
    assert out == "S \n------\n\nID: 0\nA"


def test_multi_measure_note_prepended_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prompts, "MULTI_MEASURE_NOTE_ENABLED", True)
    out = build_system(
        "S {knowledge}",
        ["\nID: 0\nA"],
        [{"key": "knowledge", "optional": False}],
        {},
    )
    assert out.startswith("S \n------\n" + prompts.MULTI_MEASURE_NOTE)
    assert out.index(prompts.MULTI_MEASURE_NOTE) < out.index("\nID: 0\nA")


def test_multi_measure_note_appended_when_template_lacks_knowledge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(prompts, "MULTI_MEASURE_NOTE_ENABLED", True)
    out = build_system("Bez miejsca", ["\nID: 0\nA"], [], {})
    assert out.endswith(prompts.MULTI_MEASURE_NOTE + "\n\n------\n\n\nID: 0\nA")
    assert out.index(prompts.MULTI_MEASURE_NOTE) < out.index("\nID: 0\nA")


def test_multi_measure_note_absent_without_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prompts, "MULTI_MEASURE_NOTE_ENABLED", True)
    out = build_system("X {knowledge}", [], [{"key": "knowledge", "optional": False}], {})
    assert "Note:" not in out


def test_default_prompt_config_unchanged() -> None:
    system = DEFAULT_PROMPT_CONFIG["system"]
    assert "Note:" not in system
    assert "several measures" not in system


# --- wiadomości i historia -------------------------------------------------


def test_build_messages() -> None:
    out = build_messages(
        "SYS", [{"role": "system", "content": "x"}, {"role": "user", "content": "a##1$$"}]
    )
    assert out == [{"role": "system", "content": "SYS"}, {"role": "user", "content": "a"}]


def test_clean_history_content() -> None:
    assert clean_history_content("<think>x</think>Tak [ID:0] i nie [ID:12].") == "Tak i nie."


def test_conversation_text() -> None:
    out = conversation_text(
        [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
        ]
    )
    assert out == "USER: a\nASSISTANT: b"


# --- fit_messages (prawdziwe count_tokens/truncate_tokens) -----------------


def real_fit(msgs: list[dict[str, str]], limit: int) -> tuple[int, list[dict[str, str]]]:
    return fit_messages(msgs, limit, count_tokens=count_tokens, truncate_tokens=truncate_tokens)


def test_fit_messages_fits() -> None:
    msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "pytanie"}]
    total, out = real_fit(msgs, 1000)
    assert total == count_tokens("sys") + count_tokens("pytanie")
    assert out == msgs
    assert msgs == [{"role": "system", "content": "sys"}, {"role": "user", "content": "pytanie"}]


def test_fit_messages_drops_middle() -> None:
    middle = " ".join(["t"] * 50)
    msgs = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": middle},
        {"role": "user", "content": middle},
        {"role": "user", "content": "ostatnie pytanie"},
    ]
    limit = count_tokens("s") + count_tokens("ostatnie pytanie") + 10
    total, out = real_fit(msgs, limit)
    assert [m["role"] for m in out] == ["system", "user"]
    assert out[-1]["content"] == "ostatnie pytanie"
    assert total == limit - 10
    assert len(msgs) == 4  # noqa: PLR2004 — wejście nie mutowane


def test_fit_messages_system_dominates() -> None:
    limit = 1000
    msgs = [{"role": "system", "content": BIG}, {"role": "user", "content": "pyt"}]
    total, out = real_fit(msgs, limit)
    assert total == limit
    assert out[-1]["content"] == "pyt"
    assert count_tokens(out[0]["content"]) == limit - count_tokens("pyt")
    assert msgs[0]["content"] == BIG


def test_fit_messages_user_dominates() -> None:
    limit = 1000
    msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": BIG}]
    total, out = real_fit(msgs, limit)
    assert total == limit
    assert out[0]["content"] == "sys"
    assert count_tokens(out[-1]["content"]) == limit - count_tokens("sys")
    assert msgs[-1]["content"] == BIG


def test_fit_messages_total_nonpositive() -> None:
    msgs = [{"role": "system", "content": ""}, {"role": "user", "content": ""}]
    total, out = real_fit(msgs, 0)
    assert total == 0
    assert out == msgs


def test_fit_messages_single() -> None:
    # do gałęzi przycięcia dochodzi tylko pojedynczy system
    msgs = [{"role": "system", "content": BIG}]
    total, out = real_fit(msgs, 500)
    assert total == 500  # noqa: PLR2004 — limit testowy
    assert count_tokens(out[0]["content"]) == 500  # noqa: PLR2004 — limit testowy
    assert msgs[0]["content"] == BIG


def test_fit_messages_lone_user_overflow_dropped() -> None:
    # upstream GEN l. 93-99: msg_ trzyma tylko system; samotny user → pusta lista i 0
    msgs = [{"role": "user", "content": BIG}]
    total, out = real_fit(msgs, 500)
    assert total == 0
    assert out == []


# --- tekst P ---------------------------------------------------------------


def test_build_prompt_text_exact() -> None:
    out = build_prompt_text("SYS", ["pyt"], Timings(10.0, 1.0, 2.0, 3.0, 4.0, 500.0), 50)
    assert out == (
        "SYS  \n  \n### Query:  \npyt  \n  \n## Time elapsed:  \n"
        "  - Total: 10.0ms  \n"
        "  - Check LLM: 1.0ms  \n"
        "  - Check Langfuse tracer: 0.0ms  \n"
        "  - Bind models: 2.0ms  \n"
        "  - Query refinement(LLM): 3.0ms  \n"
        "  - Retrieval: 4.0ms  \n"
        "  - Generate answer: 500.0ms  \n"
        "  \n## Token usage:  \n"
        "  - Generated tokens(approximately): 50  \n"
        "  - Token speed: 100/s"
    )


def test_build_prompt_text_zero_speed() -> None:
    out = build_prompt_text("S", ["q"], Timings(1.0, 0.0, 0.0, 0.0, 0.0, 0.0), 10)
    assert out.endswith("Token speed: 0/s")


def test_build_prompt_text_truncated_utf8() -> None:
    out = build_prompt_text("ż" * 70000, ["q"], Timings(1.0, 0.0, 0.0, 0.0, 0.0, 0.0), 1)
    assert len(out.encode("utf-8")) <= PROMPT_MAX_BYTES
    out.encode("utf-8").decode("utf-8")


def test_empty_prompt_text() -> None:
    assert empty_prompt_text(["a", "b"]) == "\n\n### Query:\na b"


def test_empty_prompt_text_trims_question() -> None:
    """Wejście: pytanie po refine z końcową spacją → wyjście: pole prompt bez tej spacji."""
    assert empty_prompt_text(["Odpowiedź testowa: Output: "]) == (
        "\n\n### Query:\nOdpowiedź testowa: Output:"
    )


def test_build_prompt_text_trims_question() -> None:
    """Wejście: pytanie z końcową spacją → wyjście: zapytanie przycięte przed sekcją czasów."""
    out = build_prompt_text("SYS", ["pyt? "], Timings(1.0, 0.0, 0.0, 0.0, 0.0, 0.0), 10)
    assert "### Query:  \npyt?  \n  \n## Time elapsed:" in out


# --- szablony z app.prompts ------------------------------------------------


def test_render_full_question_language_none() -> None:
    out = render_full_question(
        load_prompt("full_question_prompt"),
        today="2026-09-27",
        yesterday="2026-09-26",
        tomorrow="2026-09-28",
        conversation="USER: a\nASSISTANT: b\nUSER: c",
        language=None,
    )
    assert "- Text generated MUST be in the same language as the original user's question.\n" in out
    assert "{%" not in out
    assert "{{" not in out
    assert "MUST be in None" not in out


def test_render_full_question_language_polish() -> None:
    out = render_full_question(
        load_prompt("full_question_prompt"),
        today="2026-09-27",
        yesterday="2026-09-26",
        tomorrow="2026-09-28",
        conversation="USER: c",
        language="Polish",
    )
    assert "- Text generated MUST be in Polish.\n" in out


def test_render_full_question_conversation_substituted_last() -> None:
    out = render_full_question(
        load_prompt("full_question_prompt"),
        today="T",
        yesterday="Y",
        tomorrow="M",
        conversation="{{ today }}",
        language=None,
    )
    assert out.endswith("{{ today }}\n")


def test_citation_prompt_ends_with_suffix() -> None:
    full = citation_prompt(load_prompt("citation_prompt"))
    assert full.endswith(CITATION_SUFFIX)
    assert "\n\n\nIMPORTANT" not in full


def test_citation_prompt_strips_one_trailing_newline() -> None:
    assert citation_prompt("A\n") == "A" + CITATION_SUFFIX
    assert citation_prompt("A") == "A" + CITATION_SUFFIX
