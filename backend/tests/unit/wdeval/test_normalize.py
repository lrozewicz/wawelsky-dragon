"""Testy normalizacji tekstu — port z bety (test_eval_normalize.py) 1:1."""

from wdeval.normalize import contains, normalize


def test_thousands_separator_nbsp():
    assert normalize("1 264") == "1264"


def test_thousands_separator_narrow_nbsp():
    assert normalize("1 264") == "1264"


def test_thousands_separator_regular_space():
    assert normalize("512 585") == "512585"


def test_decimal_comma():
    assert normalize("82,26") == "82.26"


def test_decimal_comma_percent():
    assert normalize("11,0%") == "11.0%"


def test_percent_no_decimal():
    assert normalize("40%") == "40%"


def test_dash_variants_collapse():
    assert normalize("15–24 lata") == "15-24 lata"  # noqa: RUF001 — en dash celowo (normalizacja myslnikow)


def test_casefold_and_whitespace_collapse():
    assert normalize("  Ewa\n\tFilip  ") == "ewa filip"


def test_comma_not_numeric_kept():
    assert normalize("Warszawa, stolica") == "warszawa, stolica"


def test_digit_space_letter_kept():
    assert normalize("15 lutego") == "15 lutego"


def test_thousands_separator_with_trailing_word():
    assert normalize("5 970 publikacji") == "5970 publikacji"


def test_email_untouched():
    assert normalize("obslugaprasowa@stat.gov.pl") == "obslugaprasowa@stat.gov.pl"


def test_empty_string():
    assert normalize("") == ""


def test_multiple_thousands_separators():
    assert normalize("1 234 567") == "1234567"


def test_thousands_separator_newline():
    assert normalize("512\n585") == "512585"


def test_thousands_separator_tab():
    assert normalize("1\t264") == "1264"


def test_thousands_separator_regular_space_two_digit_groups():
    assert normalize("58 112") == "58112"


def test_contains_thousands_needle_across_newline():
    assert contains("Wielkosc ksiegozbioru (liczba woluminow): 512\n585", "512 585") is True


def test_contains_thousands_needle_across_multiple_whitespace_kinds():
    assert contains("Pamiec operacyjna (RAM) w GB 8 338 58\n112", "58112") is True


def test_thousands_separator_multiple_still_green():
    assert normalize("1 234 567") == "1234567"


def test_digit_space_letter_still_green():
    assert normalize("15 lutego") == "15 lutego"


def test_digit_space_word_still_green():
    assert normalize("5 osob") == "5 osob"


def test_comma_after_digit_at_sentence_end():
    assert normalize("w 2023, potem") == "w 2023, potem"


def test_decimal_comma_at_end_of_sentence_not_numeric():
    # przecinek po cyfrze, ale bez cyfry po drugiej stronie - nie liczbowy
    assert normalize("Rok 2023, kolejny akapit.") == "rok 2023, kolejny akapit."


def test_contains_thousands_in_sentence():
    assert contains("Oszacowano na poziomie ponad 1 264 tysięcy.", "1264") is True


def test_contains_decimal_dot_needle():
    assert contains("Wynik to 82,26 lat.", "82.26") is True


def test_contains_decimal_comma_needle_normalized():
    assert contains("Wynik to 82,26 lat.", "82,26") is True


def test_contains_no_match_different_digits():
    assert contains("Liczba 8226 nie pasuje.", "82.26") is False


def test_contains_thousands_needle_with_space():
    assert contains("W 2023 r. dostępnych 5 970 publikacji", "5 970") is True


def test_contains_percent_needle():
    assert contains("Największy udział w m.st. Warszawa (11,0%).", "11,0") is True


def test_contains_empty_needle():
    assert contains("cokolwiek", "") is True


def test_contains_dash_normalized_in_needle():
    assert contains("wiek 15-24 lata", "15–24") is True  # noqa: RUF001 — en dash celowo (normalizacja igly)


def test_normalize_number_with_fraction_and_word():
    # Przykład z briefu T1: "1 264,5 tys." -> "1264.5 tys." (separator tysiecy
    # sklejony, przecinek dziesietny zamieniony na kropke, reszta bez zmian).
    assert normalize("1 264,5 tys.") == "1264.5 tys."


# Ponizsze testy buduja znaki przez chr(codepoint) - jednoznaczny ASCII
# w zrodle - zeby zweryfikowac obsluge konkretnych punktow kodowych
# niezaleznie od tego, jakie niewidzialne znaki faktycznie trafily
# do literalow powyzej i do normalize.py.
def test_nbsp_thousands_separator_by_codepoint():
    assert normalize("1" + chr(0x00A0) + "264") == "1264"


def test_narrow_nbsp_thousands_separator_by_codepoint():
    assert normalize("1" + chr(0x202F) + "264") == "1264"


def test_thin_space_thousands_separator_by_codepoint():
    assert normalize("1" + chr(0x2009) + "264") == "1264"


def test_all_dash_variants_by_codepoint():
    dashes = [chr(cp) for cp in (0x2010, 0x2013, 0x2014, 0x2015, 0x2212)]
    text = (
        "a"
        + dashes[0]
        + "b"
        + dashes[1]
        + "c"
        + dashes[2]
        + "d"
        + dashes[3]
        + "e"
        + dashes[4]
        + "f"
    )
    assert normalize(text) == "a-b-c-d-e-f"
