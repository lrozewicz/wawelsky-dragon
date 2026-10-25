"""Testy highlight (CONTRACT WP E1-7 M4)."""

from app.domain.retrieval.highlight import highlight


def test_highlight_wraps_matches_case_and_diacritics_insensitive() -> None:
    result = highlight("Zażółć gęślą jaźń", ["gesla", "JAZN"])
    assert result == "Zażółć <em>gęślą</em> <em>jaźń</em>"


def test_highlight_cuts_window_around_first_match() -> None:
    text = "x" * 300 + " Tatry " + "y" * 300
    result = highlight(text, ["tatry"])
    # Okno 120 znaków przed "Tatry" (czyli 119 x-ów i spacja) i 120 po (spacja i 119 y-ów).
    assert result[:120] == "x" * 119 + " "
    assert result[-120:] == " " + "y" * 119
    assert "<em>Tatry</em>" in result
    assert len(result) == 120 + len("<em>Tatry</em>") + 120


def test_highlight_no_match_returns_text() -> None:
    assert highlight("bez trafień", ["xyz"]) == "bez trafień"


def test_highlight_requires_whole_word_match() -> None:
    assert highlight("Tatrzański", ["tatr"]) == "Tatrzański"


def test_highlight_empty_term_is_ignored() -> None:
    assert highlight("gęślą", [""]) == "gęślą"


def test_highlight_match_at_text_start_clamps_window() -> None:
    assert highlight("Łódź " + "y" * 300, ["lódź"]).startswith("<em>Łódź</em>")


def test_highlight_second_match_outside_window_not_wrapped() -> None:
    text = "aaa Tatry " + "b" * 120 + " Tatry ccc"
    result = highlight(text, ["tatry"])
    assert result.count("<em>") == 1
    assert result.startswith("aaa <em>Tatry</em>")
