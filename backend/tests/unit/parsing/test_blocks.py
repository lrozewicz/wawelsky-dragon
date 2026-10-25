"""Testy html_to_blocks — przykłady z briefu T2 (CONTRACT WP E1-5 C11)."""

from collections import Counter

from app.domain.chunking.tables import row_text
from app.parsing.blocks import html_to_blocks

# Nazwane stałe zamiast liczb magicznych w porównaniach (PLR2004).
_SIX_BLOCKS = 6
_THREE_BLOCKS = 3
_TWO_BLOCKS = 2
_EIGHT_BLOCKS = 8
_FIRST = 0

_WEJSCIE_NAGLOWKI = "<h1>A</h1><p>x</p><h2>B</h2><p>y</p><h1>C</h1><p>z</p>"

_WEJSCIE_STRONA = (
    '<section data-page="3"><p data-bbox="10.4,20,110.6,40">Tekst</p><p>Bez</p></section>'
)

_WEJSCIE_TABELA = (
    "<table><thead><tr><th>H1</th><th>H2</th></tr></thead>"
    "<tbody><tr><td>a</td><td>b</td></tr><tr><td>c</td><td>d</td></tr></tbody></table>"
)

_WEJSCIE_TABELA_BEZ_THEAD = (
    "<table><tr><td>K</td><td>V</td></tr><tr><td>1</td><td>2</td></tr></table>"
)

_WEJSCIE_LISTY = "<ul><li>a</li><li>b<ul><li>c</li></ul></li></ul><ol><li>x</li><li>y</li></ol>"

# Nagłówek wielopoziomowy (colspan/rowspan) — przykład z briefu T2.
_WEJSCIE_NAGLOWEK_WIELOPOZIOMOWY = (
    '<table><thead><tr><th rowspan="2">WYSZCZ.</th><th colspan="2">2022</th></tr>'
    "<tr><th>ogółem</th><th>kobiety</th></tr></thead>"
    '<tbody><tr><td colspan="3">OGÓŁEM</td></tr>'
    "<tr><td>15—24</td><td>10,8</td><td>11,3</td></tr></tbody></table>"
)

_WEJSCIE_ROWSPAN_W_TBODY = (
    "<table><thead><tr><th>a</th><th>b</th></tr></thead><tbody>"
    '<tr><td rowspan="2">X</td><td>1</td></tr>'
    "<tr><td>2</td></tr></tbody></table>"
)

_WEJSCIE_PROSTA_TABELA = (
    "<table><thead><tr><th>a</th><th>b</th></tr></thead>"
    "<tbody><tr><td>1</td><td>2</td></tr></tbody></table>"
)

_WEJSCIE_NIEJAWNE = '<section data-page="1">luźny tekst<p>p</p>ogon</section>'

# Dokument: 2 sekcje stron, h1-h3, tabela, lista, figura.
_DOKUMENT = (
    '<section data-page="1">'
    "<h1>Raport</h1>"
    "<p>Wstęp dokumentu.</p>"
    "<h2>Dane</h2>"
    "<table> <thead><tr><th>Produkt</th><th>Cena</th></tr></thead>"
    "<tbody><tr><td>Mleko</td><td>3.50</td></tr></tbody></table>"
    "<ul><li>pierwszy</li><li>drugi</li></ul>"
    "</section>"
    '<section data-page="2">'
    "<h3>Szczegóły</h3>"
    '<figure data-image="k1"><img><figcaption>Wykres sprzedaży</figcaption></figure>'
    "<p>Koniec.</p>"
    "</section>"
)


def test_puste_wejscie() -> None:
    """Puste wejście → brak bloków."""
    assert html_to_blocks("") == []


def test_sciezka_naglowkow() -> None:
    """Stos nagłówków: zdejmij wpisy o level >= n, ścieżka bez nagłówka, wstaw na stos."""
    blocks = html_to_blocks(_WEJSCIE_NAGLOWKI)
    assert len(blocks) == _SIX_BLOCKS
    assert [b.kind for b in blocks] == [
        "heading",
        "paragraph",
        "heading",
        "paragraph",
        "heading",
        "paragraph",
    ]
    assert [b.text for b in blocks] == ["A", "x", "B", "y", "C", "z"]
    assert [b.heading_path for b in blocks] == [(), ("A",), ("A",), ("A", "B"), (), ("C",)]
    assert [b.level for b in blocks] == [1, None, 2, None, 1, None]
    assert all(b.section is None for b in blocks)
    assert all(b.positions == () for b in blocks)


def test_pozycje_z_bbox_i_bez() -> None:
    """data-bbox → [strona, lewo, prawo, góra, dół]; brak bbox → zera; section "page:3"."""
    blocks = html_to_blocks(_WEJSCIE_STRONA)
    assert len(blocks) == _TWO_BLOCKS
    assert [b.positions for b in blocks] == [((3, 10, 111, 20, 40),), ((3, 0, 0, 0, 0),)]
    assert all(b.section == "page:3" for b in blocks)
    assert blocks[_FIRST].html == '<p data-bbox="10.4,20,110.6,40">Tekst</p>'


def test_sekcja_slajdu() -> None:
    """data-slide → "slide:n", bez pozycji (strony brak)."""
    blocks = html_to_blocks('<section data-slide="2"><p>S</p></section>')
    assert len(blocks) == 1
    assert blocks[_FIRST].section == "slide:2"
    assert blocks[_FIRST].positions == ()


def test_sekcja_arkusza() -> None:
    """data-sheet → "sheet:nazwa"."""
    blocks = html_to_blocks(
        '<section data-sheet="Arkusz1"><table><tr><td>K</td><td>V</td></tr></table></section>'
    )
    assert len(blocks) == 1
    assert blocks[_FIRST].section == "sheet:Arkusz1"


def test_niepoprawny_numer_strony() -> None:
    """data-page="x" oraz data-page="0" (< 1) → section None i brak pozycji."""
    for wejscie in (
        '<section data-page="x"><p>a</p></section>',
        '<section data-page="0"><p>a</p></section>',
    ):
        blocks = html_to_blocks(wejscie)
        assert len(blocks) == 1
        assert blocks[_FIRST].section is None
        assert blocks[_FIRST].positions == ()


def test_zly_bbox_jak_brak() -> None:
    """Zły data-bbox (3 liczby albo wartości nieliczbowe) → jak brak bbox."""
    for bbox in ("1,2,3", "a,b,c,d"):
        blocks = html_to_blocks(f'<section data-page="1"><p data-bbox="{bbox}">a</p></section>')
        assert len(blocks) == 1
        assert blocks[_FIRST].positions == ((1, 0, 0, 0, 0),)


def test_zbedne_zamkniecia_void_i_obce_znaczniki() -> None:
    """Zbędne zamknięcia void i obce znaczniki poza blokiem niczego nie zmieniają."""
    blocks = html_to_blocks("<p>a</p></br></hr></span>")
    assert len(blocks) == 1
    assert blocks[_FIRST].text == "a"


def test_normalizacja_tekstu() -> None:
    """Białe znaki (także \\n ze źródła) → spacja; <br> → \\n; encja → znak → escape w html."""
    blocks = html_to_blocks("<p>Ala  ma\n   kota<br>drugi <strong>wiersz</strong> &amp; x</p>")
    assert len(blocks) == 1
    assert blocks[_FIRST].text == "Ala ma kota\ndrugi wiersz & x"
    html = blocks[_FIRST].html
    assert "<br>" in html
    assert "<strong>wiersz</strong>" in html
    assert "&amp;" in html


def test_listy_zagniezdzona_i_numerowana() -> None:
    """ul: "- " na element, zagnieżdżona wcięta; ol numerowana od 1 w obrębie listy."""
    blocks = html_to_blocks(_WEJSCIE_LISTY)
    assert len(blocks) == _TWO_BLOCKS
    assert blocks[_FIRST].kind == "list"
    assert blocks[_FIRST].text == "- a\n- b\n  - c"
    assert blocks[1].text == "1. x\n2. y"


def test_tabela_z_thead() -> None:
    """thead z tr: nagłówek i header_html z thead, reszta tr to wiersze."""
    blocks = html_to_blocks(_WEJSCIE_TABELA)
    assert len(blocks) == 1
    block = blocks[_FIRST]
    assert block.kind == "table"
    assert block.table is not None
    assert block.table.header == ("H1", "H2")
    assert block.table.rows == (("a", "b"), ("c", "d"))
    assert block.table.header_html == "<thead><tr><th>H1</th><th>H2</th></tr></thead>"
    assert block.table.rows_html[_FIRST] == "<tr><td>a</td><td>b</td></tr>"
    assert block.text == "H1 | H2\na | b\nc | d"


def test_tabela_bez_thead() -> None:
    """Brak thead: pierwszy tr to nagłówek, w header_html opakowany w <thead>."""
    blocks = html_to_blocks(_WEJSCIE_TABELA_BEZ_THEAD)
    assert len(blocks) == 1
    table = blocks[_FIRST].table
    assert table is not None
    assert table.header == ("K", "V")
    assert table.rows == (("1", "2"),)
    assert table.header_html == "<thead><tr><td>K</td><td>V</td></tr></thead>"


def test_tabela_thead_bez_wierszy() -> None:
    """thead bez tr: nagłówek z pierwszego tr w ogóle."""
    blocks = html_to_blocks(
        "<table><thead></thead><tr><td>a</td><td>b</td></tr><tr><td>1</td><td>2</td></tr></table>"
    )
    assert len(blocks) == 1
    table = blocks[_FIRST].table
    assert table is not None
    assert table.header == ("a", "b")
    assert table.rows == (("1", "2"),)


def test_multilevel_header_linearization() -> None:
    """Nagłówek wielopoziomowy: nazwy kolumn to pełne ścieżki " / " po rozwinięciu siatki."""
    blocks = html_to_blocks(_WEJSCIE_NAGLOWEK_WIELOPOZIOMOWY)
    table = blocks[_FIRST].table
    assert table is not None
    assert table.header == ("WYSZCZ.", "2022 / ogółem", "2022 / kobiety")
    assert table.rows == (("OGÓŁEM", "", ""), ("15—24", "10,8", "11,3"))
    assert row_text(table.header, table.rows[1]) == (
        "WYSZCZ.: 15—24; 2022 / ogółem: 10,8; 2022 / kobiety: 11,3"
    )


def test_body_colspan_section_row() -> None:
    """Wiersz sekcji (colspan na pełną szerokość): wartość w pierwszej kolumnie, reszta pusta."""
    blocks = html_to_blocks(_WEJSCIE_NAGLOWEK_WIELOPOZIOMOWY)
    table = blocks[_FIRST].table
    assert table is not None
    assert table.rows[_FIRST] == ("OGÓŁEM", "", "")
    assert row_text(table.header, table.rows[_FIRST]) == "WYSZCZ.: OGÓŁEM"


def test_rowspan_body_cell_expanded() -> None:
    """Komórka tbody z rowspan: tekst powtórzony w kolejnych wierszach (rozwinięcie siatki)."""
    blocks = html_to_blocks(_WEJSCIE_ROWSPAN_W_TBODY)
    table = blocks[_FIRST].table
    assert table is not None
    assert table.header == ("a", "b")
    assert table.rows == (("X", "1"), ("X", "2"))


def test_simple_table_unchanged() -> None:
    """Prosta tabela (bez colspan/rowspan, 1 wiersz nagłówka) — wynik jak dziś."""
    blocks = html_to_blocks(_WEJSCIE_PROSTA_TABELA)
    table = blocks[_FIRST].table
    assert table is not None
    assert table.header == ("a", "b")
    assert table.rows == (("1", "2"),)
    assert blocks[_FIRST].text == "a | b\n1 | 2"


def test_header_html_keeps_colspan() -> None:
    """HTML w chunku zachowany dosłownie: colspan/rowspan zostają w header_html i block.html."""
    blocks = html_to_blocks(_WEJSCIE_NAGLOWEK_WIELOPOZIOMOWY)
    block = blocks[_FIRST]
    table = block.table
    assert table is not None
    assert 'rowspan="2"' in table.header_html
    assert 'colspan="2"' in table.header_html
    assert 'colspan="3"' in table.rows_html[_FIRST]
    assert 'colspan="2"' in block.html


def test_tabela_bez_wierszy_pominieta() -> None:
    """Tabela bez tr → pusty TableData i pusty tekst → blok pominięty."""
    assert html_to_blocks("<table></table>") == []


def test_komorka_z_br_jako_spacja() -> None:
    """W komórkach tabeli <br> staje się spacją."""
    blocks = html_to_blocks("<table><tr><td>Ala<br>ma</td><td>kota</td></tr></table>")
    assert len(blocks) == 1
    table = blocks[_FIRST].table
    assert table is not None
    assert table.header == ("Ala ma", "kota")


def test_pre_kod_doslownie() -> None:
    """pre: tekst dosłowny (białe znaki zachowane), ścięte tylko brzegowe \\n."""
    blocks = html_to_blocks("<pre><code>def f():\n    return 1\n</code></pre>")
    assert len(blocks) == 1
    assert blocks[_FIRST].kind == "code"
    assert blocks[_FIRST].text == "def f():\n    return 1"


def test_figura() -> None:
    """figure: tekst z figcaption, html zawiera data-image."""
    blocks = html_to_blocks(
        '<figure data-image="k1"><img><figcaption>Wykres  sprzedaży</figcaption></figure>'
    )
    assert len(blocks) == 1
    assert blocks[_FIRST].kind == "figure"
    assert blocks[_FIRST].text == "Wykres sprzedaży"
    assert 'data-image="k1"' in blocks[_FIRST].html


def test_figura_bez_figcaption_pominieta() -> None:
    """figure bez figcaption → pusty tekst → brak bloku."""
    assert html_to_blocks("<figure><img></figure>") == []


def test_figura_pierwszy_figcaption() -> None:
    """Pierwszy figcaption wygrywa — kolejne nie nadpisują tekstu."""
    blocks = html_to_blocks("<figure><figcaption>a</figcaption><figcaption>b</figcaption></figure>")
    assert len(blocks) == 1
    assert blocks[_FIRST].text == "a"


def test_notatki() -> None:
    """aside data-notes → notes; atrybut bez wartości serializowany jako pusty."""
    blocks = html_to_blocks("<aside data-notes>Notatka</aside>")
    assert len(blocks) == 1
    assert blocks[_FIRST].kind == "notes"
    assert blocks[_FIRST].text == "Notatka"
    assert blocks[_FIRST].html == '<aside data-notes="">Notatka</aside>'


def test_niejawne_akapity() -> None:
    """Tekst poza blokami → niejawne akapity; kończy je start bloku albo koniec kontenera."""
    blocks = html_to_blocks(_WEJSCIE_NIEJAWNE)
    assert len(blocks) == _THREE_BLOCKS
    assert [b.kind for b in blocks] == ["paragraph", "paragraph", "paragraph"]
    assert [b.text for b in blocks] == ["luźny tekst", "p", "ogon"]
    assert blocks[_FIRST].html == "<p>luźny tekst</p>"
    assert all(b.positions == ((1, 0, 0, 0, 0),) for b in blocks)
    assert all(b.section == "page:1" for b in blocks)


def test_pusty_naglowek_pominiety() -> None:
    """Nagłówek z samych białych znaków nie tworzy bloku i nie zmienia ścieżki."""
    blocks = html_to_blocks("<h2>  </h2><p>a</p>")
    assert len(blocks) == 1
    assert blocks[_FIRST].text == "a"
    assert blocks[_FIRST].heading_path == ()


def test_przezroczyste_div_i_skrypt() -> None:
    """div jest przezroczysty; zawartość script ignorowana."""
    blocks = html_to_blocks("<div><p>a</p></div><script>x()</script>")
    assert len(blocks) == 1
    assert blocks[_FIRST].text == "a"


def test_sekcja_nie_resetuje_stosu_naglowkow() -> None:
    """Granica sekcji nie czyści stosu nagłówków (h1 T zostaje na stosie dla p a)."""
    blocks = html_to_blocks('<h1>T</h1><section data-page="2"><p>a</p></section>')
    assert len(blocks) == _TWO_BLOCKS
    assert blocks[1].heading_path == ("T",)
    assert blocks[1].section == "page:2"
    assert blocks[1].positions == ((2, 0, 0, 0, 0),)


def test_ul_bez_elementow_pominiety() -> None:
    """ul bez własnych li → brak linii → blok pominięty."""
    assert html_to_blocks("<ul><ul><li>x</li></ul></ul>") == []


def test_br_poza_zlewem_tekstu() -> None:
    """<br> między elementami listy (bez aktywnego zlewu) nie zmienia tekstu."""
    blocks = html_to_blocks("<ul><li>a</li><br><li>b</li></ul>")
    assert len(blocks) == 1
    assert blocks[_FIRST].text == "- a\n- b"


def test_dokument_wielostronicowy() -> None:
    """Dokument: 2 sekcje stron, h1-h3, tabela, lista, figura — liczności per kind."""
    blocks = html_to_blocks(_DOKUMENT)
    assert len(blocks) == _EIGHT_BLOCKS
    assert Counter(b.kind for b in blocks) == {
        "heading": 3,
        "paragraph": 2,
        "table": 1,
        "list": 1,
        "figure": 1,
    }
    table = next(b for b in blocks if b.kind == "table")
    assert table.heading_path == ("Raport", "Dane")
    assert table.section == "page:1"
    assert table.positions == ((1, 0, 0, 0, 0),)
    figure = next(b for b in blocks if b.kind == "figure")
    assert figure.section == "page:2"
    assert figure.positions == ((2, 0, 0, 0, 0),)


def test_wywolanie_powtorne_rownowazne() -> None:
    """Ten sam HTML → równa lista bloków (determinizm)."""
    assert html_to_blocks(_DOKUMENT) == html_to_blocks(_DOKUMENT)
