"""Straty treści OCR: kolejność obraz-prompt, tekst przy tabelach OTSL, wykrywanie braków."""

from app.llm.openai_gateway import _vision_messages
from app.parsing.ocr_coverage import coverage, number_atoms
from app.parsing.otsl import otsl_to_html
from app.parsing.recognizers import _ORDERED_MARKER, coverage_warning


def test_image_goes_before_prompt() -> None:
    content = _vision_messages("prompt", b"png")[0]["content"]
    assert [part["type"] for part in content] == ["image_url", "text"]


def test_text_after_table_row_survives() -> None:
    source = (
        "<fcel>A<fcel>B<nl>\n<fcel>1<fcel>2<nl>\nTABL. 17 Tytuł\n"
        "<fcel>C<fcel>D<nl>\n<fcel>9008<fcel>4<nl>\nUwaga\n\nAkapit"
    )
    out, warnings = otsl_to_html(source)
    assert "TABL. 17 Tytuł" in out and "Uwaga" in out and "Akapit" in out and "9008" in out
    assert out.count("<table>") == 2  # noqa: PLR2004 — dwie tabele w źródle
    assert warnings == []


def test_truncated_cell_is_still_reported() -> None:
    out, warnings = otsl_to_html("<fcel>A<fcel>B<nl><fcel>1<fcel>2")
    assert "<table>" in out and warnings == ["OTSL truncated: closed last row"]


def test_ordered_marker_keeps_number() -> None:
    assert _ORDERED_MARKER.sub(r"\1\\\2", "2) tekst\n10. inny") == "2\\) tekst\n10\\. inny"


def test_number_atoms_ignore_thousand_separators() -> None:
    assert number_atoms("1 368 823") == number_atoms("<td>1368823</td>")
    assert number_atoms("103,2 115,4") == number_atoms("<td>103,2</td><td>115,4</td>")
    assert number_atoms("rok 2023")["2023"] == 1


def test_coverage_needs_enough_numbers() -> None:
    assert coverage(number_atoms(""), number_atoms("1 2 3")) is None
    layer = " ".join(str(100 + i) for i in range(20))
    assert coverage(number_atoms(layer), number_atoms(layer)) == 1.0


def test_warning_only_when_numbers_are_lost() -> None:
    layer = " ".join(str(100 + i) for i in range(20))
    half = " ".join(str(100 + i) for i in range(10))
    assert coverage_warning(layer, layer, 5) == []
    assert coverage_warning(half, layer, 5) == [
        "page 5: OCR kept 50% of numbers from the text layer"
    ]
