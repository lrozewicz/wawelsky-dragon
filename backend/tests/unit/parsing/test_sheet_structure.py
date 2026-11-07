"""Arkusze GUS: tytuł, nagłówek wielopoziomowy i scalone opisy po lewej."""

from app.parsing.blocks import html_to_blocks
from app.parsing.converters.sheets import sheet_html


def _blocks(rows):
    return html_to_blocks(f'<section data-sheet="T">{sheet_html(rows)}</section>')


ROWS = [
    ["TABL. 117. TRWANIE ŻYCIA", "", "", "", ""],
    ["Powrót do spisu tablic", "", "", "", ""],
    ["WYSZCZEGÓLNIENIE", "", "Mężczyźni", "", "Kobiety"],
    ["", "", "wiek", "", ""],
    ["", "", "0", "15", "0"],
    ["O G Ó Ł E M", "1970", "66.62", "54.81", "73.33"],
    ["", "1980", "66.01", "53.12", "74.44"],
]


def test_title_becomes_heading_without_navigation() -> None:
    heading = _blocks(ROWS)[0]
    assert heading.text == "TABL. 117. TRWANIE ŻYCIA"


def test_header_levels_are_flattened() -> None:
    table = _blocks(ROWS)[1].table
    assert table.header[0] == "WYSZCZEGÓLNIENIE"
    assert table.header[2] == "Mężczyźni / wiek / 0"
    assert table.header[3] == "Mężczyźni / wiek / 15"
    # „wiek” stoi tylko pod „Mężczyźni”: puste komórki należą do grupy z lewej, ale nie
    # przechodzą przez granicę grupy wyższego poziomu („Kobiety”).
    assert table.header[4] == "Kobiety / 0"


def test_merged_labels_are_repeated_on_each_row() -> None:
    table = _blocks(ROWS)[1].table
    assert table.rows[0][:3] == ("OGÓŁEM", "1970", "66.62")
    assert table.rows[1][:3] == ("OGÓŁEM", "1980", "66.01")


def test_text_sheet_stays_plain() -> None:
    rows = [["Spis tablic", ""], ["Tabl. 1", "Ludność"]]
    assert _blocks(rows)[0].table.rows[0][0] == "Tabl. 1"
