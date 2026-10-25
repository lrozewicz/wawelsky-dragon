"""Testy parsowania werdyktu sedziego i promptow — port z bety
(test_eval_judge_parse.py) 1:1."""

from __future__ import annotations

import pytest

from wdeval.judge import Verdict, parse_verdict
from wdeval.judge_prompt import (
    JUDGE_PROMPT_VERSION,
    VERDICT_KINDS,
    build_judge_messages,
)


class TestParseVerdict:
    def test_plain_tak(self):
        assert parse_verdict("grounded", "TAK").value is True

    def test_think_closed_before_tak(self):
        raw = "<think>Sprawdzam kontekst...</think>\nTAK"
        assert parse_verdict("grounded", raw).value is True

    def test_think_closed_before_nie(self):
        raw = "<think>Liczba 82,26 jest w źródle 2.</think>NIE"
        assert parse_verdict("grounded", raw).value is False

    def test_empty_ok_lowercase_nie(self):
        assert parse_verdict("empty_ok", "nie").value is False

    def test_empty_ok_mixed_case_tak(self):
        assert parse_verdict("empty_ok", "Tak").value is True

    def test_citation_ok_na_literal(self):
        assert parse_verdict("citation_ok", "N/A").value is None

    def test_citation_ok_empty_string(self):
        assert parse_verdict("citation_ok", "").value is None

    def test_no_word_boundary_not_matched(self):
        assert parse_verdict("grounded", "NIEUGRUNTOWANA").value is None

    def test_nie_embedded_in_sentence(self):
        raw = "Odpowiedź: NIE, bo kontekst nie zawiera liczby."
        assert parse_verdict("grounded", raw).value is False

    def test_unclosed_think_eats_everything(self):
        raw = "<think>rozumowanie bez zamkniecia TAK"
        assert parse_verdict("grounded", raw).value is None

    def test_last_occurrence_wins(self):
        # Reguła zmieniona po znalezisku testera: bierzemy OSTATNIE samodzielne
        # wystąpienie, nie pierwsze (prompt żąda jednej odpowiedzi na końcu).
        raw = "<think>a</think>TAK<think>b</think>NIE"
        assert parse_verdict("grounded", raw).value is False

    def test_orphan_closing_tag_from_chat_template(self):
        # Szablon czatu dokleja "<think>\n" do promptu — model zaczyna generację
        # wewnątrz bloku i emituje tylko tag zamykający. Wszystko przed nim to
        # rozumowanie i ma zniknąć.
        raw = "kontekst nie zawiera liczby, wiec NIE... </think>\nTAK"
        assert parse_verdict("grounded", raw).value is True

    def test_verdict_word_inside_prose_before_final_answer(self):
        raw = "Wszystkie fakty nie budza watpliwosci, wiec TAK"
        assert parse_verdict("grounded", raw).value is True

    def test_nested_think_blocks(self):
        raw = "<think>a<think>b</think>NIE, jednak sprawdzam</think>TAK"
        assert parse_verdict("grounded", raw).value is True

    def test_think_tag_with_space(self):
        raw = "<think >rozumowanie NIE</think> TAK"
        assert parse_verdict("grounded", raw).value is True

    def test_think_tag_uppercase(self):
        raw = "<THINK>x</THINK>NIE"
        assert parse_verdict("grounded", raw).value is False

    def test_prose_without_final_verdict_word_is_predictable_not_none(self):
        # Reguła jest przewidywalna, nie zgaduje intencji: skoro "Nie" jest
        # jedynym (więc też ostatnim) samodzielnym TAK/NIE w tekście, to jest
        # werdykt — mimo że zdanie jest w istocie stwierdzeniem "nie da się
        # ocenić", a nie odpowiedzią na pytanie sędziego. Celowe.
        assert parse_verdict("grounded", "Nie da sie ocenic.").value is False

    def test_no_verdict_word_anywhere_is_none(self):
        raw = "brak jakiegokolwiek werdyktu w tym zdaniu"
        assert parse_verdict("grounded", raw).value is None

    def test_raw_preserved_plain(self):
        assert parse_verdict("grounded", "TAK").raw == "TAK"

    def test_raw_preserved_with_think(self):
        raw = "<think>x</think>TAK"
        assert parse_verdict("grounded", raw).raw == raw

    def test_unknown_kind_raises(self):
        with pytest.raises(ValueError):
            parse_verdict("cokolwiek", "TAK")

    def test_returns_verdict_dataclass(self):
        result = parse_verdict("grounded", "TAK")
        assert isinstance(result, Verdict)
        assert result.kind == "grounded"


class TestBuildJudgeMessages:
    def test_grounded_returns_two_messages_with_roles(self):
        payload = {"question": "Q?", "answer": "A.", "context": "C."}
        messages = build_judge_messages("grounded", payload)
        assert len(messages) == 2  # noqa: PLR2004 — system + user
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_grounded_payload_values_present_in_content(self):
        payload = {
            "question": "Jaka jest stolica?",
            "answer": "Warszawa.",
            "context": "[Źródło 1] Warszawa to stolica Polski.",
        }
        messages = build_judge_messages("grounded", payload)
        user_content = messages[1]["content"]
        assert payload["question"] in user_content
        assert payload["answer"] in user_content
        assert payload["context"] in user_content

    def test_empty_ok_payload_values_present(self):
        payload = {"question": "Jaka jest stolica Marsa?", "answer": "Nie znam odpowiedzi."}
        messages = build_judge_messages("empty_ok", payload)
        user_content = messages[1]["content"]
        assert payload["question"] in user_content
        assert payload["answer"] in user_content

    def test_empty_ok_missing_context_key_not_required(self):
        # empty_ok nie wymaga 'context' — nie powinno rzucić KeyError.
        payload = {"question": "Q?", "answer": "A."}
        messages = build_judge_messages("empty_ok", payload)
        assert len(messages) == 2  # noqa: PLR2004 — system + user

    def test_citation_ok_payload_values_present(self):
        payload = {
            "question": "Q?",
            "answer": "Fakt [1].",
            "context": "[Źródło 1] Treść faktu.",
        }
        messages = build_judge_messages("citation_ok", payload)
        user_content = messages[1]["content"]
        assert payload["question"] in user_content
        assert payload["answer"] in user_content
        assert payload["context"] in user_content

    def test_unknown_kind_raises(self):
        with pytest.raises(ValueError):
            build_judge_messages("nieznany", {"question": "Q"})

    def test_missing_required_key_raises_keyerror(self):
        with pytest.raises(KeyError):
            build_judge_messages("grounded", {"question": "Q", "answer": "A"})

    @pytest.mark.parametrize("kind", VERDICT_KINDS)
    def test_all_verdict_kinds_buildable(self, kind):
        payload = {"question": "Q?", "answer": "A.", "context": "C."}
        messages = build_judge_messages(kind, payload)
        assert len(messages) == 2  # noqa: PLR2004 — system + user

    def test_judge_prompt_version_is_one(self):
        assert JUDGE_PROMPT_VERSION == 1

    def test_verdict_kinds_content(self):
        assert VERDICT_KINDS == ("grounded", "empty_ok", "citation_ok")
