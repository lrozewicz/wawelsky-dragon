"""Rok w osobnej komórce za etykietą wiersza przy boczku o kolumnę węższym (table_period, blocks).

Przypadki z held-out: TABL. 6 rocznika śląskiego 2010 (skan, OCR) i TABL. 9 rocznika
Euroregionu Nysa 2011 — wartości stały pod nazwą sąsiedniej kolumny, model odpowiadał
„zawarto 2008 małżeństw”.
"""

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
