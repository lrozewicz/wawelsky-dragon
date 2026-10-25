"""Testy konwerterów tekstu, kodu i JSON (T7, kontrakt C8/C8b)."""

import dataclasses
import json
import pickle
import re
from pathlib import Path

import pytest

from app.parsing.converters.html_in import convert_html
from app.parsing.converters.image import convert_image
from app.parsing.converters.json_in import convert_json, convert_jsonl
from app.parsing.converters.markdown import convert_markdown
from app.parsing.converters.text import convert_code, convert_text
from app.parsing.errors import CorruptedFile, EmptyDocument, LimitExceeded
from app.parsing.types import ConvertOptions

OPTS = ConvertOptions()


def _compact(html: str) -> str:
    """Porównanie ignorujące białe znaki między tagami (treść tekstowa bez zmian)."""
    return re.sub(r">\s+<", "><", html).strip()


def test_text_cp1250_two_paragraphs(tmp_path: Path) -> None:
    path = tmp_path / "d.txt"
    path.write_bytes("Zażółć gęślą jaźń\n\nDrugi akapit".encode("cp1250"))
    doc = convert_text(path, OPTS)
    assert doc.metadata["encoding"] == "cp1250"
    assert _compact(doc.html) == "<p>Zażółć gęślą jaźń</p><p>Drugi akapit</p>"


def test_text_utf8_sig(tmp_path: Path) -> None:
    path = tmp_path / "d.txt"
    path.write_bytes(b"\xef\xbb\xbf" + "Treść".encode())
    doc = convert_text(path, OPTS)
    assert doc.metadata["encoding"] == "utf-8-sig"
    assert "<p>Treść</p>" in doc.html


def test_text_nul_byte_corrupted(tmp_path: Path) -> None:
    path = tmp_path / "d.txt"
    path.write_bytes(b"abc\x00def")
    with pytest.raises(CorruptedFile):
        convert_text(path, OPTS)


def test_text_zero_bytes_raises(tmp_path: Path) -> None:
    path = tmp_path / "d.txt"
    path.write_bytes(b"")
    with pytest.raises(EmptyDocument):
        convert_text(path, OPTS)


def test_code_preserves_whitespace(tmp_path: Path) -> None:
    path = tmp_path / "d.py"
    path.write_text("def f():\n    return  1", encoding="utf-8")
    doc = convert_code(path, OPTS)
    assert doc.html == "<pre><code>def f():\n    return  1</code></pre>"
    assert doc.metadata["encoding"] == "utf-8"


def test_json_flat_records_table(tmp_path: Path) -> None:
    path = tmp_path / "d.json"
    path.write_text('[{"a": 1, "b": "x"}, {"a": 2, "c": true}]', encoding="utf-8")
    doc = convert_json(path, OPTS)
    assert _compact(doc.html) == (
        "<table><thead><tr><th>a</th><th>b</th><th>c</th></tr></thead><tbody>"
        "<tr><td>1</td><td>x</td><td></td></tr>"
        "<tr><td>2</td><td></td><td>true</td></tr></tbody></table>"
    )


def test_json_table_cells_escaped_once(tmp_path: Path) -> None:
    path = tmp_path / "d.json"
    path.write_text('[{"opis": "a & b", "wzór": "x < y"}]', encoding="utf-8")
    doc = convert_json(path, OPTS)
    html = _compact(doc.html)
    assert "<td>a &amp; b</td>" in html
    assert "<td>x &lt; y</td>" in html
    assert "&amp;amp;" not in html and "&lt;lt;" not in html


def test_json_nested_structure(tmp_path: Path) -> None:
    path = tmp_path / "d.json"
    path.write_text('{"k": {"n": [1, 2]}, "z": null}', encoding="utf-8")
    doc = convert_json(path, OPTS)
    html = _compact(doc.html)
    assert "<ul>" in html
    assert "<strong>k</strong>" in html
    assert "null" in html
    assert html == (
        "<ul><li><strong>k</strong><ul><li><strong>n</strong><ul><li>1</li><li>2</li></ul></li>"
        "</ul></li><li><strong>z</strong>: null</li></ul>"
    )


def test_json_nonflat_list_gets_records(tmp_path: Path) -> None:
    path = tmp_path / "d.json"
    path.write_text('[{"a": {"b": 1}}]', encoding="utf-8")
    doc = convert_json(path, OPTS)
    assert "<h2>Record 1</h2>" in _compact(doc.html)


def test_json_scalar_paragraph(tmp_path: Path) -> None:
    path = tmp_path / "d.json"
    path.write_text('"tekst"', encoding="utf-8")
    doc = convert_json(path, OPTS)
    assert _compact(doc.html) == "<p>tekst</p>"


def test_json_depth_over_limit_dumps(tmp_path: Path) -> None:
    path = tmp_path / "d.json"
    path.write_text(json.dumps(json.loads("[" * 25 + "1" + "]" * 25)), encoding="utf-8")
    doc = convert_json(path, OPTS)
    assert "<p>[[[[1]]]]</p>" in _compact(doc.html)


def test_json_invalid_raises_with_line(tmp_path: Path) -> None:
    path = tmp_path / "d.json"
    path.write_text('{"a": oops', encoding="utf-8")
    with pytest.raises(CorruptedFile) as excinfo:
        convert_json(path, OPTS)
    assert "line 1" in str(excinfo.value)


def test_jsonl_two_records_with_blank_line(tmp_path: Path) -> None:
    path = tmp_path / "d.jsonl"
    path.write_text('{"a": 1}\n\n{"a": false}\n', encoding="utf-8")
    doc = convert_jsonl(path, OPTS)
    assert _compact(doc.html) == (
        "<table><thead><tr><th>a</th></tr></thead><tbody>"
        "<tr><td>1</td></tr><tr><td>false</td></tr></tbody></table>"
    )


def test_jsonl_bad_second_line(tmp_path: Path) -> None:
    path = tmp_path / "d.jsonl"
    path.write_text('{"a": 1}\nble\n', encoding="utf-8")
    with pytest.raises(CorruptedFile) as excinfo:
        convert_jsonl(path, OPTS)
    assert "line 2" in str(excinfo.value)


def test_json_records_limit_exceeded(tmp_path: Path) -> None:
    path = tmp_path / "d.json"
    path.write_text('[{"a": 1}, {"a": 2}]', encoding="utf-8")
    opts = dataclasses.replace(OPTS, max_sheet_rows=1)
    with pytest.raises(LimitExceeded) as excinfo:
        convert_json(path, opts)
    assert "records 2 > 1" in str(excinfo.value)


def test_json_empty_dict_raises(tmp_path: Path) -> None:
    path = tmp_path / "d.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(EmptyDocument) as excinfo:
        convert_json(path, OPTS)
    assert "JSON has no values" in str(excinfo.value)


def test_convert_functions_are_picklable() -> None:
    for fn in (
        convert_markdown,
        convert_html,
        convert_text,
        convert_code,
        convert_json,
        convert_jsonl,
        convert_image,
    ):
        assert pickle.dumps(fn)
