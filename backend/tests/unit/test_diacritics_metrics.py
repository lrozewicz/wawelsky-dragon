"""Testy jednostkowe metryki diakrytyków (T5a, bez I/O, sieci i plików spoza repo)."""

from tests.unit.diacritics_metrics import (
    build_gt,
    classify_change,
    nums,
    score_text,
    word_changes,
)


def test_score_text_counts_ok_and_bad() -> None:
    """GT „Ogółem kobiety": do metryki wchodzą tylko słowa z diakrytykami (DEC-250)."""
    gt = build_gt(["Ogółem kobiety"])
    ok, bad, errors = score_text("Ogółem ogólem kobiety", gt)
    assert (ok, bad) == (1, 1)
    assert errors["ogólem→ogółem"] == 1
    # „kobiety" nie wnosi diakrytyków — metryka je pomija (DEC-250).
    assert score_text("Ogólem kobiety", gt)[:2] == (0, 1)


def test_nums_extracts_decimals() -> None:
    """``nums`` wyciąga liczby całkowite i dziesiętne (kropka i przecinek)."""
    assert nums("w 2019 było 10,8 i 13 oraz 1.5, suma 136") == [
        "2019",
        "10,8",
        "13",
        "1.5",
        "136",
    ]


def test_classify_change_fix_vs_false() -> None:
    """``ogólem→ogółem`` to poprawka, a usunięcie diakrytyku z poprawnego słowa to fałszywka."""
    gt = build_gt(["Ogółem końcu"])
    vocab = {"ogółem", "końcu"}
    assert classify_change("ogólem", "ogółem", vocab, gt) == "fix"
    assert classify_change("końcu", "koncu", vocab, gt) == "false"


def test_word_changes_pairs() -> None:
    """``word_changes`` zwraca pary zmienionych słów, bez słów równych."""
    assert word_changes("ogólem kobiety pracę", "ogółem kobiety pracę") == [("ogólem", "ogółem")]
