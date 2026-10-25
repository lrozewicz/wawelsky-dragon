"""Testy algorytmu general (CONTRACT WP E1-5 C6); prawdziwy tiktoken z app.llm.tokens."""

from collections import Counter
from html import escape

from app.domain.chunking.general import chunk_general
from app.domain.chunking.presets import preset_for
from app.domain.chunking.types import Block, BlockKind, ChunkConfig
from app.llm.tokens import count_tokens

# Nazwane stałe zamiast liczb magicznych (PLR2004).
LIMIT_128 = 128
LIMIT_100 = 100
LIMIT_200 = 200
PARAGRAPH_COUNT = 40
SENTENCE_MULTIPLIER = 200
WORD_MULTIPLIER = 75
CODE_MULTIPLIER = 100
MIN_CHUNKS_LONG = 8
MIN_CHUNKS_SOME = 2

_TEXT_X = "Pierwszy przykładowy akapit testowy zawiera kilka zwyczajnych słów opisowych."
_TEXT_Y = "Drugi przykładowy akapit testowy również zawiera kilka zwyczajnych słów opisowych."
_SEGMENT_1 = "a b c d e f g h"
_SEGMENT_2 = "i j k l m n o p"
_BACKTICK_TEXT = f"{_SEGMENT_1}###{_SEGMENT_2}"
_LAW_1 = "Art. 1. Pierwszy przepis ustawy zawiera treść wystarczająco długą."
_LAW_1_CONT = "Dalszy ciąg artykułu pierwszego."
_LAW_2 = "Art. 2. Drugi przepis reguluje zupełnie inny zakres spraw."
_SENTENCE = "Pies goni kaczkę ogrodem codziennie rano."
_WORDS = ("kot", "pies", "lew", "ryś", "wilk", "jeż", "łoś", "dzik")
_ABSTRACT = "Abstract"
_INTRO = "1. Introduction"
_PAPER_BODY = "W tym artykule przedstawiamy nową metodę oceny jakości systemów."
_POSITION_A = (2, 1, 2, 3, 4)
_POSITION_B = (3, 0, 0, 0, 0)


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


def _kind_block(kind: BlockKind, text: str) -> Block:
    if kind == "list":
        body = f"<ul><li>{escape(text)}</li></ul>"
    elif kind == "code":
        body = f"<pre><code>{escape(text)}</code></pre>"
    else:
        body = f"<figure><figcaption>{escape(text)}</figcaption></figure>"
    return Block(
        kind=kind,
        text=text,
        html=body,
        level=None,
        heading_path=(),
        positions=(),
        section=None,
        table=None,
    )


def _cfg(**overrides: object) -> ChunkConfig:
    return ChunkConfig(count_tokens=count_tokens, **overrides)


def _paragraph_text(i: int) -> str:
    return f"Akapit numer {i} zawiera przykładową treść testową o przebiegu eksperymentu."


def test_empty_blocks():
    assert chunk_general([], preset_for("naive"), _cfg()) == []


def test_heading_closes_chunk():
    drafty = chunk_general(
        [_head("A", 1), _para(_TEXT_X, ("A",)), _head("B", 1), _para(_TEXT_Y, ("B",))],
        preset_for("naive"),
        _cfg(),
    )
    assert len(drafty) == MIN_CHUNKS_SOME
    assert drafty[0].text.startswith("A\n")
    assert drafty[1].text.startswith("B\n")
    assert _TEXT_X in drafty[0].text
    assert _TEXT_Y in drafty[1].text
    assert drafty[0].heading_path == ("A",)
    assert drafty[1].heading_path == ("B",)
    assert all(d.ordinal == -1 for d in drafty)


def test_paragraphs_respect_token_limit_and_order():
    bloki = [_para(_paragraph_text(i), ("Rozdział",)) for i in range(PARAGRAPH_COUNT)]
    drafty = chunk_general(bloki, preset_for("naive"), _cfg(chunk_token_num=LIMIT_128))
    assert len(drafty) >= MIN_CHUNKS_SOME
    assert all(d.tokens <= LIMIT_128 for d in drafty)
    joined = "\n".join(d.text.removeprefix("Rozdział\n") for d in drafty)
    cursor = -1
    for i in range(PARAGRAPH_COUNT):
        cursor = joined.find(_paragraph_text(i), cursor + 1)
        assert cursor >= 0


def test_long_paragraph_split_by_sentences_words_intact():
    tekst = " ".join([_SENTENCE] * SENTENCE_MULTIPLIER)
    drafty = chunk_general([_para(tekst)], preset_for("naive"), _cfg(chunk_token_num=LIMIT_200))
    assert len(drafty) >= MIN_CHUNKS_LONG
    assert all(d.tokens <= LIMIT_200 for d in drafty)
    slowa = Counter(slowo for d in drafty for slowo in d.text.split())
    assert slowa == Counter(tekst.split())


def test_long_sentence_without_punctuation_split_by_words():
    tekst = " ".join(list(_WORDS) * WORD_MULTIPLIER)
    drafty = chunk_general([_para(tekst)], preset_for("naive"), _cfg(chunk_token_num=LIMIT_100))
    assert len(drafty) >= MIN_CHUNKS_SOME
    assert all(d.tokens <= LIMIT_100 for d in drafty)
    slowa = Counter(slowo for d in drafty for slowo in d.text.split())
    assert slowa == Counter(tekst.split())


def test_backtick_delimiter_segments_ignore_chunk_token_num():
    drafty = chunk_general(
        [_para(_BACKTICK_TEXT)], preset_for("naive"), _cfg(delimiter="`###`", chunk_token_num=1)
    )
    assert [d.text for d in drafty] == [_SEGMENT_1, _SEGMENT_2]
    assert all(d.chunk_type == "text" for d in drafty)


def test_manual_h4_is_content_not_boundary():
    bloki = [
        _head("A", 1),
        _para(_TEXT_X, ("A",)),
        _head("D", 4, ("A",)),
        _para(_TEXT_Y, ("A", "D")),
    ]
    drafty = chunk_general(bloki, preset_for("manual"), _cfg())
    assert len(drafty) == 1
    assert drafty[0].text.splitlines() == ["A", _TEXT_X, "D", _TEXT_Y]
    assert drafty[0].heading_path == ("A",)
    assert drafty[0].chunk_type == "text"


def test_book_h3_not_boundary_but_naive_splits():
    bloki = [
        _head("A", 1),
        _para(_TEXT_X, ("A",)),
        _head("S", 3, ("A",)),
        _para(_TEXT_Y, ("A", "S")),
    ]
    book = chunk_general(bloki, preset_for("book"), _cfg())
    naive = chunk_general(bloki, preset_for("naive"), _cfg())
    assert len(book) == 1
    assert book[0].text.splitlines() == ["A", _TEXT_X, "S", _TEXT_Y]
    assert len(naive) == MIN_CHUNKS_SOME
    assert naive[1].text.splitlines() == ["A > S", _TEXT_Y]
    assert naive[1].heading_path == ("A", "S")


def test_laws_article_boundaries():
    bloki = [_para(_LAW_1), _para(_LAW_1_CONT), _para(_LAW_2)]
    drafty = chunk_general(bloki, preset_for("laws"), _cfg())
    assert len(drafty) == MIN_CHUNKS_SOME
    assert drafty[0].text.splitlines() == [_LAW_1, _LAW_1_CONT]
    assert drafty[1].text.splitlines() == [_LAW_2]


def test_paper_section_boundaries():
    bloki = [_para(_ABSTRACT), _para(_PAPER_BODY), _para(_INTRO), _para(_PAPER_BODY)]
    drafty = chunk_general(bloki, preset_for("paper"), _cfg())
    assert len(drafty) == MIN_CHUNKS_SOME
    assert drafty[0].text.startswith(_ABSTRACT)
    assert drafty[1].text.startswith(_INTRO)


def test_chunk_types_by_block_kind():
    listy = chunk_general(
        [_kind_block("list", "Punkt pierwszy."), _kind_block("list", "Punkt drugi.")],
        preset_for("naive"),
        _cfg(),
    )
    assert len(listy) == 1
    assert listy[0].chunk_type == "list"
    kod = chunk_general([_kind_block("code", "print(1)")], preset_for("naive"), _cfg())
    assert kod[0].chunk_type == "code"
    figura = chunk_general([_kind_block("figure", "Wykres wzrostu.")], preset_for("naive"), _cfg())
    assert figura[0].chunk_type == "image"
    mieszane = chunk_general(
        [_para(_TEXT_X), _kind_block("list", "Punkt trzeci.")], preset_for("naive"), _cfg()
    )
    assert len(mieszane) == 1
    assert mieszane[0].chunk_type == "text"


def test_positions_collected_in_order_without_duplicates():
    bloki = [
        _para(_TEXT_X, positions=(_POSITION_A,)),
        _para(_TEXT_Y, positions=(_POSITION_B,)),
        _para(_TEXT_X, positions=(_POSITION_A,)),
    ]
    drafty = chunk_general(bloki, preset_for("naive"), _cfg())
    assert len(drafty) == 1
    assert drafty[0].positions == (_POSITION_A, _POSITION_B)


def test_blocks_without_positions_give_empty_positions():
    drafty = chunk_general([_para(_TEXT_X)], preset_for("naive"), _cfg())
    assert drafty[0].positions == ()
    assert drafty[0].page_from is None
    assert drafty[0].page_to is None


def test_whitespace_only_block_skipped():
    drafty = chunk_general([_para("   "), _para(_TEXT_X)], preset_for("naive"), _cfg())
    assert len(drafty) == 1
    assert drafty[0].text == _TEXT_X


def test_block_html_reused_for_single_piece():
    blok = Block(
        kind="paragraph",
        text=_TEXT_X,
        html=f'<p class="lead">{escape(_TEXT_X)}</p>',
        level=None,
        heading_path=(),
        positions=(),
        section=None,
        table=None,
    )
    drafty = chunk_general([blok], preset_for("naive"), _cfg())
    assert len(drafty) == 1
    assert drafty[0].html == blok.html


def test_generated_html_for_split_paragraph_pieces():
    tekst = " ".join([_SENTENCE] * SENTENCE_MULTIPLIER)
    drafty = chunk_general([_para(tekst)], preset_for("naive"), _cfg(chunk_token_num=LIMIT_200))
    assert all(d.html.startswith("<p>") and d.html.endswith("</p>") for d in drafty)
    assert escape(_SENTENCE) in drafty[0].html


def test_generated_html_for_split_code_pieces():
    kod = _kind_block("code", " ".join(["print", "value", "return"] * CODE_MULTIPLIER))
    drafty = chunk_general([kod], preset_for("naive"), _cfg(chunk_token_num=LIMIT_200))
    assert len(drafty) >= MIN_CHUNKS_SOME
    assert all(d.chunk_type == "code" for d in drafty)
    assert all(
        d.html.startswith("<pre><code>") and d.html.endswith("</code></pre>") for d in drafty
    )
