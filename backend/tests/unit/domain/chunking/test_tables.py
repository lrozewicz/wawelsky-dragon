"""Testy tabel: row_text, table_text, chunk_table (CONTRACT WP E1-5 C7); tiktoken."""

import logging
from html import escape

from app.domain.chunking.general import chunk_general
from app.domain.chunking.presets import preset_for
from app.domain.chunking.tables import (
    chunk_table,
    row_text,
    section_heads,
    table_lead,
    table_lines,
    table_text,
)
from app.domain.chunking.types import Block, ChunkConfig, TableData
from app.llm.tokens import count_tokens
from app.parsing.blocks import html_to_blocks

# Nazwane stałe zamiast liczb magicznych (PLR2004).
LIMIT_128 = 128
WIDE_ROW_COUNT = 60
OVERSIZED_SENTENCES = 40
MIN_CHUNKS_WIDE = 3
MIN_CHUNKS_OVERSIZED = 4
MIN_CHUNKS_PARAGRAPHS = 3

_HEADER = ("Imię", "Wiek", "Miasto")
_HEADER_HTML = "<thead><tr><th>Imię</th><th>Wiek</th><th>Miasto</th></tr></thead>"
_HEADER_LINE = " | ".join(_HEADER)

_SMALL_TABLE = TableData(
    header=("Imię", "Wiek"),
    rows=(("Ala", "7"), ("Ola", "9"), ("Ula", "12")),
    header_html="<thead><tr><th>Imię</th><th>Wiek</th></tr></thead>",
    rows_html=(
        "<tr><td>Ala</td><td>7</td></tr>",
        "<tr><td>Ola</td><td>9</td></tr>",
        "<tr><td>Ula</td><td>12</td></tr>",
    ),
)

_TEXT_A = "Akapit przed tabelą zawiera wystarczająco dużo słów."
_TEXT_B = "Akapit po tabeli również zawiera wystarczająco dużo słów."
_SENTENCE = "Zdanie numer {} opisuje szczegóły testu wydajności."


def _wide_table() -> TableData:
    rows = tuple((f"Ala{i}", str(10 + i % 80), f"Miasto{i}") for i in range(WIDE_ROW_COUNT))
    rows_html = tuple(
        f"<tr><td>Ala{i}</td><td>{10 + i % 80}</td><td>Miasto{i}</td></tr>"
        for i in range(WIDE_ROW_COUNT)
    )
    return TableData(header=_HEADER, rows=rows, header_html=_HEADER_HTML, rows_html=rows_html)


def _table_block(t: TableData, path: tuple[str, ...] = (), positions: tuple = ()) -> Block:
    full_html = f"<table>{t.header_html}<tbody>{''.join(t.rows_html)}</tbody></table>"
    text = "\n".join([" | ".join(t.header)] + [" | ".join(r) for r in t.rows])
    return Block(
        kind="table",
        text=text,
        html=full_html,
        level=None,
        heading_path=path,
        positions=positions,
        section=None,
        table=t,
    )


def _para(text: str, path: tuple[str, ...] = ()) -> Block:
    return Block(
        kind="paragraph",
        text=text,
        html=f"<p>{escape(text)}</p>",
        level=None,
        heading_path=path,
        positions=(),
        section=None,
        table=None,
    )


def _cfg(**overrides: object) -> ChunkConfig:
    return ChunkConfig(count_tokens=count_tokens, **overrides)


def test_row_text_pairs_non_empty_values():
    assert row_text(("Imię", "Wiek"), ("Ala", "7")) == "Imię: Ala; Wiek: 7"


def test_row_text_skips_empty_values():
    assert row_text(("A", "B"), ("", "x")) == "B: x"


def test_row_text_unnamed_columns_have_bare_values():
    assert row_text((), ("a", "b")) == "a; b"


def test_table_text_pairs_mode():
    t = TableData(header=("H1", "H2"), rows=(("a", "b"), ("c", "")), header_html="", rows_html=())
    assert table_text(t, html4excel=False) == "H1: a; H2: b\nH1: c"


def test_table_text_html4excel_mode():
    t = TableData(header=("H1", "H2"), rows=(("a", "b"),), header_html="", rows_html=())
    assert table_text(t, html4excel=True) == "H1 | H2\na | b"


def test_table_text_html4excel_skips_empty_header():
    t = TableData(header=(), rows=(("a", "b"),), header_html="", rows_html=())
    assert table_text(t, html4excel=True) == "a | b"


def test_small_table_single_chunk():
    blok = _table_block(_SMALL_TABLE, path=("Dane",), positions=((1, 0, 0, 0, 0),))
    drafty = chunk_table(blok, _cfg())
    assert len(drafty) == 1
    d = drafty[0]
    wiersze = [row_text(_SMALL_TABLE.header, r) for r in _SMALL_TABLE.rows]
    expected_text = "Dane\n" + "\n".join(wiersze)
    assert d.text == expected_text
    assert d.html == '<p class="breadcrumb">Dane</p>' + blok.html
    assert d.chunk_type == "table"
    assert d.heading_path == ("Dane",)
    assert d.positions == ((1, 0, 0, 0, 0),)
    assert d.tokens == count_tokens(d.text)


def test_wide_table_split_by_rows():
    t = _wide_table()
    blok = _table_block(t)
    drafty = chunk_table(blok, _cfg(chunk_token_num=LIMIT_128))
    assert len(drafty) >= MIN_CHUNKS_WIDE
    wszystkie_html = "".join(d.html for d in drafty)
    for d in drafty:
        assert d.chunk_type == "table"
        assert d.tokens <= LIMIT_128
        assert d.html.count(_HEADER_HTML) == 1
        assert d.html.startswith("<table>" + _HEADER_HTML + "<tbody>")
        assert d.html.endswith("</tbody></table>")
    pozycja = 0
    for row_html in t.rows_html:
        assert wszystkie_html.count(row_html) == 1
        pozycja = wszystkie_html.find(row_html, pozycja)
        assert pozycja >= 0
        pozycja += len(row_html)


def test_wide_table_html4excel_header_in_every_text():
    blok = _table_block(_wide_table())
    drafty = chunk_table(blok, _cfg(chunk_token_num=LIMIT_128, html4excel=True))
    assert len(drafty) >= MIN_CHUNKS_WIDE
    assert all(d.text.startswith(_HEADER_LINE) for d in drafty)
    assert all(d.tokens <= LIMIT_128 for d in drafty)


def test_oversized_row_split_with_warning(caplog):
    dluga_tresc = " ".join(_SENTENCE.format(i) for i in range(OVERSIZED_SENTENCES))
    t = TableData(
        header=("Tytuł", "Treść"),
        rows=(("Raport", dluga_tresc),),
        header_html="<thead><tr><th>Tytuł</th><th>Treść</th></tr></thead>",
        rows_html=(f"<tr><td>Raport</td><td>{escape(dluga_tresc)}</td></tr>",),
    )
    blok = _table_block(t)
    with caplog.at_level(logging.WARNING, logger="app.domain.chunking.tables"):
        drafty = chunk_table(blok, _cfg(chunk_token_num=LIMIT_128))
    assert len(drafty) >= MIN_CHUNKS_OVERSIZED
    assert all(d.tokens <= LIMIT_128 for d in drafty)
    assert all(t.header_html in d.html for d in drafty)
    assert "table row split" in caplog.text


def test_table_without_data_treated_as_paragraph():
    blok = Block(
        kind="table",
        text="tabela opisowa",
        html="<p>tabela opisowa</p>",
        level=None,
        heading_path=(),
        positions=(),
        section=None,
        table=None,
    )
    drafty = chunk_table(blok, _cfg())
    assert len(drafty) == 1
    assert drafty[0].text == "tabela opisowa"
    assert drafty[0].html == "<p>tabela opisowa</p>"


def test_table_closes_current_chunk_in_general_flow():
    bloki = [_para(_TEXT_A), _table_block(_SMALL_TABLE), _para(_TEXT_B)]
    drafty = chunk_general(bloki, preset_for("naive"), _cfg())
    assert len(drafty) == MIN_CHUNKS_PARAGRAPHS
    assert [d.chunk_type for d in drafty] == ["text", "table", "text"]
    assert _TEXT_A in drafty[0].text
    assert _TEXT_B in drafty[2].text


# Tabela T17: nagłówek 3-poziomowy (colspan/rowspan), jeden wiersz danych.
_T17_SUBHEADERS = ["ogólem total", "w tym kobiety of which women"] * 4
_T17_VALUES = ["9,9", "10,3", "10,9", "11,6", "10,8", "11,3", "11,3", "11,1"]
_T17_HTML = (
    "<table><thead>"
    '<tr><th rowspan="3">WYSZCZEGÓLNIENIE</th>'
    '<th colspan="2">2019</th><th colspan="2">2020</th>'
    '<th colspan="2">2022</th><th colspan="2">2023</th>'
    '<th rowspan="3">SPECIFICATION</th></tr>'
    "<tr>" + "".join(f"<th>{text}</th>" for text in _T17_SUBHEADERS) + "</tr>"
    '<tr><th colspan="8">w % in %</th></tr>'
    "</thead><tbody>"
    "<tr><td>15—24 lata</td>"
    + "".join(f"<td>{value}</td>" for value in _T17_VALUES)
    + "<td>15—24</td></tr>"
    "</tbody></table>"
)


def test_chunk_t17_pairs():
    blok = html_to_blocks(_T17_HTML)[0]
    drafty = chunk_table(blok, _cfg())
    assert len(drafty) == 1
    d = drafty[0]
    assert "2022 / ogólem total / w % in %: 10,8" in d.text
    assert "2022 / w tym kobiety of which women / w % in %: 11,3" in d.text
    assert "2020 / ogólem total / w % in %: 10,8" not in d.text
    assert 'colspan="2"' in d.html


# ---------------------------------------------------------------- zdanie wprowadzające (jednostka)


def _para_block(text: str) -> Block:
    return Block(
        kind="paragraph",
        text=text,
        html=f"<p>{escape(text)}</p>",
        level=None,
        heading_path=(),
        positions=(),
        section=None,
        table=None,
    )


def test_table_lead_unit_sentence_and_colon():
    unit = "The following table shows net sales by segment (dollars in millions):"
    assert table_lead(_para_block(unit)) == unit
    assert table_lead(_para_block("Przychody ogółem w mln zł")) == "Przychody ogółem w mln zł"
    assert table_lead(_para_block("Zwykłe zdanie bez jednostki.")) == ""
    assert table_lead(None) == ""


def test_table_lead_last_sentence_of_long_paragraph():
    body = "Długi opis wyników. " * 30 + "Tabela pokazuje sprzedaż (w tys. zł):"
    assert table_lead(_para_block(body)) == "Tabela pokazuje sprzedaż (w tys. zł):"


def test_lead_in_every_table_chunk_after_split():
    """Tabela dzielona po wierszach: każdy chunk niesie jednostkę z akapitu nad tabelą."""
    lead = "Sprzedaż według regionów (w mln zł):"
    rows = "".join(
        f"<tr><td>Region {i}</td><td>{i * 1000}</td></tr>" for i in range(WIDE_ROW_COUNT)
    )
    head = "<thead><tr><th>Region</th><th>Kwota</th></tr></thead>"
    html = f"<p>{lead}</p><table>{head}<tbody>{rows}</tbody></table>"
    drafts = chunk_general(html_to_blocks(html), preset_for("naive"), _cfg_limit(LIMIT_128))
    tables = [d for d in drafts if d.chunk_type == "table"]
    assert len(tables) >= MIN_CHUNKS_WIDE
    assert all(d.text.startswith(lead + "\n") for d in tables)
    assert all('<p class="table-lead">' in d.html for d in tables)


def test_no_lead_without_unit_or_colon():
    html = f"<p>{_TEXT_A}</p><table><tr><td>a</td></tr><tr><td>1</td></tr></table>"
    drafts = chunk_general(html_to_blocks(html), preset_for("naive"), _cfg_limit(LIMIT_128))
    table = next(d for d in drafts if d.chunk_type == "table")
    assert "table-lead" not in table.html


def _cfg_limit(limit: int) -> ChunkConfig:
    return ChunkConfig(count_tokens=count_tokens, chunk_token_num=limit)


# --- Tabele roczników GUS: tytuł, tabele „podwójne”, wiersze-tłumaczenia ---


def _table(header: tuple[str, ...], rows: tuple[tuple[str, ...], ...]) -> TableData:
    return TableData(
        header=header,
        rows=rows,
        header_html="<thead></thead>",
        rows_html=tuple("<tr></tr>" for _ in rows),
    )


def test_table_lead_finds_caption_in_paragraphs_before_table():
    before = [
        _para("Schools for children and youth"),
        _para("TABL. 13 (227). SZKOŁY PODSTAWOWE DLA DZIECI I MŁODZIEŻY"),
        _para("PRIMARY SCHOOLS FOR CHILDREN AND YOUTH"),
    ]
    caption = "TABL. 13 (227). SZKOŁY PODSTAWOWE DLA DZIECI I MŁODZIEŻY"
    assert table_lead(before[-1], before) == caption


def test_table_lead_caption_at_end_of_footnote_block():
    block = _para(
        "a Dane dotyczą poprzedniego roku szkolnego.\nŹródło: dane MEN.\n"
        "TABL. 14 (228). BRANŻOWE SZKOŁY I STOPNIA\nSTAGE I SECTORAL VOCATIONAL SCHOOLS"
    )
    assert table_lead(block, [block]) == "TABL. 14 (228). BRANŻOWE SZKOŁY I STOPNIA"


def test_table_lead_ignores_caption_far_above():
    block = _para("Tabela 2. Wyniki\n" + "\n".join(f"Linia {i} tekstu." for i in range(5)))
    assert table_lead(block, [block]) == ""


def test_table_lead_caption_and_unit_joined():
    before = [_para("Tabela 4. Przychody"), _para("Dane w mln zł:")]
    assert table_lead(before[-1], before) == "Tabela 4. Przychody\nDane w mln zł:"


def test_caption_not_taken_across_previous_table():
    t = _table(("A", "B"), (("x", "1"),))
    before = [_para("Tabela 1. Stara"), _table_block(t)]
    assert table_lead(None, before) == ""


def test_double_width_table_split_into_records():
    header = ("MIASTA", "2020", "2021 / ogółem", "MIASTA (cd.)", "2020", "2021 / ogółem")
    rows = (("Poznań", "547777", "545073", "Luboń", "33042", "32922"),)
    assert table_text(_table(header, rows), html4excel=False) == (
        "MIASTA: Poznań; 2020: 547777; 2021 / ogółem: 545073\n"
        "MIASTA: Luboń; 2020: 33042; 2021 / ogółem: 32922"
    )


def test_double_width_table_skips_empty_half():
    header = ("Kraj", "Wartość", "Kraj", "Wartość")
    rows = (("Austria", "46,2", "", ""),)
    assert table_text(_table(header, rows), html4excel=False) == "Kraj: Austria; Wartość: 46,2"


def test_bilingual_translation_rows_dropped():
    header = ("WYSZCZEGÓLNIENIE", "2023/24")
    rows = (
        ("Uczniowie w tys.", "3007,4"),
        ("Pupils in thousands", ""),
        ("w tym kobiety", "1451,6"),
        ("of which females", ""),
    )
    assert table_text(_table(header, rows), html4excel=False) == (
        "WYSZCZEGÓLNIENIE: Uczniowie w tys.; 2023/24: 3007,4\n"
        "WYSZCZEGÓLNIENIE: w tym kobiety; 2023/24: 1451,6"
    )


def test_section_rows_prefix_following_records():
    header = ("Pozycja", "Wartość")
    rows = (
        ("Szkoly podstawowe", ""),
        ("Uczniowie", "10"),
        ("Nauczyciele", "2"),
        ("Oddzialy", "3"),
        ("Licea", ""),
        ("Uczniowie", "5"),
    )
    assert table_text(_table(header, rows), html4excel=False) == (
        "Pozycja: Szkoly podstawowe / Uczniowie; Wartość: 10\n"
        "Pozycja: Szkoly podstawowe / Nauczyciele; Wartość: 2\n"
        "Pozycja: Szkoly podstawowe / Oddzialy; Wartość: 3\n"
        "Pozycja: Licea / Uczniowie; Wartość: 5"
    )


def test_bilingual_section_label_and_lp_column():
    header = ("Lp.", "Województwa", "1990")
    rows = (
        ("", "MIASTA", ""),
        ("", "URBAN AREAS", ""),
        ("1", "Warmińsko-mazurskie", "66,1"),
        ("", "WIEŚ", ""),
        ("", "RURAL AREAS", ""),
        ("2", "Warmińsko-mazurskie", "64,5"),
    )
    assert table_text(_table(header, rows), html4excel=False) == (
        "Lp.: 1; Województwa: MIASTA URBAN AREAS / Warmińsko-mazurskie; 1990: 66,1\n"
        "Lp.: 2; Województwa: WIEŚ RURAL AREAS / Warmińsko-mazurskie; 1990: 64,5"
    )


def test_section_split_across_chunks_keeps_label():
    header = ("Region", "Wartość")
    rows = (("WIEŚ", ""), *((f"Region{i}", str(i)) for i in range(WIDE_ROW_COUNT)))
    t = TableData(
        header=header,
        rows=rows,
        header_html="<thead></thead>",
        rows_html=tuple("<tr></tr>" for _ in rows),
    )
    drafts = chunk_table(_table_block(t), _cfg(chunk_token_num=LIMIT_128))
    assert len(drafts) >= MIN_CHUNKS_WIDE
    assert all("WIEŚ / Region" in d.text for d in drafts)


def test_trailing_label_rows_kept_as_text():
    header = ("Pozycja", "Wartość")
    rows = (("Uczniowie", "10"), ("Uwaga: dane wstępne", ""))
    assert table_text(_table(header, rows), html4excel=False) == (
        "Pozycja: Uczniowie; Wartość: 10\nPozycja: Uwaga: dane wstępne"
    )


def test_label_row_with_polish_chars_kept_even_if_alternating():
    header = ("Pozycja", "Wartość")
    rows = (("Uczniowie", "10"), ("Szkoły specjalne", ""), ("Nauczyciele", "2"), ("w tym:", ""))
    text = table_text(_table(header, rows), html4excel=False)
    assert "Szkoły specjalne / Nauczyciele" in text
    assert "w tym:" in text


def test_english_table_alternating_labels_not_dropped():
    header = ("Item", "2024")
    rows = (("Products", "100"), ("Services", ""), ("Revenue", "5"), ("Other items", ""))
    text = table_text(_table(header, rows), html4excel=False)
    assert "Services / Revenue" in text
    assert "Other items" in text


def test_repeated_label_blocks_get_aggregate_row_as_header():
    regions = ("Dolnośląskie", "Lubelskie", "Mazowieckie")
    rows = (
        ("POLSKA POLAND", "66,2"),
        *((r, "1") for r in regions),
        ("Miasta Urban areas", "66,4"),
        *((r, "2") for r in regions),
        ("Wieś Rural areas", "66,0"),
        *((r, "3") for r in regions),
    )
    lines = table_text(_table(("Województwa", "1990"), rows), html4excel=False).splitlines()
    assert lines[0] == "Województwa: POLSKA POLAND; 1990: 66,2"
    assert lines[1] == "Województwa: POLSKA POLAND / Dolnośląskie; 1990: 1"
    assert lines[5] == "Województwa: Miasta Urban areas / Dolnośląskie; 1990: 2"
    assert lines[9] == "Województwa: Wieś Rural areas / Dolnośląskie; 1990: 3"
    assert lines[11] == "Województwa: Wieś Rural areas / Mazowieckie; 1990: 3"


def test_short_repeats_do_not_make_blocks():
    rows = (
        ("Uczniowie", "10"),
        ("w tym kobiety", "5"),
        ("Absolwenci", "3"),
        ("w tym kobiety", "1"),
    )
    text = table_text(_table(("Pozycja", "2024"), rows), html4excel=False)
    assert " / " not in text


def test_data_row_matching_section_label_opens_new_section():
    header = ("Gminy", "2021", "Gminy", "2021")
    rows = (
        ("Mazowieckie (dok.)", "", "Podkarpackie (cd.)", ""),
        ("Wyszków", "10", "Jasło", "20"),
        ("Podkarpackie", "500", "Krosno", "30"),
        ("Dębica", "40", "", ""),
    )
    lines = table_text(_table(header, rows), html4excel=False).splitlines()
    assert lines == [
        "Gminy: Mazowieckie (dok.) / Wyszków; 2021: 10",
        "Gminy: Podkarpackie (cd.) / Jasło; 2021: 20",
        "Gminy: Podkarpackie; 2021: 500",
        "Gminy: Podkarpackie (cd.) / Krosno; 2021: 30",
        "Gminy: Podkarpackie / Dębica; 2021: 40",
    ]


def test_section_not_duplicated_when_label_repeats_it():
    header = ("Płeć", "2021")
    rows = (("Kobiety", ""), ("Kobiety ogółem", "5"), ("w wieku 0-14", "1"))
    lines = table_text(_table(header, rows), html4excel=False).splitlines()
    assert lines == ["Płeć: Kobiety ogółem; 2021: 5", "Płeć: Kobiety / w wieku 0-14; 2021: 1"]


def test_section_heads_from_other_tables_close_section():
    header = ("Miasta", "2021")
    page1 = _table(
        header, (("Opolskie (dok.)", ""), ("Nysa", "1"), ("Podkarpackie", "9"), ("Rzeszów", "2"))
    )
    page2 = _table(header, (("Podkarpackie (cd.)", ""), ("Krosno", "3")))
    lines = table_lines(page1, section_heads([page1, page2]))
    assert lines == [
        [],
        ["Miasta: Opolskie (dok.) / Nysa; 2021: 1"],
        ["Miasta: Podkarpackie; 2021: 9"],
        ["Miasta: Podkarpackie / Rzeszów; 2021: 2"],
    ]


def test_note_rows_are_not_sections():
    header = ("OBJAŚNIENIA:", "")
    note = "Dane dla sekcji S obejmują również pracujących w sekcjach T oraz U."
    rows = ((note, ""), ("Zagranica", "Dotyczy pracujących spoza Polski."))
    lines = table_text(_table(header, rows), html4excel=False).splitlines()
    assert lines == [
        f"OBJAŚNIENIA:: {note}",
        "OBJAŚNIENIA:: Zagranica; Dotyczy pracujących spoza Polski.",
    ]
