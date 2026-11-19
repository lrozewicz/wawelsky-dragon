"""Linie warstwy tekstowej PDF dopisywane po OCR, gdy OCR pominął mapę/wykres (layer_supplement).

Przypadek z held-out: MAPA 1 (27) rocznika pomorskiego 2025 (s. 116) — OCR dał tytuł mapy,
a legenda „pomorskie = 147” (czytelnicy bibliotek na 1000 ludności) zginęła.
"""

from app.parsing.layer_supplement import missing_lines, repeated_keys, supplement_html
from app.parsing.recognizers import apply_recognition
from app.parsing.types import ConvertedDocument, PendingPage

_OCR_116 = (
    "<p>MAPA 1 (27). BIBLIOTEKI PUBLICZNE W 2024 R.</p><p>MAP 1 (27). PUBLIC LIBRARIES IN 2024</p>"
    "<p>Wypożyczenia księgozbioru na 1 czytelnika w woluminach</p>"
)
_LAYER_116 = "\n".join(
    [
        "CULTURE. TOURISM. SPORT",
        "MAPA 1 (27). BIBLIOTEKI PUBLICZNE W 2024 R.",
        "MAP 1 (27). PUBLIC LIBRARIES IN 2024",
        "Czytelnicy bibliotek publicznych",
        "na 1000 ludności",
        "361 - 694",
        "Wypożyczenia księgozbioru na 1 czytelnika w woluminach",
        "pomorskie = 147 pomorskie = 14,6",
        "c h o d k a r t u s k i",
        "Spis treści ........................ 7",
        "115",
    ]
)


def test_lost_map_legend_is_added_with_its_description() -> None:
    lines = missing_lines(_OCR_116, _LAYER_116)
    assert "pomorskie = 147 pomorskie = 14,6" in lines
    assert "Czytelnicy bibliotek publicznych" in lines
    assert "na 1000 ludności" in lines
    # już przepisane przez OCR, bez liter, rozsypane, spis treści — nie wracają
    assert "MAPA 1 (27). BIBLIOTEKI PUBLICZNE W 2024 R." not in lines
    assert "Wypożyczenia księgozbioru na 1 czytelnika w woluminach" not in lines
    assert "361 - 694" not in lines
    assert not any(line.startswith(("c h o d", "Spis treści")) for line in lines)


def test_nothing_added_when_ocr_kept_all_numbers() -> None:
    ocr = "<table><tr><td>Ogółem</td><td>19 547</td><td>3,5</td></tr></table>"
    # inny podział wiersza i zapis tysięcy niż w OCR — liczby są, więc nic nie dopisujemy
    assert missing_lines(ocr, "Powierzchnia ogółem 19547 km2 3.5\nNota bez liczb") == []


def test_only_years_missing_is_not_a_loss() -> None:
    assert missing_lines("<p>Ludność</p>", "Ludność w latach 2015 i 2024") == []


def test_repeated_lines_are_skipped() -> None:
    words = ["Ludność", "Kina", "Teatry", "Muzea", "Szkoły"]
    layers = [f"Rocznik Euroregionu Nysa 2011 {n}\n{w} {n}0" for n, w in enumerate(words)]
    drop = repeated_keys(layers)
    assert missing_lines("<p>Ludność</p>", layers[0], drop) == ["Ludność 00"]


def test_map_legend_template_repeated_across_pages_is_kept() -> None:
    # Każda mapa ma legendę „pomorskie = …” — powtarzalny szablon w środku strony to treść.
    body = "Czytelnicy bibliotek\nna 1000 ludności\npomorskie = 1{n}7 pomorskie = 1{n},6\nźródło"
    layers = [
        f"DZIAŁ\nMAPA {n}\n" + body.format(n=n) + f"\nRocznik 2025\n{n + 100}" for n in range(5)
    ]
    drop = repeated_keys(layers)
    assert "pomorskie = 107 pomorskie = 10,6" in missing_lines("<p>MAPA 0</p>", layers[0], drop)


def test_apply_recognition_appends_lines_to_page_section() -> None:
    pending = PendingPage(116, "vision", b"", "image_cover", "", _LAYER_116)
    doc = ConvertedDocument('<section data-page="116"></section>', 1, [pending], {}, [], {})
    out = apply_recognition(doc, [(pending, _OCR_116, None, [])], vision=None)
    assert "<p>pomorskie = 147 pomorskie = 14,6</p>" in out.html
    assert out.html.index("BIBLIOTEKI") < out.html.index("pomorskie = 147")
    assert any("text-layer lines added" in w for w in out.warnings)


def test_supplement_html_escapes() -> None:
    assert supplement_html(["a < b"]) == "<p>a &lt; b</p>"


def test_table_row_with_leader_dots_is_added() -> None:
    # Rocznik woj. warmińsko-mazurskiego 2011: OCR zgubił wiersze tabeli mieszkań; w warstwie
    # mają kropki wiodące jak spis treści, ale za nimi stoją wartości, nie numer strony
    layer = (
        "Mieszkania oddane do użytkowania\nna 1000 ludności ................. 2,6 3,1 4,8 3,4 3,3"
    )
    assert missing_lines("<p>Mieszkania oddane do użytkowania</p>", layer) == [
        "na 1000 ludności ................. 2,6 3,1 4,8 3,4 3,3"
    ]


def test_table_row_kept_by_ocr_is_not_duplicated() -> None:
    ocr = "<table><tr><td>na 1000 ludności</td><td>2,6</td><td>3,1</td><td>4,8</td></tr></table>"
    layer = "na 1000 ludności ........ 2,6 3,1 4,8\nprzeciętna 1 mieszkania ..... 59,4 64,9 65,6"
    assert missing_lines(ocr, layer) == ["przeciętna 1 mieszkania ..... 59,4 64,9 65,6"]
