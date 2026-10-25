"""Testy etapu słownikowego korekty diakrytyków (CONTRACT WP E5-H4b §2).

Uruchomienie pojedynczo: ``uv run pytest tests/unit/parsing/test_diacritics_dict.py -q``.
Wartości zipf zależą od danych pakietu ``wordfreq`` — testy używają słów powszechnych.
"""

import pytest

from app.parsing import diacritics_dict
from app.parsing.diacritics_dict import correct_with_wordfreq


def test_fixes_common_words() -> None:
    assert correct_with_wordfreq("<p>mezczyzni i kobiety</p>") == "<p>mężczyźni i kobiety</p>"
    assert correct_with_wordfreq("<p>zrodlo</p>") == "<p>źródło</p>"
    assert correct_with_wordfreq("<p>wyksztalcenie</p>") == "<p>wykształcenie</p>"


@pytest.mark.parametrize("text", ["<td>10,8</td>", "<p>10,8 i 3,5</p>", "<br/>"])
def test_numbers_and_tags_untouched(text: str) -> None:
    assert correct_with_wordfreq(text) == text


def test_english_word_untouched() -> None:
    assert correct_with_wordfreq("<td>total</td>") == "<td>total</td>"
    assert correct_with_wordfreq("<p>revenue profit</p>") == "<p>revenue profit</p>"


def test_keeps_case() -> None:
    assert correct_with_wordfreq("<p>OGOLEM</p>") == "<p>OGÓŁEM</p>"
    assert correct_with_wordfreq("<p>Mezczyzni</p>") == "<p>Mężczyźni</p>"


def test_existing_word_kept_unless_margin() -> None:
    # „kobiety" i „ogółem" są poprawne — zostają bez zmian.
    assert correct_with_wordfreq("<p>kobiety ogółem</p>") == "<p>kobiety ogółem</p>"
    # „mezczyzni" jest rzadsze niż „mężczyźni" o więcej niż MARGIN — zostaje podmienione.
    assert correct_with_wordfreq("<p>mezczyzni</p>") == "<p>mężczyźni</p>"


def test_index_built_once() -> None:
    diacritics_dict._build_index.cache_clear()
    correct_with_wordfreq("<p>zrodlo</p>")
    correct_with_wordfreq("<p>wyksztalcenie</p>")
    info = diacritics_dict._build_index.cache_info()
    assert info.misses == 1
    assert info.hits == 1


def test_never_removes_diacritics() -> None:
    assert correct_with_wordfreq("<p>ogółem</p>") == "<p>ogółem</p>"
    # „pokazuję" ma diakrytyk, a kandydat „pokazuje" (częstszy) nie — słowo musi zostać.
    assert correct_with_wordfreq("<p>pokazuję</p>") == "<p>pokazuję</p>"


def test_empty_and_letterless_untouched() -> None:
    assert correct_with_wordfreq("") == ""
    assert correct_with_wordfreq("<p>123 456,7</p>") == "<p>123 456,7</p>"
