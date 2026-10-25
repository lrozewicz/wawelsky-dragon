"""Testy kanonicznych kluczy chunków (C3.1; dodatek po BLOCKED T4 — determinizm)."""

from wdeval.seed import canonical_keys


def test_przyklad_z_dodatku_duplikaty_wspoldziela_min_ordinal() -> None:
    wiersze = [("a.pdf", 0, "x"), ("a.pdf", 1, "y"), ("a.pdf", 2, "x"), ("b.pdf", 0, "x")]
    assert canonical_keys(wiersze) == ["a.pdf#0", "a.pdf#1", "a.pdf#0", "b.pdf#0"]


def test_min_ordinal_niezalezny_od_kolejnosci_wejscia() -> None:
    """Najmniejszy ordinal duplikatu, nie pierwsze wystąpienie na liście."""
    wiersze = [("a.pdf", 3, "x"), ("a.pdf", 1, "x"), ("a.pdf", 2, "y")]
    assert canonical_keys(wiersze) == ["a.pdf#1", "a.pdf#1", "a.pdf#2"]


def test_identyczna_tresc_w_roznych_dokumentach_osobne_klucze() -> None:
    wiersze = [("a.pdf", 5, "x"), ("b.pdf", 2, "x")]
    assert canonical_keys(wiersze) == ["a.pdf#5", "b.pdf#2"]
