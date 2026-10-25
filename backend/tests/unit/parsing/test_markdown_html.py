"""Testy konwerterów Markdown i HTML (T7, kontrakt C8/C8a)."""

import re
from pathlib import Path

import pytest

from app.parsing.converters.html_in import clean_html_document, convert_html
from app.parsing.converters.markdown import convert_markdown
from app.parsing.errors import EmptyDocument
from app.parsing.types import ConvertOptions

OPTS = ConvertOptions()


def _compact(html: str) -> str:
    """Porównanie ignorujące białe znaki między tagami (markdown-it i lxml wstawiają \\n)."""
    return re.sub(r">\s+<", "><", html).strip()


def test_markdown_full_document(tmp_path: Path) -> None:
    path = tmp_path / "doc.md"
    path.write_text(
        "---\n"
        'title: "Raport"\n'
        "author: Jan\n"
        "notatka bez dwukropka\n"
        "---\n"
        "\n"
        "# H1\n"
        "\n"
        "## H2\n"
        "\n"
        "Akapit tekstu.\n"
        "\n"
        "- pozycja\n"
        "\n"
        "| a | b |\n"
        "|---|---|\n"
        "| 1 | 2 |\n"
        "\n"
        "```py\n"
        "kod\n"
        "```\n",
        encoding="utf-8",
    )
    doc = convert_markdown(path, OPTS)
    assert doc.metadata["title"] == "Raport"
    assert doc.metadata["author"] == "Jan"
    html = _compact(doc.html)
    assert "<h1>H1</h1>" in html
    assert "<h2>H2</h2>" in html
    assert "<p>Akapit tekstu.</p>" in html
    assert "<ul><li>pozycja</li></ul>" in html
    assert (
        "<table><thead><tr><th>a</th><th>b</th></tr></thead>"
        "<tbody><tr><td>1</td><td>2</td></tr></tbody></table>" in html
    )
    assert "<pre><code>kod\n</code></pre>" in html


def test_markdown_plain_gfm_table(tmp_path: Path) -> None:
    path = tmp_path / "doc.md"
    path.write_text("# Tytuł\n\n| a | b |\n|---|---|\n| 1 | 2 |\n", encoding="utf-8")
    doc = convert_markdown(path, OPTS)
    assert _compact(doc.html) == (
        "<h1>Tytuł</h1>"
        "<table><thead><tr><th>a</th><th>b</th></tr></thead>"
        "<tbody><tr><td>1</td><td>2</td></tr></tbody></table>"
    )


def test_markdown_without_closing_front_matter(tmp_path: Path) -> None:
    path = tmp_path / "doc.md"
    path.write_text("---\n\ntylko treść\n", encoding="utf-8")
    doc = convert_markdown(path, OPTS)
    assert doc.metadata == {}
    assert "<p>tylko treść</p>" in _compact(doc.html)


def test_markdown_only_front_matter_raises(tmp_path: Path) -> None:
    path = tmp_path / "doc.md"
    path.write_text("---\ntitle: x\n---\n", encoding="utf-8")
    with pytest.raises(EmptyDocument) as excinfo:
        convert_markdown(path, OPTS)
    assert "document has no text" in str(excinfo.value)


def test_html_meta_charset_iso8859_2(tmp_path: Path) -> None:
    path = tmp_path / "page.html"
    path.write_bytes(
        '<html><head><meta charset="iso-8859-2"></head><body><p>Zażółć gęślą jaźń</p>'
        "</body></html>".encode("iso-8859-2")
    )
    doc = convert_html(path, OPTS)
    assert "<p>Zażółć gęślą jaźń</p>" in doc.html


def test_html_drops_noise_and_banners(tmp_path: Path) -> None:
    path = tmp_path / "page.html"
    path.write_text(
        "<html><head><title>Tytuł</title></head><body>"
        "<p>Zdrowy tekst</p>"
        "<script>SKRYPT()</script>"
        "<style>.STYL { }</style>"
        "<nav>NAWIGACJA</nav>"
        "<footer>STOPKA</footer>"
        "<aside>BOK</aside>"
        "<header>NAGŁÓWEK STRONY</header>"
        "<form>FORMULARZ</form>"
        '<div id="cookie-banner"><p>CIASTECZKA</p></div>'
        '<div class="x GDPR-notice">RODO</div>'
        "</body></html>",
        encoding="utf-8",
    )
    doc = convert_html(path, OPTS)
    assert doc.metadata["title"] == "Tytuł"
    for marker in (
        "SKRYPT",
        "STYL",
        "NAWIGACJA",
        "STOPKA",
        "BOK",
        "NAGŁÓWEK STRONY",
        "FORMULARZ",
        "CIASTECZKA",
        "RODO",
    ):
        assert marker not in doc.html
    assert "<p>Zdrowy tekst</p>" in doc.html


def test_html_table_without_thead_gets_header(tmp_path: Path) -> None:
    path = tmp_path / "page.html"
    path.write_text(
        "<table><tr><td>A</td><td>B</td></tr><tr><td>1</td><td>2</td></tr></table>",
        encoding="utf-8",
    )
    doc = convert_html(path, OPTS)
    assert (
        "<thead><tr><th>A</th><th>B</th></tr></thead><tbody><tr><td>1</td><td>2</td></tr></tbody>"
        in _compact(doc.html)
    )


def test_html_fragment_without_body(tmp_path: Path) -> None:
    path = tmp_path / "page.html"
    path.write_text("<p>Fragment</p>", encoding="utf-8")
    doc = convert_html(path, OPTS)
    assert "<p>Fragment</p>" in doc.html
    assert doc.metadata == {}


def test_html_only_script_raises(tmp_path: Path) -> None:
    path = tmp_path / "page.html"
    path.write_text("<html><body><script>var x = 1;</script></body></html>", encoding="utf-8")
    with pytest.raises(EmptyDocument) as excinfo:
        convert_html(path, OPTS)
    assert "page has no text" in str(excinfo.value)


def test_clean_html_document_returns_html_and_metadata() -> None:
    html_out, metadata = clean_html_document(
        "<html><head><title>T</title></head><body><p>x</p></body></html>"
    )
    assert "<p>x</p>" in html_out
    assert metadata == {"title": "T"}
