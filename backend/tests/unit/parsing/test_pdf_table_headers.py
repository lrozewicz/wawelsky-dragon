"""Tabele PDF: nagłówek wielopoziomowy i opisy rozbite na kilka wierszy siatki (GUS)."""

from types import SimpleNamespace

from app.domain.chunking.tables import row_text
from app.parsing.converters.pdf_layout import _body_rows, _first_data_row, structured_table


def _table(rows, bboxes):
    table = SimpleNamespace(
        extract=lambda: rows,
        rows=[SimpleNamespace(cells=row) for row in bboxes],
    )
    return table


def test_multilevel_header_is_flattened_with_merged_cells() -> None:
    rows = [
        ["", "2015", "2020", ""],
        ["SEKCJE", "w tys. etatów", None, "SECTIONS"],
        ["OGÓŁEM ......", "9823,0", "10700,9", "TOTAL"],
    ]
    cells = [
        [(0, 0, 10, 10), (10, 0, 20, 10), (20, 0, 30, 10), (30, 0, 40, 10)],
        [(0, 10, 10, 20), (10, 10, 30, 20), None, (30, 10, 40, 20)],
        [(0, 20, 10, 30), (10, 20, 20, 30), (20, 20, 30, 30), (30, 20, 40, 30)],
    ]
    out, header_rows = structured_table(_table(rows, cells))
    assert header_rows == 1
    assert out[0] == ["SEKCJE", "2015 / w tys. etatów", "2020 / w tys. etatów", "SECTIONS"]
    assert out[1] == ["OGÓŁEM", "9823,0", "10700,9", "TOTAL"]


def test_year_row_and_roman_terms_are_not_data() -> None:
    assert (
        _first_data_row([["", "2015", "2020"], ["WYSZ", "X", "XI"], ["Ogółem", "460", "132"]]) == 2  # noqa: PLR2004
    )


def test_table_without_header_keeps_first_row() -> None:
    rows = [["Ogółem", "460"], ["Kobiety", "132"]]
    cells = [[(0, 0, 10, 10), (10, 0, 20, 10)], [(0, 10, 10, 20), (10, 10, 20, 20)]]
    out, header_rows = structured_table(_table(rows, cells))
    assert (out, header_rows) == (rows, 1)


def test_label_split_around_values_is_merged() -> None:
    rows = [
        ["Rolnictwo i ry-", "", ""],
        ["", "145,1", "Agriculture"],
        ["bactwo", "", ""],
        ["Górnictwo", "20,0", "Mining"],
    ]
    assert _body_rows(rows) == [
        ["Rolnictwo i rybactwo", "145,1", "Agriculture"],
        ["Górnictwo", "20,0", "Mining"],
    ]


def test_group_heading_stays_separate_and_digits_are_not_joined() -> None:
    rows = [["WEDŁUG WIEKU", "", ""], ["Do 29 lat", "1 2 3", "x"]]
    assert _body_rows(rows) == [["WEDŁUG WIEKU", "", ""], ["Do 29 lat", "1 2 3", "x"]]


def test_unnamed_column_has_no_placeholder() -> None:
    assert row_text(["Rok", ""], ["2023", "11,5"]) == "Rok: 2023; 11,5"
