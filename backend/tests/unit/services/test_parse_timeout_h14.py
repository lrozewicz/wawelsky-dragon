"""Testy limitu czasu parsowania per dokument (H14, kontrakt T2).

`convert_document(..., timeout_s=N)` przerywa konwersję po N sekundach błędem `ParseTimeout`
(trwałym), a `timeout_s=None` zachowuje dotychczasowe zachowanie bez limitu.
"""

import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.parsing.errors import ParseTimeout
from app.parsing.types import ConvertedDocument, ConvertOptions
from app.services.ingest_convert import convert_document

_TXT = "Ala ma kota.\n"  # treść testowa pliku .txt


def _fast_convert(path: Path, fmt: str, opts: ConvertOptions) -> ConvertedDocument:
    """Konwerter natychmiastowy: dokument bez stron pending."""
    return ConvertedDocument("<p>ok</p>", None, [], {}, [], {"chars": 2})


def _slow_convert(path: Path, fmt: str, opts: ConvertOptions) -> ConvertedDocument:
    """Konwerter wolny: śpi 3 s, dłużej niż timeout 1 s w teście."""
    time.sleep(3.0)
    return _fast_convert(path, fmt, opts)


async def test_convert_document_timeout_raises_parse_timeout(tmp_path, monkeypatch):
    """Konwersja dłuższa niż timeout_s → ParseTimeout z komunikatem i details."""
    monkeypatch.setattr("app.services.ingest_convert.convert", _slow_convert)
    path = tmp_path / "a.txt"
    path.write_bytes(_TXT.encode("utf-8"))
    with pytest.raises(ParseTimeout) as excinfo:
        await convert_document(
            path, "txt", ConvertOptions(), executor=None, ocr=None, vision=None, timeout_s=1
        )
    assert str(excinfo.value) == "Parsing timed out after 1 s"
    assert excinfo.value.details == {"timeout_s": 1}


async def test_convert_document_without_timeout_returns(tmp_path, monkeypatch):
    """timeout_s=None → brak limitu, wynik zwrócony bez błędu."""
    monkeypatch.setattr("app.services.ingest_convert.convert", _fast_convert)
    path = tmp_path / "a.txt"
    path.write_bytes(_TXT.encode("utf-8"))
    doc = await convert_document(
        path, "txt", ConvertOptions(), executor=None, ocr=None, vision=None, timeout_s=None
    )
    assert doc.html == "<p>ok</p>"


def test_parse_timeout_s_default():
    """Domyślny WD_PARSE_TIMEOUT_S to 1800 (kontrakt T2); konwencja sąsiednich testów: env=test."""
    assert Settings(env="test").parse_timeout_s == 1800  # noqa: PLR2004 — wartość domyślna z kontraktu


def test_parse_timeout_s_rejects_zero():
    """parse_timeout_s < 1 odrzucone przez walidację pydantic."""
    with pytest.raises(ValidationError):
        Settings(parse_timeout_s=0)
