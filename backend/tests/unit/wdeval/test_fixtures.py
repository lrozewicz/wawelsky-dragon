"""Testy mini-korpusu (kontrakt C14): pliki istnieją, PDF czytelny, pozycje wg schematu."""

from __future__ import annotations

import io
from pathlib import Path

import pdfplumber

from wdeval.dataset import validate_schema
from wdeval.fixtures import build_mini_corpus

_DRAGON_SENTENCE = "Smok Wawelski mieszkal w jamie pod Wawelem."
_EN_SENTENCE = "The dragon was defeated by a shoemaker named Skuba."
_MIN_PAGE_TEXT = 150  # strona tekstowa (E1-4 05 §8.2)


def test_mini_korpus_pliki_i_pdf_czytelny(tmp_path: Path) -> None:
    _items, _docs = build_mini_corpus(tmp_path)
    assert (tmp_path / "mini.pdf").exists()
    assert (tmp_path / "mini-en.txt").exists()

    with pdfplumber.open(io.BytesIO((tmp_path / "mini.pdf").read_bytes())) as pdf:
        assert len(pdf.pages) == 1
        text = pdf.pages[0].extract_text() or ""
    assert _DRAGON_SENTENCE in text
    assert len(text) >= _MIN_PAGE_TEXT

    txt = (tmp_path / "mini-en.txt").read_text(encoding="utf-8")
    assert _EN_SENTENCE in txt


def test_mini_korpus_pozycje_walidne(tmp_path: Path) -> None:
    items, _docs = build_mini_corpus(tmp_path)
    assert validate_schema(items) == []

    by_id = {item.id: item for item in items}
    assert set(by_id) == {"mini-pl-01", "mini-en-01", "mini-un-01"}

    pl_item = by_id["mini-pl-01"]
    assert pl_item.answerable is True
    assert pl_item.language == "pl"
    assert pl_item.group == "narrative"
    assert pl_item.sources[0].file == "mini.pdf"
    assert pl_item.sources[0].fragment == "jamie pod Wawelem"

    en_item = by_id["mini-en-01"]
    assert en_item.answerable is True
    assert en_item.language == "en"
    assert en_item.group == "codex-gold"
    assert en_item.source == "codex-gold"
    assert en_item.sources[0].file == "mini-en.txt"
    assert en_item.sources[0].fragment == "shoemaker named Skuba"

    un_item = by_id["mini-un-01"]
    assert un_item.answerable is False
    assert un_item.expected_answer is None
    assert un_item.sources == []


def test_mini_korpus_dokumenty_posortowane_po_nazwie(tmp_path: Path) -> None:
    _items, docs = build_mini_corpus(tmp_path)
    assert [doc.name for doc in docs] == ["mini-en.txt", "mini.pdf"]
    for doc in docs:
        assert doc.path is not None
        assert doc.path.exists()
        assert doc.data is None
