"""Testy przekrojowe: html_to_blocks → chunk_blocks (CONTRACT WP E1-5 C9-C11)."""

import pytest

from app.domain.chunking.chunker import chunk_blocks
from app.domain.chunking.errors import DocumentTooLarge, UnsupportedChunkMethod
from app.domain.chunking.presets import preset_for
from app.domain.chunking.types import ChunkConfig
from app.llm.tokens import count_tokens
from app.parsing.blocks import html_to_blocks

# Nazwane stałe zamiast liczb magicznych (PLR2004).
NAIVE_TOKEN_NUM = 128
TABLE_ROWS = 50
MIN_TABLE_CHUNKS = 2
ONE_MAX_TOKENS = 8000
BIG_DOC_TARGET_TOKENS = 9000
UNSUPPORTED_CODE = 101

_ALL_METHODS = (
    "naive",
    "manual",
    "book",
    "laws",
    "paper",
    "presentation",
    "one",
    "qa",
    "table",
    "picture",
    "email",
)
_UNSUPPORTED = ("tag", "knowledge_graph", "resume", "audio")

_BIG_SENTENCE = "Akapit opisuje przebieg długiego eksperymentu badawczego i jego wyniki końcowe."

_SMALL_HTML = (
    '<section data-page="1"><h1>Dokument</h1>'
    "<p>Treść dokumentu w kilku zdaniach opisujących temat.</p>"
    "<p>Q: Co to RAG?<br>A: Wyszukiwanie plus generacja.</p>"
    "<ul><li>punkt pierwszy</li><li>punkt drugi</li></ul>"
    "<table><thead><tr><th>Pytanie</th><th>Odpowiedź</th></tr></thead>"
    "<tbody><tr><td>Ile?</td><td>Dwa.</td></tr></tbody></table>"
    "</section>"
)

_XLSX_HTML = (
    '<section data-sheet="S1"><table><tr><td>Pytanie 1?</td><td>Odp 1.</td></tr>'
    "<tr><td>Pytanie 2?</td><td>Odp 2.</td></tr></table></section>"
)


def _cfg(**overrides: object) -> ChunkConfig:
    return ChunkConfig(count_tokens=count_tokens, **overrides)


def _big_doc() -> str:
    """Dwa sekcje data-page: h1/h2, 8 akapitów z data-bbox, lista, tabela 50 wierszy (thead)."""
    parts = ['<section data-page="1">', "<h1>Raport</h1>", "<h2>Wstęp</h2>"]
    for i in range(4):
        parts.append(f'<p data-bbox="10,{20 + i},300,{40 + i}">Akapit {i} opisuje badanie.</p>')
    parts.append("<ul><li>punkt pierwszy</li><li>punkt drugi</li></ul>")
    parts.append("</section>")
    parts.append('<section data-page="2">')
    for i in range(4, 8):
        parts.append(f'<p data-bbox="10,{20 + i},300,{40 + i}">Akapit {i} opisuje badanie.</p>')
    parts.append("<table><thead><tr><th>Produkt</th><th>Cena</th></tr></thead><tbody>")
    for i in range(TABLE_ROWS):
        parts.append(f"<tr><td>Produkt numer {i}</td><td>{i}.50</td></tr>")
    parts.append("</tbody></table></section>")
    return "".join(parts)


def test_naive_pipeline_tables_limits_and_ordinals():
    drafty = chunk_blocks(
        html_to_blocks(_big_doc()), preset_for("naive"), _cfg(chunk_token_num=NAIVE_TOKEN_NUM)
    )
    assert drafty
    tabele = [d for d in drafty if d.chunk_type == "table"]
    assert len(tabele) >= MIN_TABLE_CHUNKS
    assert all("<thead>" in d.html for d in tabele)
    assert all(d.tokens <= NAIVE_TOKEN_NUM for d in drafty)
    assert all(d.text.startswith("Raport > Wstęp") for d in drafty)
    assert [d.ordinal for d in drafty] == list(range(len(drafty)))
    strony = {d.page_from for d in drafty} | {d.page_to for d in drafty}
    assert strony <= {1, 2}


def test_pipeline_deterministic():
    bloki = html_to_blocks(_big_doc())
    wynik_1 = chunk_blocks(bloki, preset_for("naive"), _cfg(chunk_token_num=NAIVE_TOKEN_NUM))
    wynik_2 = chunk_blocks(bloki, preset_for("naive"), _cfg(chunk_token_num=NAIVE_TOKEN_NUM))
    assert wynik_1 == wynik_2


@pytest.mark.parametrize("method", _ALL_METHODS)
def test_every_preset_produces_chunks(method: str):
    drafty = chunk_blocks(html_to_blocks(_SMALL_HTML), preset_for(method), _cfg())
    assert len(drafty) >= 1


@pytest.mark.parametrize("method", _UNSUPPORTED)
def test_unsupported_methods_raise(method: str):
    with pytest.raises(UnsupportedChunkMethod) as exc_info:
        preset_for(method)
    assert exc_info.value.code == UNSUPPORTED_CODE


def test_qa_from_xlsx_like_html():
    drafty = chunk_blocks(html_to_blocks(_XLSX_HTML), preset_for("qa"), _cfg())
    assert [d.text for d in drafty] == [
        "Question: Pytanie 1?\tAnswer: Odp 1.",
        "Question: Pytanie 2?\tAnswer: Odp 2.",
    ]
    assert all(d.chunk_type == "qa" for d in drafty)


def test_qa_from_txt_md_like_html():
    html = "<p>Q: Ile masz lat?<br>A: Dwadzieścia trzy lata.</p>"
    drafty = chunk_blocks(html_to_blocks(html), preset_for("qa"), _cfg())
    assert [d.text for d in drafty] == ["Question: Ile masz lat?\tAnswer: Dwadzieścia trzy lata."]


def test_one_over_limit_html():
    powtorzen = -(-BIG_DOC_TARGET_TOKENS // count_tokens(_BIG_SENTENCE)) + 1
    html = "".join(f"<p>{_BIG_SENTENCE}</p>" for _ in range(powtorzen))
    with pytest.raises(DocumentTooLarge):
        chunk_blocks(html_to_blocks(html), preset_for("one"), _cfg(max_tokens=ONE_MAX_TOKENS))
