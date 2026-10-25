"""Testy tabel: row_text, table_text, chunk_table (CONTRACT WP E1-5 C7); tiktoken."""

import logging
from html import escape

from app.domain.chunking.general import chunk_general
from app.domain.chunking.presets import preset_for
from app.domain.chunking.tables import chunk_table, row_text, table_text
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


def test_row_text_fallback_column_names():
    assert row_text((), ("a", "b")) == "column_1: a; column_2: b"


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
