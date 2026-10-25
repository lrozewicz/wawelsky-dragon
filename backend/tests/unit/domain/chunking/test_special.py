"""Testy presetów specjalnych: presentation, one, qa, table i stopek paper (C10)."""

from html import escape

import pytest

from app.domain.chunking.chunker import chunk_blocks
from app.domain.chunking.errors import DocumentTooLarge
from app.domain.chunking.presets import preset_for
from app.domain.chunking.special import strip_page_furniture
from app.domain.chunking.types import Block, ChunkConfig, Position, TableData
from app.llm.tokens import count_tokens

# Nazwane stałe zamiast liczb magicznych (PLR2004).
ARGUMENT_ERROR_CODE = 101
SLIDE_MAX_TOKENS = 100
ONE_MAX_TOKENS = 50
ROW_MAX_TOKENS = 60
MIN_SLIDE_CHUNKS = 3
MIN_ROW_CHUNKS = 2
SLIDE_SENTENCE_REPEATS = 20
LONG_SENTENCE_REPEATS = 8
PAGE_COUNT = 4
DEDICATION_PAGES = 2
FURNITURE_CONTENT_COUNT = 6

_POS_A = (1, 0, 0, 0, 0)
_POS_B = (1, 1, 1, 1, 1)
_POS_C = (1, 2, 2, 2, 2)
_POS_D = (1, 3, 3, 3, 3)

_SLIDE_SENTENCE = (
    "Prezentacja omawia wyniki eksperymentów przeprowadzonych w laboratorium badawczym "
    "podczas ostatniego kwartału."
)
_LONG_SENTENCE = "Zdanie o przebiegu długiego eksperymentu badawczego i jego wnioskach."

_TABLE_ROLES = {"SKU": "metadata", "Cena": "indexing"}

_PRODUCT_TABLE = TableData(
    header=("Produkt", "Cena", "SKU"),
    rows=(("Mleko", "3.50", "X1"), ("Chleb", "", "X2")),
    header_html="<thead><tr><th>Produkt</th><th>Cena</th><th>SKU</th></tr></thead>",
    rows_html=(
        "<tr><td>Mleko</td><td>3.50</td><td>X1</td></tr>",
        "<tr><td>Chleb</td><td></td><td>X2</td></tr>",
    ),
)

_QA_TABLE = TableData(
    header=("Jak?", "Tak."),
    rows=(("Co?", "To."), ("", "x")),
    header_html="<thead><tr><th>Jak?</th><th>Tak.</th></tr></thead>",
    rows_html=("<tr><td>Co?</td><td>To.</td></tr>", "<tr><td></td><td>x</td></tr>"),
)


def _cfg(**overrides: object) -> ChunkConfig:
    return ChunkConfig(count_tokens=count_tokens, **overrides)


def _para(
    text: str,
    *,
    positions: tuple[Position, ...] = (),
    section: str | None = None,
    path: tuple[str, ...] = (),
) -> Block:
    return Block(
        kind="paragraph",
        text=text,
        html=f"<p>{escape(text)}</p>",
        level=None,
        heading_path=path,
        positions=positions,
        section=section,
        table=None,
    )


def _head(text: str, level: int, *, section: str | None = None) -> Block:
    return Block(
        kind="heading",
        text=text,
        html=f"<h{level}>{escape(text)}</h{level}>",
        level=level,
        heading_path=(),
        positions=(),
        section=section,
        table=None,
    )


def _notes(text: str, *, section: str | None = None) -> Block:
    return Block(
        kind="notes",
        text=text,
        html=f"<aside>{escape(text)}</aside>",
        level=None,
        heading_path=(),
        positions=(),
        section=section,
        table=None,
    )


def _figure(text: str) -> Block:
    return Block(
        kind="figure",
        text=text,
        html=f"<figure><figcaption>{escape(text)}</figcaption></figure>",
        level=None,
        heading_path=(),
        positions=(),
        section=None,
        table=None,
    )


def _table_block(t: TableData, positions: tuple[Position, ...] = ()) -> Block:
    full_html = f"<table>{t.header_html}<tbody>{''.join(t.rows_html)}</tbody></table>"
    lines = [" | ".join(t.header)] + [" | ".join(row) for row in t.rows]
    return Block(
        kind="table",
        text="\n".join(lines),
        html=full_html,
        level=None,
        heading_path=(),
        positions=positions,
        section=None,
        table=t,
    )


# -- presentation (C10.1) --


def test_presentation_two_slides():
    bloki = [
        _head("Tytuł", 1, section="slide:1"),
        _para("punkt", section="slide:1"),
        _notes("notatka", section="slide:1"),
        _para("drugi", section="slide:2"),
    ]
    drafty = chunk_blocks(bloki, preset_for("presentation"), _cfg())
    assert [d.text for d in drafty] == ["Tytuł\npunkt\nnotatka", "drugi"]
    assert all(d.heading_path == () for d in drafty)
    assert drafty[0].html == "<h1>Tytuł</h1><p>punkt</p><aside>notatka</aside>"


def test_presentation_notes_at_end():
    bloki = [
        _para("a", section="slide:1"),
        _notes("n", section="slide:1"),
        _para("b", section="slide:1"),
    ]
    drafty = chunk_blocks(bloki, preset_for("presentation"), _cfg())
    assert [d.text for d in drafty] == ["a\nb\nn"]
    assert drafty[0].html == "<p>a</p><p>b</p><aside>n</aside>"


def test_presentation_without_sections_uses_naive():
    bloki = [
        _head("Rozdział", 1),
        _para("Treść pierwsza.", path=("Rozdział",)),
        _para("Treść druga.", path=("Rozdział",)),
    ]
    drafty = chunk_blocks(bloki, preset_for("presentation"), _cfg())
    assert drafty == chunk_blocks(bloki, preset_for("naive"), _cfg())
    assert "breadcrumb" in drafty[0].html


def test_presentation_slide_over_limit():
    tekst = " ".join([_SLIDE_SENTENCE] * SLIDE_SENTENCE_REPEATS)
    assert count_tokens(tekst) > 2 * SLIDE_MAX_TOKENS
    drafty = chunk_blocks(
        [_para(tekst, section="slide:1")],
        preset_for("presentation"),
        _cfg(max_tokens=SLIDE_MAX_TOKENS),
    )
    assert len(drafty) >= MIN_SLIDE_CHUNKS
    assert all(d.tokens <= SLIDE_MAX_TOKENS for d in drafty)
    assert all(d.html.startswith("<p>") for d in drafty)


def test_presentation_empty_group_skipped():
    bloki = [_para("zawartość", section="slide:1"), _para("   ", section="slide:2")]
    drafty = chunk_blocks(bloki, preset_for("presentation"), _cfg())
    assert [d.text for d in drafty] == ["zawartość"]


# -- one / picture (C10.2) --


def test_one_single_chunk_with_all_positions():
    bloki = [
        _para("Akapit pierwszy.", positions=(_POS_A,)),
        _para("Akapit drugi.", positions=(_POS_B,)),
        _table_block(_QA_TABLE, positions=(_POS_C,)),
        _para("Akapit trzeci.", positions=(_POS_D,)),
    ]
    drafty = chunk_blocks(bloki, preset_for("one"), _cfg())
    assert len(drafty) == 1
    assert drafty[0].text == "\n".join(b.text for b in bloki if b.text.strip())
    assert drafty[0].html == "".join(b.html for b in bloki)
    assert drafty[0].chunk_type == "text"
    assert drafty[0].positions == (_POS_A, _POS_B, _POS_C, _POS_D)
    assert drafty[0].ordinal == 0


def test_one_document_too_large():
    tekst = " ".join([_LONG_SENTENCE] * LONG_SENTENCE_REPEATS)
    assert count_tokens(tekst) > ONE_MAX_TOKENS
    with pytest.raises(DocumentTooLarge) as exc_info:
        chunk_blocks([_para(tekst)], preset_for("one"), _cfg(max_tokens=ONE_MAX_TOKENS))
    assert str(exc_info.value) == "document too large for 'one'"
    assert exc_info.value.code == ARGUMENT_ERROR_CODE


def test_picture_uses_one_chunk():
    drafty = chunk_blocks([_figure("Wykres wzrostu sprzedaży")], preset_for("picture"), _cfg())
    assert [d.text for d in drafty] == ["Wykres wzrostu sprzedaży"]
    assert drafty[0].chunk_type == "text"


# -- qa (C10.3) --


def test_qa_from_table():
    drafty = chunk_blocks([_table_block(_QA_TABLE, positions=(_POS_A,))], preset_for("qa"), _cfg())
    assert [d.text for d in drafty] == [
        "Question: Jak?\tAnswer: Tak.",
        "Question: Co?\tAnswer: To.",
    ]
    assert [d.questions for d in drafty] == [("Jak?",), ("Co?",)]
    assert all(d.chunk_type == "qa" for d in drafty)
    assert all(d.positions == (_POS_A,) for d in drafty)


def test_qa_from_text_lines():
    akapit = "Q: Ile?\nA: Dwa.\nciąg dalszy\nQ: Kto?\nA: Ja."
    drafty = chunk_blocks([_para(akapit)], preset_for("qa"), _cfg())
    assert [d.text for d in drafty] == [
        "Question: Ile?\tAnswer: Dwa.\nciąg dalszy",
        "Question: Kto?\tAnswer: Ja.",
    ]


def test_qa_polish_prefixes():
    akapit = "Pytanie: Gdzie?\nOdpowiedź: Tu."
    drafty = chunk_blocks([_para(akapit)], preset_for("qa"), _cfg())
    assert [d.text for d in drafty] == ["Question: Gdzie?\tAnswer: Tu."]


def test_qa_from_headings_when_no_text_pairs():
    bloki = [_head("Co to RAG?", 2), _para("Wyszukiwanie + generacja."), _head("Pusty?", 2)]
    drafty = chunk_blocks(bloki, preset_for("qa"), _cfg())
    assert [d.text for d in drafty] == [
        "Question: Co to RAG?\tAnswer: Wyszukiwanie + generacja.",
    ]
    assert drafty[0].questions == ("Co to RAG?",)
    assert drafty[0].chunk_type == "qa"


def test_qa_without_pairs_uses_naive():
    bloki = [_para("Zwykły akapit numer jeden."), _para("Zwykły akapit numer dwa.")]
    drafty = chunk_blocks(bloki, preset_for("qa"), _cfg())
    assert drafty == chunk_blocks(bloki, preset_for("naive"), _cfg())
    assert drafty[0].chunk_type == "text"


# -- table (C10.4) --


def test_table_manual_roles_text_and_metadata():
    drafty = chunk_blocks(
        [_table_block(_PRODUCT_TABLE)],
        preset_for("table"),
        _cfg(table_column_mode="manual", table_column_roles=_TABLE_ROLES),
    )
    assert [d.text for d in drafty] == ["Produkt: Mleko; Cena: 3.50", "Produkt: Chleb"]
    assert [dict(d.metadata) for d in drafty] == [
        {"Produkt": "Mleko", "SKU": "X1"},
        {"Produkt": "Chleb", "SKU": "X2"},
    ]
    for i, draft in enumerate(drafty):
        expected_html = (
            "<table>"
            + _PRODUCT_TABLE.header_html
            + "<tbody>"
            + _PRODUCT_TABLE.rows_html[i]
            + "</tbody></table>"
        )
        assert draft.html == expected_html
        assert draft.chunk_type == "table"
    assert [d.ordinal for d in drafty] == [0, 1]


def test_table_auto_mode_ignores_roles():
    drafty = chunk_blocks(
        [_table_block(_PRODUCT_TABLE)],
        preset_for("table"),
        _cfg(table_column_mode="auto", table_column_roles=_TABLE_ROLES),
    )
    assert drafty[0].text == "Produkt: Mleko; Cena: 3.50; SKU: X1"
    assert dict(drafty[0].metadata) == {"Produkt": "Mleko", "Cena": "3.50", "SKU": "X1"}


def test_table_row_with_empty_indexing_skipped():
    tabela = TableData(
        header=("Produkt", "Cena", "SKU"),
        rows=(("", "3.50", "X1"), ("Mleko", "3.50", "X2")),
        header_html=_PRODUCT_TABLE.header_html,
        rows_html=(
            "<tr><td></td><td>3.50</td><td>X1</td></tr>",
            "<tr><td>Mleko</td><td>3.50</td><td>X2</td></tr>",
        ),
    )
    roles = {"Cena": "metadata", "SKU": "metadata"}
    drafty = chunk_blocks(
        [_table_block(tabela)],
        preset_for("table"),
        _cfg(table_column_mode="manual", table_column_roles=roles),
    )
    assert [d.text for d in drafty] == ["Produkt: Mleko"]


def test_table_run_and_rows_ordinals():
    bloki = [_para("Opis produktów spożywczych."), _table_block(_PRODUCT_TABLE)]
    drafty = chunk_blocks(bloki, preset_for("table"), _cfg())
    assert [d.chunk_type for d in drafty] == ["text", "table", "table"]
    assert [d.ordinal for d in drafty] == [0, 1, 2]
    assert drafty[0].text == "Opis produktów spożywczych."


def test_table_row_over_max_tokens_split():
    dlugi_opis = " ".join([_LONG_SENTENCE] * LONG_SENTENCE_REPEATS)
    assert count_tokens(f"Produkt: Mleko; Opis: {dlugi_opis}") > ROW_MAX_TOKENS
    tabela = TableData(
        header=("Produkt", "Opis"),
        rows=(("Mleko", dlugi_opis),),
        header_html="<thead><tr><th>Produkt</th><th>Opis</th></tr></thead>",
        rows_html=(f"<tr><td>Mleko</td><td>{escape(dlugi_opis)}</td></tr>",),
    )
    drafty = chunk_blocks(
        [_table_block(tabela)], preset_for("table"), _cfg(max_tokens=ROW_MAX_TOKENS)
    )
    assert len(drafty) >= MIN_ROW_CHUNKS
    assert all(d.tokens <= ROW_MAX_TOKENS for d in drafty)
    assert all(dict(d.metadata) == {"Produkt": "Mleko", "Opis": dlugi_opis} for d in drafty)
    expected_html = (
        "<table>" + tabela.header_html + "<tbody>" + tabela.rows_html[0] + "</tbody></table>"
    )
    assert all(d.html == expected_html for d in drafty)


# -- strip_page_furniture (C10.5) --


_PAGE_CONTENT = (
    "Metodologia badań została opisana w pierwszej części opracowania.",
    "Wyniki eksperymentów zestawiono w tabelach analitycznych dodatku.",
    "Dyskusja wyników obejmuje kontekst wcześniejszych prac badawczych.",
    "Wnioski wskazują kierunki dalszych prac oraz ograniczenia metody.",
)


def _page_blocks() -> list[Block]:
    numery = ["Strona 1 z 4", "Page 2", "17", "Page 4 of 4"]
    bloki: list[Block] = []
    for numer in range(PAGE_COUNT):
        sekcja = f"page:{numer + 1}"
        bloki.append(_para("Journal of X, vol. 3", section=sekcja))
        bloki.append(_para(numery[numer], section=sekcja))
        bloki.append(_para(_PAGE_CONTENT[numer], section=sekcja))
        if numer < DEDICATION_PAGES:
            bloki.append(_para("Dedykacja dla rodziców.", section=sekcja))
    return bloki


def test_strip_page_furniture_removes_repeated_and_numbers():
    teksty = [b.text for b in strip_page_furniture(_page_blocks())]
    assert teksty == [
        _PAGE_CONTENT[0],
        "Dedykacja dla rodziców.",
        _PAGE_CONTENT[1],
        "Dedykacja dla rodziców.",
        _PAGE_CONTENT[2],
        _PAGE_CONTENT[3],
    ]
    assert len(teksty) == FURNITURE_CONTENT_COUNT


def test_paper_pipeline_removes_furniture():
    drafty = chunk_blocks(_page_blocks(), preset_for("paper"), _cfg())
    assert drafty
    assert all("Journal of X" not in d.text for d in drafty)
    assert all("Strona 1 z 4" not in d.text for d in drafty)
    assert all("Page 2" not in d.text for d in drafty)
    assert any(_PAGE_CONTENT[0] in d.text for d in drafty)
