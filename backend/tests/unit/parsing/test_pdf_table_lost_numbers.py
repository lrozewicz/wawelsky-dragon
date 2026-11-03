"""Tabela pdfplumbera, która gubi liczby, nie może zastąpić linii tekstu strony."""

from app.parsing.converters.pdf_layout import lost_numbers


def test_lost_numbers_counts_values_missing_from_cells() -> None:
    rows = [["O G Ó Ł E M ....", "4,00", "3,57", None, None, None, "T O T A L"]]
    words = ["O", "G", "Ó", "Ł", "E", "M", "....", "4,00", "3,57", "3,86", "3,72", "4,04"]
    missing_values = 3
    assert lost_numbers(rows, words) == missing_values


def test_lost_numbers_ignores_text_and_complete_cells() -> None:
    rows = [["Razem", "7679 9456", "9913"]]
    assert lost_numbers(rows, ["Razem", "tekst", "7679", "9456", "9913"]) == 0


def test_lost_numbers_counts_repeated_values() -> None:
    assert lost_numbers([["0,52", None]], ["0,52", "0,52"]) == 1
