"""Ciąg dalszy tabeli na kolejnej stronie i tabela rozcięta — table_continuation."""

from app.domain.chunking.general import chunk_general
from app.domain.chunking.presets import preset_for
from app.domain.chunking.types import ChunkConfig
from app.parsing.blocks import html_to_blocks

_HEAD = "<thead><tr><th>Lp.</th><th>Uczelnia</th><th>Limit</th><th>Cudzoziemcy</th></tr></thead>"


def _page(n: int, body: str) -> str:
    return f'<section data-page="{n}">{body}</section>'


def _tables(html: str):
    return [b for b in html_to_blocks(html) if b.kind == "table"]


def _cfg() -> ChunkConfig:
    return ChunkConfig(count_tokens=lambda s: len(s.split()), chunk_token_num=512)


def test_next_page_table_with_data_row_as_header_gets_previous_header_and_title():
    html = _page(
        1,
        "<p>Tabela 1. Limit przyjęć na studia</p><table>"
        + _HEAD
        + "<tbody><tr><td>1</td><td>Uniwersytet A</td><td>196</td><td>2</td></tr></tbody></table>",
    ) + _page(
        2,
        "<p>Dziennik Ustaw</p><table><thead><tr><th>2</th><th>Uniwersytet B</th><th>326</th>"
        "<th>6</th></tr></thead><tbody><tr><td>3</td><td>Akademia C</td><td>225</td><td>0</td>"
        "</tr></tbody></table>",
    )
    first, second = _tables(html)
    assert second.table.header == first.table.header
    assert ("Akademia C", "225", "0") in second.table.rows or any(
        "Akademia C" in r and "225" in r for r in second.table.rows
    )
    assert any("Uniwersytet B" in r for r in second.table.rows)  # wiersz z nagłówka wraca do danych
    assert second.table.title == "Tabela 1. Limit przyjęć na studia"
    drafts = chunk_general(html_to_blocks(html), preset_for("naive"), _cfg())
    assert all("Limit przyjęć na studia" in d.text for d in drafts if d.chunk_type == "table")


def test_section_paragraph_between_tables_becomes_label_row():
    head = "<thead><tr><th>WYSZCZEGÓLNIENIE</th><th>2010/11</th><th>2018/19</th></tr></thead>"
    html = _page(
        1,
        "<p>TABL. 2 (130). SZKOŁY WEDŁUG ORGANÓW PROWADZĄCYCH</p><table>"
        + head
        + "<tbody><tr><td>Szkoły podstawowe</td><td>1 200</td><td>1 300</td></tr></tbody></table>"
        "<p>UCZNIOWIE I STUDENCI</p><table><thead><tr><th>Szkoły podstawowe</th><th>240382</th>"
        "<th>340783</th></tr></thead><tbody><tr><td>Licea</td><td>90 000</td><td>80 000</td></tr>"
        "</tbody></table>",
    )
    blocks = html_to_blocks(html)
    assert not any(b.kind == "paragraph" and b.text == "UCZNIOWIE I STUDENCI" for b in blocks)
    second = [b for b in blocks if b.kind == "table"][1]
    assert second.table.header[1].startswith("2010/11")
    assert "UCZNIOWIE I STUDENCI" in second.text
    assert any("340783" in r for r in second.table.rows)
    assert second.table.title.startswith("TABL. 2 (130)")


def test_new_table_with_own_header_is_not_joined():
    html = _page(
        1,
        "<p>Tabela 1. A</p><table>"
        + _HEAD
        + "<tbody><tr><td>1</td><td>X</td><td>1</td><td>2</td></tr></tbody></table>",
    ) + _page(
        2,
        "<table><thead><tr><th>Lp.</th><th>Szkoła</th><th>Uczniowie</th><th>Klasy</th></tr>"
        "</thead><tbody><tr><td>1</td><td>Y</td><td>30</td><td>2</td></tr></tbody></table>",
    )
    second = _tables(html)[1]
    assert second.table.header[1] == "Szkoła"
    assert second.table.title == ""


def test_table_after_long_text_is_not_joined():
    long_text = "Treść rozdziału " * 20
    html = _page(
        1,
        "<p>Tabela 1. A</p><table>"
        + _HEAD
        + "<tbody><tr><td>1</td><td>X</td><td>1</td><td>2</td></tr></tbody></table>",
    ) + _page(
        2,
        f"<p>{long_text}</p><table><thead><tr><th>2</th><th>Y</th><th>30</th><th>4</th></tr>"
        "</thead><tbody><tr><td>3</td><td>Z</td><td>1</td><td>5</td></tr></tbody></table>",
    )
    assert _tables(html)[1].table.title == ""


def test_wide_table_split_in_two_is_joined_side_by_side():
    left = (
        "<table><thead><tr><th>Wyszczególnienie</th><th>2000</th><th>2010</th></tr></thead>"
        "<tbody><tr><td>ŚWIAT</td><td>6 485,0</td><td>15 220,2</td></tr>"
        "<tr><td>Afryka</td><td>100,0</td><td>200,0</td></tr></tbody></table>"
    )
    right = (
        "<table><thead><tr><th>2019</th><th>2020</th></tr></thead>"
        "<tbody><tr><td>18 759,0</td><td>17 379,4</td></tr>"
        "<tr><td>300,0</td><td>250,0</td></tr></tbody></table>"
    )
    html = _page(1, "<p>TABL. I.36. IMPORT I EKSPORT</p>" + left + right)
    tables = _tables(html)
    assert len(tables) == 1
    assert tables[0].table.header[-1] == "2020"
    assert ("ŚWIAT", "6 485,0", "15 220,2", "18 759,0", "17 379,4") in tables[0].table.rows


def test_label_row_thead_is_skipped_and_column_header_taken_from_chain():
    """Strona „na tle kraju”: tabela z nazwami kolumn, pod nią tabele-sekcje z etykietą w thead."""
    html = _page(
        1,
        "<h2>I. WOJEWÓDZTWO NA TLE KRAJU</h2><table><thead><tr><th>WYSZCZEGÓLNIENIE</th>"
        "<th>Polska</th><th>Województwo</th><th>SPECIFICATION</th></tr></thead></table>"
        "<p>JUSTICE</p><table><thead><tr><th>Przestępstwa stwierdzone:</th><th></th><th></th>"
        "<th>Crimes ascertained:</th></tr></thead><tbody><tr><td>ogółem</td><td>772682</td>"
        "<td>50667</td><td>total</td></tr></tbody></table>"
        "<p>POPULATION</p><table><thead><tr><th>Ludność w tys.</th><th>37489,1</th><th>2359,5</th>"
        "<th>Population</th></tr></thead><tbody><tr><td>miasta</td><td>22276,0</td><td>1465,5</td>"
        "<td>urban</td></tr></tbody></table>",
    )
    last = _tables(html)[-1]
    assert last.table.header[1].startswith("Polska")
    assert last.table.header[2].startswith("Województwo")
    assert any("1465,5" in r for r in last.table.rows)


def test_english_caps_translation_is_not_a_title():
    html = _page(
        1,
        "<h2>I. WOJEWÓDZTWO NA TLE KRAJU W 2024 R.</h2>"
        "<p>VOIVODSHIP AGAINST THE BACKGROUND OF THE COUNTRY IN 2024</p><table><thead><tr>"
        "<th>WYSZCZEGÓLNIENIE</th><th>Polska</th><th>Województwo</th></tr></thead><tbody><tr>"
        "<td>Ludność</td><td>37489,1</td><td>2359,5</td></tr></tbody></table>",
    )
    drafts = chunk_general(html_to_blocks(html), preset_for("naive"), _cfg())
    assert not any("VOIVODSHIP AGAINST" in d.text for d in drafts if d.chunk_type == "table")
