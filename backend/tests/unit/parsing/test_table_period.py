"""Rok w osobnej komórce za etykietą wiersza przy boczku o kolumnę węższym (table_period, blocks).

Przypadki z held-out: TABL. 6 rocznika śląskiego 2010 (skan, OCR) i TABL. 9 rocznika
Euroregionu Nysa 2011 — wartości stały pod nazwą sąsiedniej kolumny, model odpowiadał
„zawarto 2008 małżeństw”.
"""

from app.domain.chunking.tables import table_lines
from app.parsing.blocks import html_to_blocks
from app.parsing.table_period import merge_period_cells

_SLASKIE = (
    "<table><thead><tr><th rowspan='2'>WYSZCZEGÓLNIENIE</th><th colspan='2'>Małżeństwa</th>"
    "<th rowspan='2'>Separacje</th><th rowspan='2'>Rozwody</th><th rowspan='2'>Urodzenia żywe</th>"
    "<th colspan='2'>Zgony</th><th rowspan='2'>Przyrost naturalny</th></tr>"
    "<tr><th>ogółem</th><th>w tym wyznaniowe</th><th>ogółem</th><th>w tym niemowląt</th></tr>"
    "</thead><tbody>"
    "<tr><td>OGÓŁEM</td><td>2000</td><td>25336</td><td>17007</td><td>104</td><td>6012</td>"
    "<td>46000</td><td>47000</td><td>400</td></tr>"
    "<tr><td></td><td>2008</td><td>31109</td><td>19890</td><td>797</td><td>9711</td>"
    "<td>46994</td><td>48016</td><td>318</td></tr>"
    "</tbody></table>"
)

_NYSA = (
    "<table><thead><tr><th rowspan='2'>WYSZCZEGÓLNIENIE</th><th rowspan='2'>OGÓŁEM</th>"
    "<th colspan='3'>Przyczyny zgonów</th></tr>"
    "<tr><th>A00-B99</th><th>C00-D48</th><th>I00-I99</th></tr></thead><tbody>"
    "<tr><td>OGÓŁEM ...</td><td>2000</td><td>17473</td><td>58</td><td>4269</td></tr>"
    "<tr><td></td><td>2009</td><td>17973</td><td>133</td><td>4472</td></tr>"
    "</tbody></table>"
)


def _table(html: str):
    blocks = [b for b in html_to_blocks(html) if b.table is not None]
    assert len(blocks) == 1
    return blocks[0].table


def _record(table, row: int) -> dict[str, str]:
    return dict(zip(table.header, table.rows[row], strict=False))


def test_year_after_label_is_merged_and_values_return_under_headers() -> None:
    t = _table(_SLASKIE)
    first, second = _record(t, 0), _record(t, 1)
    assert first["Małżeństwa / ogółem"] == "25336"
    assert second["Małżeństwa / ogółem"] == "31109"
    assert second["Rozwody"] == "9711"
    assert second["Zgony / w tym niemowląt"] == "318"
    assert t.rows[1][0] == "OGÓŁEM 2008"  # pusta etykieta dziedziczy sekcję
    assert "<td>OGÓŁEM 2008</td>" in t.rows_html[1]
    assert "<td>31109</td>" in t.rows_html[1]
    assert t.rows_html[1].count("<td") == len(_SLASKIE.split("<tr><td></td>")[1].split("<td")) - 1


def test_nysa_total_column_gets_total_not_year() -> None:
    t = _table(_NYSA)
    rec = _record(t, 0)
    assert rec["OGÓŁEM"] == "17473"
    assert rec["Przyczyny zgonów / A00-B99"] == "58"
    assert rec["Przyczyny zgonów / C00-D48"] == "4269"
    assert "2000" not in rec.values()
    assert _record(t, 1)["OGÓŁEM"] == "17973"


def test_year_column_with_period_header_is_left_alone() -> None:
    html = (
        "<table><thead><tr><th>Województwo</th><th>Rok</th><th>Ludność</th></tr></thead><tbody>"
        "<tr><td>Śląskie</td><td>2008</td><td>4654115</td></tr>"
        "<tr><td>Śląskie</td><td>2009</td><td>4640725</td></tr></tbody></table>"
    )
    t = _table(html)
    assert _record(t, 0)["Rok"] == "2008"
    assert _record(t, 0)["Ludność"] == "4654115"


def test_value_column_with_year_like_numbers_is_not_moved() -> None:
    cell = ((1, 1),) * 3
    head = [(("Wiek", "Ogółem", "Kobiety"), "<tr></tr>", cell)]
    rows = [("19 lat i mniej", "1998", "3"), ("20-24", "4213", "12"), ("25-29", "1968", "40")]
    body = [(r, "<tr>" + "".join(f"<td>{x}</td>" for x in r) + "</tr>", cell) for r in rows]
    # 1998 i 1968 to liczby zgonów: w kolumnie „Ogółem” są też inne liczby, więc to nie lata.
    assert merge_period_cells(head, body) == body


def test_mixed_table_merges_only_rows_with_empty_label() -> None:
    # Nysa s. 73: OCR raz skleił rok z etykietą, raz zostawił go w osobnej komórce.
    html = (
        "<table><thead><tr><th>WYSZCZEGÓLNIENIE</th><th>Kina placówki</th><th>Kina miejsca</th>"
        "</tr></thead><tbody>"
        "<tr><td>Polska ... 1995</td><td>20</td><td>6903</td></tr>"
        "<tr><td>Polish 2000</td><td>20</td><td>6449</td></tr>"
        "<tr><td></td><td>2005</td><td>14</td><td>4401</td></tr>"
        "<tr><td></td><td>2010</td><td>11</td><td>3199</td></tr>"
        "</tbody></table>"
    )
    t = _table(html)
    assert _record(t, 1)["Kina placówki"] == "20"
    assert _record(t, 2)["Kina placówki"] == "14"
    assert _record(t, 3)["Kina miejsca"] == "3199"


def test_rowspan_label_is_repeated_so_year_can_join_it() -> None:
    html = (
        "<table><thead><tr><th>WYSZCZEGÓLNIENIE</th><th>OGÓŁEM</th><th>Mężczyźni</th></tr></thead>"
        "<tbody><tr><td>OGÓŁEM</td><td>1991</td><td>1769849</td><td>853470</td></tr>"
        '<tr><td rowspan="2">TOTAL</td><td>1995</td><td>1757434</td><td>852664</td></tr>'
        "<tr><td>2000</td><td>1703248</td><td>827817</td></tr></tbody></table>"
    )
    t = _table(html)
    assert [_record(t, r)["OGÓŁEM"] for r in range(3)] == ["1769849", "1757434", "1703248"]
    assert t.rows_html[2].startswith("<tr><td>TOTAL 2000</td><td>1703248</td>")
    assert "rowspan" not in "".join(t.rows_html)


_WARSZAWA = (
    "<table><thead><tr><th colspan='2' rowspan='2'>LATA PŁEĆ</th><th rowspan='2'>Ogółem</th>"
    "<th colspan='2'>Czas pozostawania bez pracy</th></tr>"
    "<tr><th>do 1 miesiąca</th><th>powyżej 24 miesięcy</th></tr></thead><tbody>"
    "<tr><td>O G Ó Ł E M</td><td>2005</td><td>58398</td><td>3641</td><td>19580</td></tr>"
    "<tr><td>T O T A L</td><td>2010</td><td>38640</td><td>3301</td><td>2887</td></tr>"
    "<tr><td></td><td>2015</td><td>39724</td><td>3140</td><td>9753</td></tr>"
    "<tr><td>Mężczyźni</td><td>2005</td><td>28257</td><td>1909</td><td>9013</td></tr>"
    "<tr><td>Males</td><td>2010</td><td>20189</td><td>1849</td><td>1482</td></tr>"
    "<tr><td></td><td>2014</td><td>25278</td><td>1874</td><td>6464</td></tr>"
    "<tr><td></td><td>2015</td><td>20512</td><td>1708</td><td>5199</td></tr>"
    "</tbody></table>"
)


def test_empty_label_in_wide_stub_gets_group_label() -> None:
    # Warszawa 2016, tabela „Bezrobotni według czasu pozostawania bez pracy” (DOCX, scalenie
    # w pionie): wiersz 2015 mężczyzn trafiał do fragmentu bez słowa „Mężczyźni”.
    t = _table(_WARSZAWA)
    assert t.rows_html[2].startswith("<tr><td>O G Ó Ł E M T O T A L</td><td>2015</td>")
    assert t.rows_html[5].startswith("<tr><td>Mężczyźni Males</td><td>2014</td>")
    assert t.rows_html[6].startswith("<tr><td>Mężczyźni Males</td><td>2015</td><td>20512</td>")
    assert t.rows_html[3].startswith("<tr><td>Mężczyźni</td><td>2005</td>")  # własna etykieta
    assert "Mężczyźni" in t.rows[6][0]


def test_narrow_stub_empty_label_is_left_alone() -> None:
    html = (
        "<table><thead><tr><th>Wyszczególnienie</th><th>2014</th><th>2015</th></tr></thead>"
        "<tbody><tr><td>Ludność</td><td>10</td><td>11</td></tr>"
        "<tr><td></td><td>12</td><td>13</td></tr></tbody></table>"
    )
    assert _table(html).rows_html[1].startswith("<tr><td></td>")


# Przełamane etykiety: TABL. 4 (106) Rocznika Statystycznego Przemysłu 2019 (XLSX) — nazwa działu
# w dwóch wierszach arkusza („… i opty-” bez liczb, „cznych ……” z liczbami); wiersz bez liczb
# był sekcją doklejaną do wszystkich dalszych działów („opty- / Produkcja mebli”).
def _wrapped(*rows: str) -> str:
    head = "<thead><tr><th>SEKCJE I DZIAŁY</th><th>2009</th><th>2010</th></tr></thead>"
    return f"<table>{head}<tbody>{''.join(rows)}</tbody></table>"


def _lines(html: str) -> list[str]:
    return [line for lines in table_lines(_table(html)) for line in lines]


def test_hyphen_wrapped_label_is_joined_and_not_a_section() -> None:
    html = _wrapped(
        "<tr><td>Produkcja komputerów, wyrobów elektronicznych i opty-</td><td></td><td></td></tr>",
        "<tr><td>cznych ……………</td><td>105.1</td><td>108.2</td></tr>",
        "<tr><td>Produkcja mebli ……………</td><td>110</td><td>107.1</td></tr>",
    )
    lines = _lines(html)
    assert any(
        line.startswith(
            "SEKCJE I DZIAŁY: Produkcja komputerów, wyrobów elektronicznych i optycznych"
        )
        for line in lines
    )
    assert any(line.startswith("SEKCJE I DZIAŁY: Produkcja mebli") for line in lines)
    assert not any("opty-" in line for line in lines)
    assert any("optycznych" in tr and "105.1" in tr for tr in _table(html).rows_html)


def test_lowercase_continuation_with_leaders_is_joined() -> None:
    html = _wrapped(
        "<tr><td>Produkcja wyrobów z pozostałych mineralnych surowców</td><td></td><td></td></tr>",
        "<tr><td>niemetalicznych ……………</td><td>108.7</td><td>103.7</td></tr>",
        "<tr><td>Produkcja metali ……………</td><td>102.9</td><td>102.1</td></tr>",
    )
    lines = _lines(html)
    assert any("surowców niemetalicznych" in line for line in lines)
    assert any(line.startswith("SEKCJE I DZIAŁY: Produkcja metali") for line in lines)


def test_section_with_subordinate_row_is_not_joined() -> None:
    html = _wrapped(
        "<tr><td>Miasta</td><td></td><td></td></tr>",
        "<tr><td>w tym kobiety ……</td><td>51</td><td>52</td></tr>",
    )
    assert any(line.startswith("SEKCJE I DZIAŁY: Miasta / w tym kobiety") for line in _lines(html))


def test_section_with_several_unit_rows_is_not_joined() -> None:
    # Rocznik Statystyczny Przemysłu 2025: „Energia pierwotna ogółem” nad „w TJ …” i „w % …”
    html = _wrapped(
        "<tr><td>Energia pierwotna ogółem</td><td></td><td></td></tr>",
        "<tr><td>w TJ ……</td><td>5100</td><td>5200</td></tr>",
        "<tr><td>w % ……</td><td>100,0</td><td>100,0</td></tr>",
    )
    lines = _lines(html)
    assert any(
        line.startswith("SEKCJE I DZIAŁY: Energia pierwotna ogółem / w TJ") for line in lines
    )
    assert any(line.startswith("SEKCJE I DZIAŁY: Energia pierwotna ogółem / w %") for line in lines)


def test_english_translation_row_is_not_joined() -> None:
    html = _wrapped(
        "<tr><td>choroby niedokrwienne serca ……</td><td>4992</td><td>107,3</td></tr>",
        "<tr><td>ischaemic heart disease</td><td></td><td></td></tr>",
        "<tr><td>choroby naczyń mózgowych ……</td><td>3814</td><td>90,1</td></tr>",
    )
    assert not any("disease choroby" in line for line in _lines(html))
