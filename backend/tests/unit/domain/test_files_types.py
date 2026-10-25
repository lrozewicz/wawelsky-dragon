"""Testy `filename_type` (E4-5a T1, K16 §1 p. 6) — przykłady dosłownie z briefu T1."""

import pytest

from app.domain.files import FOLDER_TYPE, filename_type


def test_filename_type_brief_examples() -> None:
    """Przykłady wejście → wyjście z briefu T1 (tabela)."""
    assert filename_type("ragflow_intro.txt") == "doc"
    assert filename_type("a.pdf") == "pdf"


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("a.pdf", "pdf"),
        ("A.PDF", "pdf"),
        ("ragflow_intro.txt", "doc"),
        ("report.docx", "doc"),
        ("dane.csv", "doc"),
        ("notatki.md", "doc"),
        ("song.mp3", "aural"),
        ("dzwiek.wav", "aural"),
        ("obraz.png", "visual"),
        ("foto.JPEG", "visual"),
        ("film.mp4", "visual"),
        ("archiwum.zip", "other"),
        ("bez_rozszerzenia", "other"),
        ("", "other"),
    ],
)
def test_filename_type_values(filename: str, expected: str) -> None:
    """Rozszerzenie decyduje o typie; nierozpoznane → ``other``."""
    assert filename_type(filename) == expected


def test_filename_type_uses_basename_and_lowercase() -> None:
    """Ścieżka i wielkość liter nie zmieniają typu (normalizacja jak w upstream)."""
    assert filename_type("katalog/Umowa.PDF") == "pdf"
    assert filename_type("a/b/c/plik.TXT") == "doc"
    assert filename_type("  spacja.txt  ") == "doc"


def test_filename_type_rejects_empty_and_oversized() -> None:
    """Pusta nazwa oraz dłuższa niż limit (255) → ``other``."""
    assert filename_type("   ") == "other"
    assert filename_type("x" * 252 + ".txt") == "other"
    assert filename_type("x" * 251 + ".txt") == "doc"


def test_folder_type_constant() -> None:
    """Folder to osobna stała — ``filename_type`` jej nie zwraca (§D2)."""
    assert FOLDER_TYPE == "folder"
    assert filename_type("folder") == "other"
