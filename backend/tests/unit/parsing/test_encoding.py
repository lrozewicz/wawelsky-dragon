"""Testy detekcji kodowania (kontrakt C5)."""

from types import SimpleNamespace

import pytest
from charset_normalizer import from_bytes

from app.parsing.encoding import MOJIBAKE_GLYPHS, decode_bytes, mojibake_ratio
from app.parsing.errors import CorruptedFile


@pytest.mark.parametrize(
    ("data", "expected_text", "expected_encoding"),
    [
        ("Zażółć gęślą jaźń".encode("cp1250"), "Zażółć gęślą jaźń", "cp1250"),
        ("Zażółć gęślą jaźń".encode("iso8859_2"), "Zażółć gęślą jaźń", "iso8859_2"),
        (b"\xef\xbb\xbfabc", "abc", "utf-8-sig"),
        ("Zażółć".encode("utf-16"), "Zażółć", "utf-16"),  # BOM FF FE
        ("Zażółć".encode(), "Zażółć", "utf-8"),
    ],
    ids=["cp1250", "iso8859-2", "utf-8-sig", "utf-16-bom", "utf-8"],
)
def test_decode_bytes(data: bytes, expected_text: str, expected_encoding: str) -> None:
    assert decode_bytes(data) == (expected_text, expected_encoding)


def test_decode_bytes_nul_raises() -> None:
    with pytest.raises(CorruptedFile) as excinfo:
        decode_bytes(b"abc\x00def", fmt="csv")
    message = "File is corrupted or unreadable (.csv): binary content in a text file"
    assert str(excinfo.value) == message


def test_decode_bytes_charset_normalizer_fallback() -> None:
    # cp1250 nie dekoduje 0x81; iso8859_2 daje U+0081/U+0098 (C1) — oba kandydatów odpadają, krok 6.
    data = b"abc\x81\x98def"
    best = from_bytes(data).best()
    assert best is not None
    assert decode_bytes(data) == (str(best), best.encoding)


def test_decode_bytes_charset_normalizer_none(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = lambda _data: SimpleNamespace(best=lambda: None)  # noqa: E731 — atrapa krok 6 C5
    monkeypatch.setattr("app.parsing.encoding.from_bytes", fake)
    with pytest.raises(CorruptedFile) as excinfo:
        decode_bytes(b"abc\x81\x98def", fmt="txt")
    assert str(excinfo.value) == "File is corrupted or unreadable (.txt): unknown text encoding"


def test_mojibake_glyphs() -> None:
    assert frozenset("ȥ˷ɇɽƃ�￾") == MOJIBAKE_GLYPHS


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Zażółć gęślą", 0.0),
        ("", 0.0),
        ("ȥȥab", 0.5),
        ("a", 0.5),  # Private Use → zły, "a" → dobry
        ("a+b=c 5% 20°C 3€", 0.0),  # ASCII, symbole i cyfry dozwolone
    ],
)
def test_mojibake_ratio(text: str, expected: float) -> None:
    assert mojibake_ratio(text) == expected
