"""Testy jednostkowe handlera ``build_outline`` — części bez bazy (K21 §2 p. 4).

Pokrywają wyznaczanie nagłówków z pliku (konwertery bez modeli), odesłanie do OCR/wizji
(``pending_pages`` → brak spisu), wybór źródła w ``_determine`` (zakładki PDF → nagłówki
→ ``none``, jak w ``parse_document``) i wymóg payloadu ``document_id``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.core.config import Settings
from app.parsing.outline import OutlineItem
from app.parsing.types import ConvertedDocument, PendingPage
from app.worker.errors import PermanentError
from app.worker.handlers import build_outline as module


def _settings() -> Settings:
    """Ustawienia testowe (storage w tmp niepotrzebny — funkcje nie dotykają bazy)."""
    return Settings(env="test")


def _doc(suffix: str = "pdf") -> SimpleNamespace:
    """Dokument zastępczy — tylko pola czytane przez ``_determine``."""
    return SimpleNamespace(suffix=suffix, location=f"files/x.{suffix}")


def _container_with_storage(path: Path) -> SimpleNamespace:
    """Kontener zastępczy dla ``_determine``: storage oddaje podaną ścieżkę."""
    return SimpleNamespace(
        storage=SimpleNamespace(local_path=lambda _key: path), settings=_settings()
    )


async def test_missing_document_id_is_permanent_error() -> None:
    """Payload bez ``document_id`` → ``PermanentError`` (zadanie od razu ``failed``)."""
    task = SimpleNamespace(payload={})
    ctx = SimpleNamespace(container=None)  # dojście do kontenera nie następuje

    with pytest.raises(PermanentError):
        await module.build_outline(cast("Any", task), cast("Any", ctx))


def test_headings_from_markdown_file(tmp_path: Path) -> None:
    """Plik Markdown → nagłówki z konwersji bez modeli (K21 §2 p. 2b/4)."""
    path = tmp_path / "notatka.md"
    path.write_text("# Umowa najmu\n\n## Warunki\n\ntekst akapitu\n", encoding="utf-8")

    outline = module._headings_from_file(path, "md", _settings())

    assert [item["title"] for item in outline] == ["Umowa najmu", "Warunki"]
    assert [item["level"] for item in outline] == [0, 1]


def test_pending_pages_yield_no_headings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Strona wymagająca OCR/wizji bez modelu → pusty spis (``none``) (K21 §2 p. 4)."""
    path = tmp_path / "skan.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    pending = PendingPage(page=1, mode="vision", image_png=b"png", reason="image_cover")
    converted = ConvertedDocument(
        html='<section data-page="1"></section>',
        pages=1,
        pending_pages=[pending],
        metadata={},
        warnings=[],
        stats={},
    )
    monkeypatch.setattr(module, "convert", lambda *_a, **_k: converted)

    assert module._headings_from_file(path, "png", _settings()) == []


# --- `_determine`: pierwsze niepuste źródło, PDF bez zakładek → nagłówki (K21 §2 p. 2b) ---


def test_determine_pdf_with_bookmarks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """PDF z zakładkami → ``pdf_bookmarks`` (K21 §2 p. 2a)."""
    path = tmp_path / "a.pdf"
    path.write_bytes(b"%PDF-1.4 fake")
    bookmarks: list[OutlineItem] = [{"level": 0, "title": "DZIAŁ I", "page": 1}]
    monkeypatch.setattr(module, "outline_from_pdf", lambda _path: bookmarks)

    outline, source = module._determine(_container_with_storage(path), cast("Any", _doc("pdf")))

    assert source == "pdf_bookmarks"
    assert outline == bookmarks


def test_determine_pdf_without_bookmarks_falls_back_to_headings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """PDF bez zakładek → nagłówki z konwersji bez modeli, jak w ``parse_document`` (§2 p. 2b)."""
    path = tmp_path / "a.pdf"
    path.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(module, "outline_from_pdf", lambda _path: [])
    converted = ConvertedDocument(
        html='<section data-page="1"><h1>Rozdział</h1><p>akapit</p></section>',
        pages=1,
        pending_pages=[],
        metadata={},
        warnings=[],
        stats={},
    )
    monkeypatch.setattr(module, "convert", lambda *_a, **_k: converted)

    outline, source = module._determine(_container_with_storage(path), cast("Any", _doc("pdf")))

    assert source == "headings"
    assert [item["title"] for item in outline] == ["Rozdział"]
    assert [item["level"] for item in outline] == [0]


def test_determine_pdf_without_bookmarks_needing_model_is_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """PDF bez zakładek, konwersja wymaga modelu (``pending``) → ``none`` (K21 §2 p. 2b/4)."""
    path = tmp_path / "a.pdf"
    path.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(module, "outline_from_pdf", lambda _path: [])
    pending = PendingPage(page=1, mode="vision", image_png=b"png", reason="image_cover")
    converted = ConvertedDocument(
        html='<section data-page="1"></section>',
        pages=1,
        pending_pages=[pending],
        metadata={},
        warnings=[],
        stats={},
    )
    monkeypatch.setattr(module, "convert", lambda *_a, **_k: converted)

    outline, source = module._determine(_container_with_storage(path), cast("Any", _doc("pdf")))

    assert (outline, source) == ([], "none")
