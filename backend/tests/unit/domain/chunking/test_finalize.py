"""Testy finalizacji: merge_small, apply_overlap, finalize (CONTRACT WP E1-5 C8); tiktoken."""

from html import escape

from app.domain.chunking.chunker import chunk_blocks
from app.domain.chunking.finalize import MIN_CHUNK_TOKENS, apply_overlap, finalize, merge_small
from app.domain.chunking.limits import split_sentences
from app.domain.chunking.presets import preset_for
from app.domain.chunking.types import Block, ChunkConfig, ChunkDraft
from app.llm.tokens import count_tokens

# Nazwane stałe zamiast liczb magicznych (PLR2004).
MIN_TOKENS_EXPECTED = 8
OVERLAP_PCT = 20
LIMIT_100 = 100
TOLERANCE_5 = 5
OVERLAP_PARAGRAPHS = 30
MIN_CHUNKS_SOME = 2

_LONG_TEXT = "To jest dłuższy tekst testowy, który zdecydowanie przekracza próg ośmiu tokenów."
_LONG_TEXT_2 = "Drugi długi tekst testowy, który również przekracza próg ośmiu tokenów."
_OK = "ok."
_PATH = ("Rozdział",)
_POSITION_D0 = ((1, 0, 0, 0, 0),)
_POSITION_D1 = ((2, 0, 0, 0, 0),)
_PAGE_MIN = 1
_PAGE_MAX = 3
# Zdania po 6 tokenów: ostatnie zdanie mieści się w budżecie overlapu 20% (ceil(body*0.2) = 6).
_SENTENCES_A = [
    "Ala ma kota.",
    "Kot ma Alę.",
    "Pies ma kość.",
    "Ola ma psa.",
    "Ula ma lwa.",
]
_SENTENCES_B = [
    "Ola ma kota.",
    "Ula ma psa.",
    "Ela ma psa.",
    "Ola ma lwa.",
    "Ula ma lwa.",
]


def _body(sentences: list[str]) -> str:
    return " ".join(sentences)


def _draft(
    text: str, chunk_type: str = "text", positions: tuple = (), path: tuple[str, ...] = ()
) -> ChunkDraft:
    return ChunkDraft(
        ordinal=-1,
        text=text,
        html=f"<p>{escape(text)}</p>",
        chunk_type=chunk_type,  # type: ignore[arg-type]
        heading_path=path,
        positions=positions,
        page_from=None,
        page_to=None,
        tokens=count_tokens(text),
        questions=(),
        metadata={},
    )


def _table_draft() -> ChunkDraft:
    return _draft("<table><tbody>wiersze danych tabeli</tbody></table>", chunk_type="table")


def _cfg(**overrides: object) -> ChunkConfig:
    return ChunkConfig(count_tokens=count_tokens, **overrides)


def _para(text: str) -> Block:
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


def _expected_overlap(body_prev: str, body_cur: str, path: tuple[str, ...]) -> str:
    """Wzór z CONTRACT C8: najdłuższy sufiks zdań poprzednika w budżecie ceil(pct% tokenów)."""
    prefix = " > ".join(path) + "\n" if path else ""
    budzet = -(-(count_tokens(body_prev) * OVERLAP_PCT) // 100)
    sufiks = ""
    okno: list[str] = []
    for zdanie in reversed(split_sentences(body_prev)):
        okno.insert(0, zdanie)
        kandydat = " ".join(okno)
        if count_tokens(kandydat) > budzet:
            break
        sufiks = kandydat
    return prefix + sufiks + "\n" + body_cur


def _paragraph_text(i: int) -> str:
    return f"Akapit numer {i} zawiera przykładową treść testową o przebiegu eksperymentu."


def test_min_chunk_tokens_constant():
    assert MIN_CHUNK_TOKENS == MIN_TOKENS_EXPECTED


def test_merge_small_into_previous():
    d0 = _draft(_LONG_TEXT, positions=_POSITION_D0)
    d1 = _draft(_OK, positions=_POSITION_D1)
    wynik = merge_small([d0, d1], _cfg())
    assert len(wynik) == 1
    assert wynik[0].text == d0.text + "\n" + d1.text
    assert wynik[0].positions == _POSITION_D0
    assert wynik[0].tokens == count_tokens(wynik[0].text)


def test_merge_small_into_next():
    d0 = _draft(_OK, positions=_POSITION_D0)
    d1 = _draft(_LONG_TEXT, positions=_POSITION_D1)
    wynik = merge_small([d0, d1], _cfg())
    assert len(wynik) == 1
    assert wynik[0].text == d0.text + "\n" + d1.text
    assert wynik[0].positions == _POSITION_D1


def test_merge_small_prefers_previous_over_next():
    drafty = [_draft(_LONG_TEXT), _draft(_OK), _draft(_LONG_TEXT_2)]
    wynik = merge_small(drafty, _cfg())
    assert len(wynik) == MIN_CHUNKS_SOME
    assert wynik[0].text == _LONG_TEXT + "\n" + _OK
    assert wynik[1].text == _LONG_TEXT_2


def test_merge_small_kept_between_tables():
    drafty = [_table_draft(), _draft(_OK), _table_draft()]
    wynik = merge_small(drafty, _cfg())
    assert wynik == drafty


def test_merge_small_kept_without_neighbors():
    drafty = [_draft(_OK)]
    assert merge_small(drafty, _cfg()) == drafty


def test_merge_small_respects_max_tokens():
    d0 = _draft(_LONG_TEXT)
    d1 = _draft(_OK)
    cfg = _cfg(max_tokens=count_tokens(_LONG_TEXT))
    wynik = merge_small([d0, d1], cfg)
    assert wynik == [d0, d1]


def test_apply_overlap_appends_sentence_suffix():
    body_a = _body(_SENTENCES_A)
    body_b = _body(_SENTENCES_B)
    d0 = _draft("Rozdział\n" + body_a, path=_PATH)
    d1 = _draft("Rozdział\n" + body_b, path=_PATH)
    wynik = apply_overlap([d0, d1], _cfg(overlapped_percent=OVERLAP_PCT))
    assert wynik[0] == d0
    assert wynik[1].text == _expected_overlap(body_a, body_b, _PATH)
    assert wynik[1].html == d1.html


def test_apply_overlap_without_breadcrumb():
    body_a = _body(_SENTENCES_A)
    body_b = _body(_SENTENCES_B)
    d0 = _draft(body_a)
    d1 = _draft(body_b)
    wynik = apply_overlap([d0, d1], _cfg(overlapped_percent=OVERLAP_PCT))
    assert wynik[1].text == _expected_overlap(body_a, body_b, ())


def test_apply_overlap_uses_original_previous():
    body_a = _body(_SENTENCES_A)
    body_b = _body(_SENTENCES_B)
    body_c = _body(_SENTENCES_A[:3])
    drafty = [
        _draft(body_a, path=_PATH),
        _draft(body_b, path=_PATH),
        _draft(body_c, path=_PATH),
    ]
    wynik = apply_overlap(drafty, _cfg(overlapped_percent=OVERLAP_PCT))
    assert wynik[1].text == _expected_overlap(body_a, body_b, _PATH)
    assert wynik[2].text == _expected_overlap(body_b, body_c, _PATH)


def test_apply_overlap_zero_percent_no_change():
    d0 = _draft(_LONG_TEXT)
    d1 = _draft(_LONG_TEXT_2)
    assert apply_overlap([d0, d1], _cfg()) == [d0, d1]


def test_apply_overlap_skips_tables():
    drafty = [_draft(_LONG_TEXT), _table_draft(), _table_draft(), _draft(_LONG_TEXT_2)]
    wynik = apply_overlap(drafty, _cfg(overlapped_percent=OVERLAP_PCT))
    assert wynik == drafty


def test_apply_overlap_sentence_over_budget_no_overlap():
    poprzednik = _draft(" ".join(["kot", "pies", "lew", "ryś", "wilk", "jeż"] * 10))
    nastepny = _draft(_LONG_TEXT_2)
    wynik = apply_overlap([poprzednik, nastepny], _cfg(overlapped_percent=OVERLAP_PCT))
    assert wynik[1].text == nastepny.text


def test_finalize_ordinals_and_pages():
    d0 = _draft(_LONG_TEXT, positions=((_PAGE_MAX, 1, 1, 1, 1), (_PAGE_MIN, 0, 0, 0, 0)))
    d1 = _draft(_LONG_TEXT_2, positions=((_PAGE_MIN, 5, 5, 5, 5),))
    wynik = finalize([d0, d1])
    assert [d.ordinal for d in wynik] == [0, 1]
    assert wynik[0].page_from == _PAGE_MIN
    assert wynik[0].page_to == _PAGE_MAX
    assert wynik[1].page_from == _PAGE_MIN
    assert wynik[1].page_to == _PAGE_MIN


def test_finalize_without_positions():
    wynik = finalize([_draft(_LONG_TEXT)])
    assert wynik[0].ordinal == 0
    assert wynik[0].page_from is None
    assert wynik[0].page_to is None


def test_chunk_blocks_overlap_within_tolerance():
    bloki = [_para(_paragraph_text(i)) for i in range(OVERLAP_PARAGRAPHS)]
    cfg = _cfg(chunk_token_num=LIMIT_100, overlapped_percent=OVERLAP_PCT)
    drafty = chunk_blocks(bloki, preset_for("naive"), cfg)
    assert len(drafty) >= MIN_CHUNKS_SOME
    assert all(d.tokens <= LIMIT_100 + TOLERANCE_5 for d in drafty)
