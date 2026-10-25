"""Testy rdzenia korekty diakrytyków (CONTRACT WP E5-H4b §1, DEC-248)."""

import re

import pytest

from app.parsing.diacritics import (
    correct_with_layer,
    fold,
    fuse,
    split_segments,
)

_EXAMPLE_HTML = "<td>ogólem</td>\n<td>10,8</td>"
_EXAMPLE_PARTS = ["<td>", "ogólem", "</td>", "\n", "<td>", "10,8", "</td>"]
_EXAMPLE_EDITABLE = [1]

_TAG_RE = re.compile(r"<[^>]+>")
_NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")


def test_fold() -> None:
    assert fold("Ogółem") == "ogolem"
    assert fold("Mężczyźni") == "mezczyzni"


def test_split_segments_roundtrip() -> None:
    for text in ("", "bez tagów", _EXAMPLE_HTML, "<p>a\nb</p>", "<td></td>"):
        parts, _editable = split_segments(text)
        assert "".join(parts) == text


def test_split_segments_editable() -> None:
    parts, editable = split_segments(_EXAMPLE_HTML)
    assert parts == _EXAMPLE_PARTS
    assert editable == _EXAMPLE_EDITABLE


def test_fuse_accepts_diacritics_fix() -> None:
    assert fuse("10,8 ogólem", "10,8 ogółem") == ("10,8 ogółem", None)


def test_fuse_rejects_changed_number() -> None:
    assert fuse("10,8 ogólem", "11,8 ogółem") == ("10,8 ogólem", "numbers")


def test_fuse_rejects_markup_change() -> None:
    assert fuse("_ogólem_", "ogółem") == ("_ogólem_", "markup")


def test_fuse_rejects_new_newline() -> None:
    assert fuse("a ogólem", "a\nogółem") == ("a ogólem", "layout")


def test_fuse_rejects_rewrite() -> None:
    accepted, reason = fuse("ogólem razem", "zupelnie inny tekst tu")
    assert accepted == "ogólem razem"
    assert reason in {"rewrite", "content"}


def test_fuse_missing() -> None:
    assert fuse("x", None) == ("x", "missing")


def test_layer_fixes_diacritics() -> None:
    assert correct_with_layer("<p>Ogólem 10,8</p>", "Ogółem 10,8") == "<p>Ogółem 10,8</p>"


def test_layer_resolves_by_position() -> None:
    html = "<p>osoby szukajace prace oraz prace sezonowe</p>"
    layer = "osoby szukające pracę oraz prace sezonowe"
    assert correct_with_layer(html, layer) == "<p>osoby szukające pracę oraz prace sezonowe</p>"


def test_layer_empty_layer_noop() -> None:
    assert correct_with_layer("<td>ogólem</td>", "") == "<td>ogólem</td>"
    assert correct_with_layer("<td>ogólem</td>", "   \n ") == "<td>ogólem</td>"


@pytest.mark.parametrize(
    ("text", "layer"),
    [
        ("<td>2022</td>", "2023 ogółem"),
        ("<p>Ogólem 10,8</p>", "Ogółem 10,8"),
        ("<table><tr><td>ogólem</td></tr></table>", "ogółem 1 234,5"),
        ("<td>12,5%</td>", "12,5% ogółem"),
    ],
)
def test_layer_never_touches_numbers_or_tags(text: str, layer: str) -> None:
    result = correct_with_layer(text, layer)
    assert _TAG_RE.findall(result) == _TAG_RE.findall(text)
    assert _NUM_RE.findall(result) == _NUM_RE.findall(text)


def test_layer_no_false_replacement_when_fold_differs() -> None:
    assert correct_with_layer("<td>kota</td>", "pies") == "<td>kota</td>"


def test_layer_rejects_diacritic_removal() -> None:
    assert correct_with_layer("<td>ogółem</td>", "Ogolem") == "<td>ogółem</td>"
