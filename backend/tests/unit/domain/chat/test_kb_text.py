"""Testy kb_text: wiersze tabeli przypadków 1-12 z CONTRACT WP E4-7c (brief T1)."""

import re

import pytest

from app.domain.chat.kb_text import kb_text

CASES = [
    pytest.param(
        '<p data-bbox="72,86,277,98">Raport kwartalny</p>', "Raport kwartalny", id="1-p-bbox"
    ),
    pytest.param('<p data-bbox="1">A</p><p data-bbox="2">B</p>', "A\nB", id="2-dwa-p"),
    pytest.param("<h1>Tytuł</h1><p>Treść</p>", "Tytuł\nTreść", id="3-h1-p"),
    pytest.param("<ul><li>x</li><li>y</li></ul>", "- x\n- y", id="4-ul-li"),
    pytest.param(
        '<p class="breadcrumb">Rozdz 1 &gt; Pod 2</p><p>t</p>',
        "Rozdz 1 > Pod 2\nt",
        id="5-breadcrumb",
    ),
    pytest.param("<p>Tom &amp; Jerry</p>", "Tom & Jerry", id="6-encja-amp"),
    pytest.param("a<br>b<br/>c", "a\nb\nc", id="7-br"),
    pytest.param(
        "<div><table><tr><td>1</td></tr></table></div>",
        "<table><tr><td>1</td></tr></table>",
        id="8-tabela-w-div",
    ),
    pytest.param(
        '<p>przed</p><table border="1"><tr><td>1</td></tr></table><p>po</p>',
        'przed\n<table border="1"><tr><td>1</td></tr></table>\npo',
        id="9-tabela-atrybut",
    ),
    pytest.param("", "", id="10-puste"),
    pytest.param("   ", "", id="10-spacje"),
    pytest.param("<p></p>", "", id="10-same-tagi"),
    pytest.param("<div><span></span></div>", "", id="10-div-span"),
    pytest.param("zwykły tekst\ndruga linia", "zwykły tekst\ndruga linia", id="11-bez-html"),
    pytest.param("<p>a <b>b</b> c</p>", "a b c", id="12-inline"),
]


@pytest.mark.parametrize(("source", "expected"), CASES)
def test_kb_text_cases(source: str, expected: str) -> None:
    assert kb_text(source) == expected


def test_kb_text_no_tags_outside_tables() -> None:
    """Wynik nie ma '<' poza fragmentami <table ...>…</table> (CONTRACT, property)."""
    for case in CASES:
        source = case.values[0]
        out = kb_text(source)
        without_tables = re.sub(r"<table.*?</table>", "", out, flags=re.DOTALL)
        assert "<" not in without_tables, f"wejście {source!r} → {out!r}"
