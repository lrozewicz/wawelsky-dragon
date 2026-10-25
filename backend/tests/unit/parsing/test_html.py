"""Testy sanityzacji i budowy HTML (kontrakt C3)."""

import pytest

from app.parsing.html import (
    ALLOWED_ATTRS,
    ALLOWED_TAGS,
    DROP_WITH_CONTENT,
    esc,
    normalize_text,
    paragraphs_html,
    promote_table_headers,
    sanitize_html,
    section_html,
    table_html,
    text_chars,
)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("<p>a<script>x()</script>b</p>", "<p>ab</p>"),
        ("<style>p{}</style><p>t</p>", "<p>t</p>"),
        ('<div class="x"><p id="a" style="c">t</p></div>', "<p>t</p>"),
        ("<b>x</b><i>y</i>", "<strong>x</strong><em>y</em>"),
        ('<a href="javascript:alert(1)">z</a>', "<a>z</a>"),
        ('<a href="https://x.pl" target="_blank">z</a>', '<a href="https://x.pl">z</a>'),
        ('<section data-page="3" class="q"></section>', '<section data-page="3"></section>'),
        (
            '<table><tr><td colspan="2" width="5">x</td></tr></table>',
            '<table><tr><td colspan="2">x</td></tr></table>',
        ),
        ("<p>a\u00a0\u00a0 b</p>", "<p>a b</p>"),
        ("<pre><code>a  b</code></pre>", "<pre><code>a  b</code></pre>"),
        ("<p>é\x07</p>", "<p>é</p>"),
        ("<html><head><title>T</title></head><body><p>x</p></body></html>", "<p>x</p>"),
    ],
    ids=[
        "script",
        "style",
        "div-unwrap",
        "renames",
        "bad-href",
        "good-href",
        "section-empty",
        "td-attrs",
        "nbsp",
        "pre-spaces",
        "nfc-bel",
        "full-document",
    ],
)
def test_sanitize_examples(source: str, expected: str) -> None:
    assert sanitize_html(source) == expected


def test_sanitize_aside_notes() -> None:
    result = sanitize_html("<aside>x</aside><aside data-notes>n</aside>")
    # stała faktycznie wytwarzana przez implementację (serializacja atrybutu wg lxml)
    assert result == "x<aside data-notes>n</aside>"
    assert "<aside data-notes" in result
    assert not result.startswith("<aside")  # pierwszy aside rozpakowany, jego tekst został


def test_sanitize_empty() -> None:
    assert sanitize_html("") == ""


@pytest.mark.parametrize(
    "source",
    [
        "<p>a<script>x()</script>b</p>",
        '<div class="x"><p id="a" style="c">t</p></div>',
        "<b>x</b><i>y</i>",
        '<a href="https://x.pl" target="_blank">z</a>',
        "<p>é\x07  z</p>",
        "<ol><li>a</li><li>b</li></ol>",
        "<table><thead><tr><th>A</th></tr></thead><tbody><tr><td>1</td></tr></tbody></table>",
        "<pre><code>a  b\tc</code></pre>",
    ],
    ids=["script", "div", "renames", "href", "text", "list", "table", "pre"],
)
def test_sanitize_idempotent(source: str) -> None:
    once = sanitize_html(source)
    assert sanitize_html(once) == once


_FLOW_DROP_TAGS = sorted(DROP_WITH_CONTENT - {"head", "title"})


@pytest.mark.parametrize("tag", _FLOW_DROP_TAGS)
def test_drop_with_content(tag: str) -> None:
    result = sanitize_html(f"<p>a<{tag}>SECRET</{tag}>b</p>")
    assert result == "<p>ab</p>"
    assert "SECRET" not in result


@pytest.mark.parametrize(
    "source",
    [
        "<html><body><p>a<head><title>SECRET</title></head>b</p></body></html>",
        "<html><head><title>SECRET</title></head><body><p>a</p></body></html>",
    ],
    ids=["head", "title"],
)
def test_drop_with_content_head_like(source: str) -> None:
    # parser HTML sam przenosi część treści head do body — sprawdzamy usunięcie z treścią.
    assert "SECRET" not in sanitize_html(source)


def test_drop_with_content_skips_inner_subtree() -> None:
    assert sanitize_html("<p>a<object><b>SECRET</b></object>b</p>") == "<p>ab</p>"


def test_sanitize_comment_and_pi_removed() -> None:
    assert sanitize_html("<p>a<!-- note -->b<?pi foo?>c</p>") == "<p>abc</p>"


def test_sanitize_tfoot_renamed_to_tbody() -> None:
    assert (
        sanitize_html("<table><tfoot><tr><td>x</td></tr></tfoot></table>")
        == "<table><tbody><tr><td>x</td></tr></tbody></table>"
    )


def test_sanitize_keeps_tail_of_allowed_element() -> None:
    assert sanitize_html("<p><em>a</em>b  c</p>") == "<p><em>a</em>b c</p>"


def test_allowed_tags_and_attrs_match_contract() -> None:
    assert (
        frozenset(
            {
                "section",
                "h1",
                "h2",
                "h3",
                "h4",
                "h5",
                "h6",
                "p",
                "ul",
                "ol",
                "li",
                "table",
                "thead",
                "tbody",
                "tr",
                "th",
                "td",
                "pre",
                "code",
                "figure",
                "figcaption",
                "aside",
                "br",
                "strong",
                "em",
                "a",
            }
        )
        == ALLOWED_TAGS
    )
    assert {
        "section": frozenset({"data-page", "data-slide", "data-sheet"}),
        "p": frozenset({"data-bbox"}),
        "table": frozenset({"data-bbox"}),
        "th": frozenset({"colspan", "rowspan"}),
        "td": frozenset({"colspan", "rowspan"}),
        "figure": frozenset({"data-image"}),
        "aside": frozenset({"data-notes"}),
        "a": frozenset({"href"}),
    } == ALLOWED_ATTRS


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("é", "é"),  # NFC
        ("a\r\nb", "a\nb"),
        ("a\rb", "a\nb"),
        ("a\x07b", "ab"),  # BEL usunięty
        ("a\tb", "a\tb"),  # tabulator zostaje
        ("a\u00a0b", "a b"),  # NBSP
        ("a  b", "a b"),  # podwójne spacje
        ("﻿a", "﻿a"),  # BOM w środku tekstu zostaje (nie jest Cc)
    ],
)
def test_normalize_text(text: str, expected: str) -> None:
    assert normalize_text(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("a  b", "a  b"),  # pre=True nie redukuje spacji
        ("a\u00a0b", "a\u00a0b"),  # ani NBSP
        ("a\x07b", "ab"),  # sterujące i tak usuwane
    ],
)
def test_normalize_text_pre(text: str, expected: str) -> None:
    assert normalize_text(text, pre=True) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("a<b>&\"'", "a&lt;b&gt;&amp;&quot;&#x27;"),
        ("a  b", "a b"),  # esc normalizuje
        ("", ""),
    ],
)
def test_esc(text: str, expected: str) -> None:
    assert esc(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("a\nb\n\nc", "<p>a<br>b</p><p>c</p>"),
        ("  \n\n ", ""),
        ("a\nb\nc", "<p>a<br>b<br>c</p>"),
        ("one", "<p>one</p>"),
        ("", ""),
    ],
)
def test_paragraphs_html(text: str, expected: str) -> None:
    assert paragraphs_html(text) == expected


@pytest.mark.parametrize(
    ("rows", "kwargs", "expected"),
    [
        (
            [["A", "B"], ["1"]],
            {},
            "<table><thead><tr><th>A</th><th>B</th></tr></thead>"
            "<tbody><tr><td>1</td><td></td></tr></tbody></table>",
        ),
        (
            [["A"], ["1"]],
            {"header_rows": 0},
            "<table><tbody><tr><td>A</td></tr><tr><td>1</td></tr></tbody></table>",
        ),
        ([["A"]], {}, "<table><thead><tr><th>A</th></tr></thead></table>"),  # brak tbody
        ([], {}, ""),
        (
            [["A", "B", "C"], ["1"]],
            {},
            "<table><thead><tr><th>A</th><th>B</th><th>C</th></tr></thead>"
            "<tbody><tr><td>1</td><td></td><td></td></tr></tbody></table>",
        ),
        (
            [["A"]],
            {"header_rows": 0, "bbox": "1,2,3,4"},
            '<table data-bbox="1,2,3,4"><tbody><tr><td>A</td></tr></tbody></table>',
        ),
        ([["<x>"]], {}, "<table><thead><tr><th>&lt;x&gt;</th></tr></thead></table>"),
    ],
    ids=["example", "no-header", "no-tbody", "empty", "padding", "bbox", "escaped-cells"],
)
def test_table_html(rows: list[list[str]], kwargs: dict[str, object], expected: str) -> None:
    assert table_html(rows, **kwargs) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("kind", "value", "inner", "expected"),
    [
        ("page", 2, "<p>x</p>", '<section data-page="2"><p>x</p></section>'),
        ("slide", "3", "", '<section data-slide="3"></section>'),
        ("sheet", "A<B", "", '<section data-sheet="A&lt;B"></section>'),
    ],
)
def test_section_html(kind: str, value: object, inner: str, expected: str) -> None:
    assert section_html(kind, value, inner) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "<table><tr><td>A</td><td>B</td></tr><tr><td>1</td><td>2</td></tr></table>",
            "<table><thead><tr><th>A</th><th>B</th></tr></thead><tbody><tr><td>1</td><td>2</td></tr></tbody></table>",
        ),
        (
            "<table><thead><tr><th>A</th></tr></thead><tbody><tr><td>1</td></tr></tbody></table>",
            "<table><thead><tr><th>A</th></tr></thead><tbody><tr><td>1</td></tr></tbody></table>",
        ),
        ("<table><tr><td>A</td></tr></table>", "<table><tr><td>A</td></tr></table>"),
        ("", ""),
        ("<p>bez tabeli</p>", "<p>bez tabeli</p>"),
    ],
    ids=["promoted", "thead-kept", "single-row", "empty", "no-table"],
)
def test_promote_table_headers(source: str, expected: str) -> None:
    assert promote_table_headers(source) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("<p>a b</p>", 2),
        ("", 0),
        ("<p>a<b>b</b>c</p>", 3),
        ("<p>  </p>", 0),
        ("<p>x</p><p>yz</p>", 3),
    ],
)
def test_text_chars(source: str, expected: int) -> None:
    assert text_chars(source) == expected
