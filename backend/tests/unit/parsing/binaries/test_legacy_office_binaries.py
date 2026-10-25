"""Testy binaries starszych formatów biurowych: wvHtml (.doc) i catppt (.ppt) (kontrakt C12)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.parsing.recognizers import self_check
from app.parsing.registry import convert, detect_format
from app.parsing.types import ConvertOptions

pytestmark = [
    pytest.mark.binaries,
    pytest.mark.skipif(
        shutil.which("wvHtml") is None or shutil.which("catppt") is None,
        reason="brak wvHtml/catppt",
    ),
]

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "parsing"


def test_doc_through_wvhtml() -> None:
    path = FIXTURES / "sample.doc"
    assert detect_format(path, ".doc") == "doc"
    doc = convert(path, "doc", ConvertOptions())
    assert "Sprawozdanie" in doc.html
    assert "zażółć" in doc.html


def test_ppt_through_catppt() -> None:
    # sample.ppt z test-data Apache POI (patrz make_legacy_office.sh) — tekst „Slide Masters”
    path = FIXTURES / "sample.ppt"
    assert detect_format(path, ".ppt") == "ppt"
    doc = convert(path, "ppt", ConvertOptions())
    assert doc.html.count("data-slide") >= 1
    assert "Slide Masters" in doc.html


def test_self_check_sees_legacy_office() -> None:
    check = self_check()
    assert check["wvHtml"] is True
    assert check["catppt"] is True
