"""Testy chunk_blocks — dispatch, fallback i pełny pipeline (CONTRACT WP E1-5 C9)."""

from html import escape

from app.domain.chunking.chunker import chunk_blocks
from app.domain.chunking.presets import preset_for
from app.domain.chunking.types import Block, ChunkConfig, TableData
from app.llm.tokens import count_tokens

# Nazwane stałe zamiast liczb magicznych (PLR2004).
LIMIT_128 = 128
PARAGRAPH_COUNT = 40
MIN_CHUNKS_SOME = 2
_PAGE_A = 2
_PAGE_B = 3

_TEXT_X = "Pierwszy przykładowy akapit testowy zawiera kilka zwyczajnych słów opisowych."
_TEXT_Y = "Drugi przykładowy akapit testowy również zawiera kilka zwyczajnych słów opisowych."
_POSITION_A = (_PAGE_A, 1, 2, 3, 4)
_POSITION_B = (_PAGE_B, 0, 0, 0, 0)

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


def _para(text: str, path: tuple[str, ...] = (), positions: tuple = ()) -> Block:
    return Block(
        kind="paragraph",
        text=text,
        html=f"<p>{escape(text)}</p>",
        level=None,
        heading_path=path,
        positions=positions,
        section=None,
        table=None,
    )


def _head(text: str, level: int, path: tuple[str, ...] = ()) -> Block:
    return Block(
        kind="heading",
        text=text,
        html=f"<h{level}>{escape(text)}</h{level}>",
        level=level,
        heading_path=path,
        positions=(),
        section=None,
        table=None,
    )


def _table_block(t: TableData, path: tuple[str, ...] = ()) -> Block:
    full_html = f"<table>{t.header_html}<tbody>{''.join(t.rows_html)}</tbody></table>"
    text = "\n".join([" | ".join(t.header)] + [" | ".join(r) for r in t.rows])
    return Block(
        kind="table",
        text=text,
        html=full_html,
        level=None,
        heading_path=path,
        positions=(),
        section=None,
        table=t,
    )


def _cfg(**overrides: object) -> ChunkConfig:
    return ChunkConfig(count_tokens=count_tokens, **overrides)


def _paragraph_text(i: int) -> str:
    return f"Akapit numer {i} zawiera przykładową treść testową o przebiegu eksperymentu."


def test_empty_blocks_give_no_chunks():
    assert chunk_blocks([], preset_for("naive"), _cfg()) == []


def test_naive_pipeline_breadcrumb_and_ordinal():
    bloki = [_head("Wstęp", 1), _para("Ala ma kota. Kot ma Alę.", ("Wstęp",))]
    drafty = chunk_blocks(bloki, preset_for("naive"), _cfg())
    assert len(drafty) == 1
    assert drafty[0].text == "Wstęp\nAla ma kota. Kot ma Alę."
    assert drafty[0].html.startswith('<p class="breadcrumb">Wstęp</p>')
    assert drafty[0].heading_path == ("Wstęp",)
    assert drafty[0].ordinal == 0
    assert drafty[0].chunk_type == "text"
    assert drafty[0].page_from is None
    assert drafty[0].page_to is None


def test_fallback_only_headings():
    drafty = chunk_blocks([_head("A", 1), _head("B", 2, ("A",))], preset_for("naive"), _cfg())
    assert len(drafty) == 1
    assert drafty[0].text == "A\nB"
    assert drafty[0].html == "<h1>A</h1><h2>B</h2>"
    assert drafty[0].heading_path == ()
    assert drafty[0].ordinal == 0
    assert drafty[0].chunk_type == "text"


def test_fallback_empty_text_gives_no_chunks():
    assert chunk_blocks([_para("   ")], preset_for("naive"), _cfg()) == []


def test_deterministic_results_with_table():
    bloki = [
        _para(_TEXT_X, ("Rozdział",)),
        _table_block(_SMALL_TABLE),
        _para(_TEXT_Y, ("Rozdział",)),
    ]
    wynik_1 = chunk_blocks(bloki, preset_for("naive"), _cfg())
    wynik_2 = chunk_blocks(bloki, preset_for("naive"), _cfg())
    assert wynik_1 == wynik_2
    assert [d.chunk_type for d in wynik_1] == ["text", "table", "text"]


def test_paragraph_ordinals_limits_and_order():
    bloki = [_para(_paragraph_text(i), ("Rozdział",)) for i in range(PARAGRAPH_COUNT)]
    drafty = chunk_blocks(bloki, preset_for("naive"), _cfg(chunk_token_num=LIMIT_128))
    assert len(drafty) >= MIN_CHUNKS_SOME
    assert [d.ordinal for d in drafty] == list(range(len(drafty)))
    assert all(d.tokens <= LIMIT_128 for d in drafty)
    joined = "\n".join(d.text.removeprefix("Rozdział\n") for d in drafty)
    cursor = -1
    for i in range(PARAGRAPH_COUNT):
        cursor = joined.find(_paragraph_text(i), cursor + 1)
        assert cursor >= 0


def test_positions_pages_from_min_to_max():
    bloki = [
        _para(_TEXT_X, ("Rozdział",), (_POSITION_A,)),
        _para(_TEXT_Y, ("Rozdział",), (_POSITION_B,)),
    ]
    drafty = chunk_blocks(bloki, preset_for("naive"), _cfg())
    assert len(drafty) == 1
    assert drafty[0].positions == (_POSITION_A, _POSITION_B)
    assert drafty[0].page_from == _PAGE_A
    assert drafty[0].page_to == _PAGE_B
    assert drafty[0].ordinal == 0
