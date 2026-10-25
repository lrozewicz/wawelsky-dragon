"""Testy konwertera EML (T8, kontrakt C8c)."""

import email
import email.policy
from pathlib import Path

import pytest

from app.parsing.converters.eml import convert_eml
from app.parsing.errors import EmptyDocument
from app.parsing.types import ConvertOptions

OPTS = ConvertOptions()


def _full_message() -> bytes:
    """Wiadomość multipart/alternative z tabelą w html i dwoma załącznikami (jeden uszkodzony)."""
    msg = email.message.EmailMessage()
    msg["Subject"] = "Zażółć gęślą"
    msg["From"] = "Ala <ala@example.com>"
    msg["To"] = "Bob <bob@example.com>"
    msg["Date"] = "Sat, 27 Sep 2026 12:00:00 +0200"
    msg.set_content("Wersja tekstowa wiadomości")
    msg.add_alternative(
        "<html><body><p>Treść <strong>hipertekstowa</strong></p>"
        "<table><tbody><tr><td>komórka</td></tr></tbody></table></body></html>",
        subtype="html",
    )
    msg.add_attachment(
        b"Nazwa;Kwota\nAla;3,14", maintype="text", subtype="csv", filename="dane.csv"
    )
    msg.add_attachment(b"nie pdf", maintype="application", subtype="pdf", filename="zly.pdf")
    return bytes(msg)


def test_eml_full_message(tmp_path: Path) -> None:
    data = _full_message()
    assert "=?utf-8?" in data.decode("latin-1")  # temat zakodowany RFC 2047 przy serializacji
    path = tmp_path / "wiadomosc.eml"
    path.write_bytes(data)
    doc = convert_eml(path, OPTS)
    assert "<h1>Zażółć gęślą</h1>" in doc.html
    assert "<strong>From</strong>" in doc.html
    assert "<strong>hipertekstowa</strong>" in doc.html  # treść z części html
    assert "<table>" in doc.html
    assert "Wersja tekstowa wiadomości" not in doc.html  # część plain odrzucona
    assert "<h2>Attachment: dane.csv</h2>" in doc.html
    assert "3,14" in doc.html  # przecinek dziesiętny bez zmian w tabeli załącznika
    assert doc.warnings[0].startswith(
        "attachment 'zly.pdf' skipped: File is corrupted or unreadable (.pdf): "
    )
    assert doc.metadata["title"] == "Zażółć gęślą"
    assert "ala@example.com" in doc.metadata["author"]


def test_eml_plain_only_with_unnamed_attachment(tmp_path: Path) -> None:
    msg = email.message.EmailMessage()
    msg["Subject"] = "Notatka"
    msg["From"] = "Ala <ala@example.com>"
    msg.set_content("Zwykły tekst wiadomości")
    msg.add_attachment(b"nienazwana zawartosc", maintype="application", subtype="octet-stream")
    path = tmp_path / "wiadomosc.eml"
    path.write_bytes(bytes(msg))
    doc = convert_eml(path, OPTS)
    assert "<p>Zwykły tekst wiadomości</p>" in doc.html
    assert "Attachment:" not in doc.html  # załącznik bez nazwy — pomijany
    assert doc.warnings == []


def test_eml_attachment_path_traversal(tmp_path: Path) -> None:
    msg = email.message.EmailMessage()
    msg["Subject"] = "Załącznik"
    msg["From"] = "Ala <ala@example.com>"
    msg.set_content("Treść wiadomości")
    msg.add_attachment(
        "treść załącznika".encode(), maintype="text", subtype="plain", filename="../../etc/x.txt"
    )
    path = tmp_path / "wiadomosc.eml"
    path.write_bytes(bytes(msg))
    doc = convert_eml(path, OPTS)
    assert "<h2>Attachment: x.txt</h2>" in doc.html
    assert "<p>treść załącznika</p>" in doc.html
    assert "../" not in doc.html


def test_eml_empty_message_raises(tmp_path: Path) -> None:
    msg = email.message.EmailMessage()
    msg["Subject"] = ""
    path = tmp_path / "wiadomosc.eml"
    path.write_bytes(bytes(msg))
    with pytest.raises(EmptyDocument):
        convert_eml(path, OPTS)
