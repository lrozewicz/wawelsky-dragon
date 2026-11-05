"""Struktura tabel: tytuł, nagłówek wielopoziomowy, hierarchia wierszy (table_structure, blocks)."""

from app.parsing.blocks import html_to_blocks
from app.parsing.converters.sheets import sheet_html
from app.parsing.otsl import otsl_to_html
from app.parsing.table_structure import analyze

# CSV KG PSP: adres i data, tytuł, trzy poziomy nagłówka, kolumna Lp., stopka.
PSP = [
    ["KG PSP Warszawa ul. Podchorążych 38", "", "", "", "", "", "Warszawa, 23-01-2019 r."],
    ["10_2. Wypadki z ludźmi podczas pożarów", "", "", "", "", "", ""],
    ["", "", "", "", "Pożar (P)", "", ""],
    ["", "", "OGÓŁEM", "", "Ratownicy", "", "Inne"],
    ["LP.", "Podział administracyjny", "Śmiertelne", "Ranni", "Śmiertelne", "Ranni", "Ranni"],
    ["1", "Polska", "4959", "69108", "1", "406", "3929"],
    ["2", "DOLNOŚLĄSKIE", "568", "6501", "0", "28", "399"],
    ["3", "bolesławiecki", "15", "358", "0", "2", "33"],
    ["4", "Gromadka", "0", "44", "0", "1", "4"],
    ["5", "Nowogrodziec", "2", "57", "0", "0", "7"],
    ["6", "jaworski", "9", "120", "0", "1", "9"],
    ["7", "Bolków", "1", "20", "0", "0", "2"],
    ["8", "OPOLSKIE", "100", "900", "0", "5", "40"],
    ["9", "kędzierzyńsko-kozielski", "10", "215", "0", "1", "14"],
    ["10", "Kędzierzyn-Koźle", "3", "140", "0", "0", "8"],
    ["11", "MAZOWIECKIE", "700", "9000", "0", "50", "500"],
    ["12", "sochaczewski", "20", "300", "0", "2", "20"],
    ["13", "Młodzieszyn", "3", "18", "0", "0", "1"],
    ["Opracowano:", "", "", "", "", "", ""],
]


def test_csv_title_rows_and_three_header_levels() -> None:
    shape = analyze(PSP)
    assert shape is not None
    assert shape.title[1].startswith("10_2. Wypadki")
    assert shape.labels[0] == "Podział administracyjny"  # „LP.” usunięta
    assert shape.labels[1] == "OGÓŁEM / Śmiertelne"
    assert shape.labels[2] == "OGÓŁEM / Ranni"
    assert shape.labels[3] == "Pożar (P) / Ratownicy / Śmiertelne"
    assert shape.labels[4] == "Pożar (P) / Ratownicy / Ranni"
    assert shape.labels[5] == "Pożar (P) / Inne / Ranni"


def test_case_hierarchy_gives_voivodship_and_county_path() -> None:
    shape = analyze(PSP)
    assert shape is not None
    labels = [row[0] for row in shape.rows]
    assert "OPOLSKIE / kędzierzyńsko-kozielski / Kędzierzyn-Koźle" in labels
    assert "DOLNOŚLĄSKIE / jaworski / Bolków" in labels
    assert "MAZOWIECKIE / sochaczewski" in labels


def test_csv_document_has_title_heading_and_composed_header() -> None:
    blocks = html_to_blocks(sheet_html(PSP))
    assert blocks[0].kind == "heading"
    assert "Wypadki z ludźmi" in blocks[0].text
    table = blocks[1].table
    assert table is not None
    assert table.header[1] == "OGÓŁEM / Śmiertelne"
    assert table.rows[0][:3] == ("Polska", "4959", "69108")


def test_rowspan_header_across_thead_and_tbody_stays_aligned() -> None:
    """DOCX (mammoth): thead = 1. wiersz, a jego rowspan sięga do 2. wiersza w tbody."""
    html = (
        "<table><thead><tr><th rowspan='2'>WYSZCZEGÓLNIENIE</th><th rowspan='2'>2014</th>"
        "<th colspan='2'>2015</th></tr></thead><tbody>"
        "<tr><td>ogółem</td><td>w tym kobiety</td></tr>"
        "<tr><td>Przemysł</td><td>70921</td><td>70071</td><td>24718</td></tr>"
        "<tr><td>Budownictwo</td><td>50000</td><td>51000</td><td>9000</td></tr>"
        "</tbody></table>"
    )
    table = html_to_blocks(html)[0].table
    assert table is not None
    assert table.header == ("WYSZCZEGÓLNIENIE", "2014", "2015 / ogółem", "2015 / w tym kobiety")
    assert table.rows[0] == ("Przemysł", "70921", "70071", "24718")


def test_paragraphs_in_cell_are_separated() -> None:
    html = (
        "<table><tr><td><p>WYSZCZEGÓLNIENIE</p><p>SPECIFICATION</p></td><td>2015</td></tr>"
        "<tr><td>Przemysł</td><td>1</td></tr></table>"
    )
    table = html_to_blocks(html)[0].table
    assert table is not None
    assert table.header[0] == "WYSZCZEGÓLNIENIE SPECIFICATION"


def test_period_rows_join_polish_and_english_label() -> None:
    grid = [
        ["SEKCJE", "SEKCJE", "Województwo", "Miasta"],
        ["Przemysł", "2014", "266122", "197543"],
        ["Industry", "2015", "264206", "193674"],
        ["Budownictwo", "2014", "100", "90"],
        ["Construction", "2015", "110", "95"],
    ]
    shape = analyze(grid)
    assert shape is not None
    assert shape.labels[:2] == ("SEKCJE", "")  # powtórzona nazwa w opisie — bez nazwy
    assert shape.rows[1][:2] == ("Przemysł / Industry", "2015")
    assert shape.rows[2][0] == "Budownictwo / Construction"


def test_ocr_rowspan_in_data_keeps_row_order() -> None:
    """OTSL: <ucel> w wierszu danych (opis nad latami) nie robi z niego nagłówka."""
    otsl = (
        "<fcel>WYSZCZEGÓLNIENIE<lcel><fcel>Ogółem<fcel>Żywność<nl>"
        "<fcel>Polska<fcel>2000<fcel>87,2<fcel>90,2<nl>"
        "<fcel>Polish<fcel>2005<fcel>100,0<fcel>100,0<nl>"
        "<ucel><fcel>2010<fcel>116,7<fcel>121,8<nl>"
        "<fcel>Czeska<fcel>2005<fcel>100,0<fcel>100,0<nl>"
        "<ucel><fcel>2010<fcel>114,9<fcel>111,3<nl>"
    )
    html, _ = otsl_to_html(otsl)
    table = html_to_blocks(html)[0].table
    assert table is not None
    assert table.rows[2] == ("Polska / Polish", "2010", "116,7", "121,8")
    assert table.rows[4] == ("Czeska", "2010", "114,9", "111,3")


def test_indent_and_repeated_labels_build_row_path() -> None:
    grid = [
        ["WYSZCZEGÓLNIENIE", "2017", "2018"],
        ["W wieku produkcyjnym", "1415748", "1407448"],
        ["mężczyźni", "748560", "744518"],
        ["Miasta", "887501", "877578"],
        ["kobiety", "422768", "418051"],
        ["W wieku poprodukcyjnym", "454077", "467637"],
        ["Miasta", "334848", "343160"],
        ["kobiety", "225661", "229998"],
    ]
    shape = analyze(grid, None, [0, 0, 1, 0, 1, 0, 0, 1])
    assert shape is not None
    labels = [row[0] for row in shape.rows]
    assert labels[1] == "W wieku produkcyjnym / mężczyźni"
    assert labels[2] == "W wieku produkcyjnym / Miasta"
    assert labels[3] == "W wieku produkcyjnym / Miasta / kobiety"
    assert labels[6] == "W wieku poprodukcyjnym / Miasta / kobiety"


def test_subordinate_rows_get_parent() -> None:
    grid = [
        ["WYSZCZEGÓLNIENIE", "2017", "2018"],
        ["Rodziny zastępcze", "2311", "2245"],
        ["Spokrewnione", "1431", "1403"],
        ["dzieci", "1839", "1804"],
        ["Niezawodowe", "687", "647"],
        ["dzieci", "950", "892"],
        ["Urodzenia żywe", "100", "90"],
        ["na 1000 ludności", "9,5", "9,1"],
    ]
    shape = analyze(grid)
    assert shape is not None
    labels = [row[0] for row in shape.rows]
    assert labels[2] == "Spokrewnione / dzieci"
    assert labels[4] == "Niezawodowe / dzieci"
    assert labels[6] == "Urodzenia żywe / na 1000 ludności"


def test_section_row_above_data_is_not_a_column_name() -> None:
    grid = [
        ["WYSZCZEGÓLNIENIE", "1946", "1950"],
        ["POWIERZCHNIA. TOTAL AREA.", "", ""],
        ["Powierzchnia ogólna kraju", "1,316", "1,260"],
        ["w tym użytki rolne", "0,860", "0,823"],
    ]
    shape = analyze(grid)
    assert shape is not None
    assert shape.labels == ("WYSZCZEGÓLNIENIE", "1946", "1950")
    assert shape.rows[0][0] == "POWIERZCHNIA. TOTAL AREA."
    assert shape.rows[2][0] == "Powierzchnia ogólna kraju / w tym użytki rolne"


def test_column_numbering_row_is_dropped() -> None:
    grid = [
        ["WYSZCZEGÓLNIENIE", "Ogółem", "Miasta"],
        ["0", "1", "2"],
        ["Ludność", "100", "60"],
        ["Mieszkania", "40", "30"],
    ]
    shape = analyze(grid)
    assert shape is not None
    assert shape.labels == ("WYSZCZEGÓLNIENIE", "Ogółem", "Miasta")
    assert [row[0] for row in shape.rows] == ["Ludność", "Mieszkania"]


def test_text_table_is_left_to_thead() -> None:
    assert analyze([["Termin", "Definicja"], ["RAG", "wyszukiwanie z generacją"]]) is None


def test_header_numbers_are_not_data() -> None:
    """Wiersz wieku („0 | 15 | 30”) bez opisu to nagłówek, nie dane."""
    grid = [
        ["WYSZCZEGÓLNIENIE", "wiek", "", ""],
        ["", "0", "15", "30"],
        ["Mężczyźni", "74,0", "59,3", "44,8"],
        ["Kobiety", "81,8", "67,1", "52,3"],
    ]
    shape = analyze(grid)
    assert shape is not None
    assert shape.labels == ("WYSZCZEGÓLNIENIE", "wiek / 0", "wiek / 15", "wiek / 30")


def test_double_table_header_is_not_renamed() -> None:
    """Tabela „podwójna” (Poznań | … | Luboń | …): chunker rozdziela ją po powtórzonym nagłówku."""
    grid = [
        ["Miasto", "2010", "2020", "Miasto", "2010", "2020"],
        ["Poznań", "551", "534", "Luboń", "29", "32"],
        ["Swarzędz", "30", "31", "Puszczykowo", "9", "9"],
    ]
    shape = analyze(grid)
    assert shape is not None
    assert shape.labels == ("Miasto", "2010", "2020", "Miasto", "2010", "2020")


def test_consecutive_years_are_not_an_ordinal_column() -> None:
    grid = [
        ["WYSZCZEGÓLNIENIE", "", "Korzystający", "Świadczenia"],
        ["Zasiłek stały", "2015", "17000", "80124"],
        ["", "2016", "17100", "82000"],
        ["", "2017", "17150", "84000"],
        ["", "2018", "17197", "85503,7"],
    ]
    shape = analyze(grid)
    assert shape is not None
    assert shape.rows[3][:2] == ("Zasiłek stały", "2018")
