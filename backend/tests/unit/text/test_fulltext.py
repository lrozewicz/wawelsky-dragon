"""Testy normalizacji tekstu pod FULLTEXT MariaDB (app.text.fulltext)."""

from __future__ import annotations

import pytest

from app.text import fulltext


def test_stem_text_przypadek_wiazacy() -> None:
    assert fulltext.stem_text("Najwyższy szczyt Tatr i zażółć gęślą jaźń 2024") == (
        "najwysoki szczyt tatra i zazolcic geslic jazn 2024"
    )


def test_stem_text_pusty_tekst() -> None:
    assert fulltext.stem_text("") == ""


def test_stem_text_tylko_interpunkcja() -> None:
    assert fulltext.stem_text("   ,.;  ") == ""


def test_ft_text_nfc_i_biale_znaki() -> None:
    # NFC składa "e" + U+0301 w "é"; podwójna spacja i tab → jedna spacja.
    assert fulltext.ft_text("é  gęślą\tjaźń") == "é gęślą jaźń"


def test_ft_text_usuwa_znaki_sterujace() -> None:
    assert fulltext.ft_text("a\x00b\x07c") == "abc"


def test_ft_text_zawija_nowe_linie() -> None:
    assert fulltext.ft_text("linia 1\r\n\r\n\r\n\r\nlinia 2  ") == "linia 1\n\nlinia 2"


def test_ft_text_laczy_podwojne_spacje() -> None:
    assert fulltext.ft_text("Ala ma  kota") == "Ala ma kota"


def test_ft_text_zachowuje_wielkosc_i_diakrytyki() -> None:
    assert fulltext.ft_text("Łódź") == "Łódź"


def test_fold_polskie_znaki() -> None:
    assert fulltext.fold("Łódź ŻÓŁW, 2024!") == "lodz zolw 2024"


def test_fold_pusty_tekst() -> None:
    assert fulltext.fold("") == ""


def test_stemmer_zwraca_ten_sam_obiekt() -> None:
    assert fulltext._stemmer() is fulltext._stemmer()


def test_stem_text_token_bez_znakow_ascii_po_fold() -> None:
    # "___" to token (\w+), ale fold daje z niego "" — taki wynik jest pomijany.
    assert fulltext.stem_text("___ 2024") == "2024"


def test_stem_text_fallback_gdy_stemmer_niczego_nie_zwroci(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gdy stem() zwróci None lub "", token wchodzi bez zmian."""

    class _Stub:
        def stem(self, word: str) -> str | None:
            return None if word == "ala" else ""

    monkeypatch.setattr(fulltext, "_stemmer", _Stub)
    assert fulltext.stem_text("Ala ma") == "ala ma"
