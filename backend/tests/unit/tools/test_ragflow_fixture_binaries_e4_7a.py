"""Deterministyczność plików binarnych fixture'u RAGFlow v0.24 (brief E4-7a T3).

Sprawdza, że generator `tests/fixtures/ragflow_v024/make_binaries.py` daje powtarzalne
bajty i że pliki zacommitowane w repo są dokładnie jego wyjściem.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "ragflow_v024"
BUCKET = "d1e2f3a4b5c60718293a4b5c6d7e8f01"

#: nazwa pliku w repo → (funkcja generatora, magic bytes formatu)
BUILDERS = {
    "raport.pdf": ("build_pdf", b"%PDF-"),
    "umowa.docx": ("build_docx", b"PK"),
}


def _generator() -> ModuleType:
    """Moduł `make_binaries.py` wczytany po ścieżce (katalog fixture'u nie jest pakietem)."""
    path = FIXTURES_DIR / "make_binaries.py"
    spec = importlib.util.spec_from_file_location("make_binaries_e4_7a", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_build_is_deterministic(name: str) -> None:
    """(a)/(c) Dwa wywołania dają identyczne bajty, a plik zaczyna się od magic formatu."""
    builder_name, magic = BUILDERS[name]
    build = getattr(_generator(), builder_name)
    first = build()
    assert first == build()
    assert first.startswith(magic)


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_repo_blob_matches_generator(name: str) -> None:
    """(b) Bajty pliku w repo == bajty z generatora."""
    builder_name, _magic = BUILDERS[name]
    blob = FIXTURES_DIR / "files" / BUCKET / name
    assert blob.read_bytes() == getattr(_generator(), builder_name)()
