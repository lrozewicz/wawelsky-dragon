"""Testy presetów i błędów chunkingu (CONTRACT WP E1-5 C4, C2.2)."""

import re

import pytest

from app.core.error_codes import RetCode
from app.core.errors import ValidationFailed
from app.domain.chunking.errors import DocumentTooLarge, UnsupportedChunkMethod
from app.domain.chunking.presets import (
    ALL_LEVELS,
    LAWS_PATTERNS,
    PAPER_PATTERNS,
    UNSUPPORTED,
    preset_for,
)
from app.domain.chunking.types import ChunkPreset

# Poziomy podziału na nagłówkach — nazwane stałe zamiast liczb magicznych (PLR2004).
MANUAL_LEVELS = (1, 2, 3)
BOOK_LEVELS = (1, 2)

_LAWS_EXAMPLE = "Art. 12. Treść przepisu"
_LAWS_NEGATIVE = "Artykuł prasowy"
_PAPER_SECTION = "2. Introduction"
_PAPER_PLAIN_SENTENCE = "Introduction of new rules to the market"

_TOO_MANY_TOKENS = 9000
_TOKEN_LIMIT = 8000

_OUTSIDE_PRESETS = ("foo", "", "Naive")


@pytest.mark.parametrize(
    ("metoda", "oczekiwany_preset"),
    [
        ("naive", ChunkPreset("naive", ALL_LEVELS)),
        ("email", ChunkPreset("email", ALL_LEVELS)),
        ("manual", ChunkPreset("manual", MANUAL_LEVELS)),
        ("book", ChunkPreset("book", BOOK_LEVELS)),
        ("laws", ChunkPreset("laws", ALL_LEVELS, boundary_patterns=LAWS_PATTERNS)),
        (
            "paper",
            ChunkPreset(
                "paper", ALL_LEVELS, boundary_patterns=PAPER_PATTERNS, strip_page_furniture=True
            ),
        ),
        ("presentation", ChunkPreset("presentation", mode="presentation")),
        ("one", ChunkPreset("one", mode="one")),
        ("picture", ChunkPreset("picture", mode="one")),
        ("qa", ChunkPreset("qa", mode="qa")),
        ("table", ChunkPreset("table", mode="table")),
    ],
)
def test_preset_for(metoda, oczekiwany_preset):
    """Pełna tabela C4: chunk_method → ChunkPreset."""
    assert preset_for(metoda) == oczekiwany_preset


def test_naive_and_email_general_mode():
    """Presety tekstowe mają tryb general (C4)."""
    assert preset_for("naive").mode == "general"
    assert preset_for("email").mode == "general"


def test_laws_boundary_patterns():
    """Wzorce laws łapią 'Art. 12.', nie łapią zwykłego tekstu (C4)."""
    assert preset_for("laws").boundary_patterns == LAWS_PATTERNS
    assert any(re.match(p, _LAWS_EXAMPLE) for p in LAWS_PATTERNS)
    assert not any(re.match(p, _LAWS_NEGATIVE) for p in LAWS_PATTERNS)


def test_paper_furniture_and_patterns():
    """Paper zdejmuje szatę graficzną i łapie numerowane sekcje, nie zwykłe zdania (C4)."""
    preset = preset_for("paper")
    assert preset.strip_page_furniture is True
    assert preset.boundary_patterns == PAPER_PATTERNS
    assert any(re.match(p, _PAPER_SECTION) for p in PAPER_PATTERNS)
    assert not any(re.match(p, _PAPER_PLAIN_SENTENCE) for p in PAPER_PATTERNS)


@pytest.mark.parametrize(
    ("metoda", "tryb"),
    [
        ("picture", "one"),
        ("one", "one"),
        ("presentation", "presentation"),
        ("qa", "qa"),
        ("table", "table"),
    ],
)
def test_mode_equals_name(metoda, tryb):
    """Presety specjalne: mode == nazwa (C4)."""
    assert preset_for(metoda).mode == tryb


@pytest.mark.parametrize("metoda", sorted(UNSUPPORTED) + list(_OUTSIDE_PRESETS))
def test_unsupported_chunk_method(metoda):
    """Nieznany/niewspierany chunk_method → UnsupportedChunkMethod (code 101, C2.2)."""
    with pytest.raises(UnsupportedChunkMethod) as exc_info:
        preset_for(metoda)
    exc = exc_info.value
    assert isinstance(exc, ValidationFailed)
    assert exc.code == RetCode.ARGUMENT_ERROR
    assert str(exc) == f"chunk_method {metoda} is not supported by this server"


def test_document_too_large():
    """DocumentTooLarge: komunikat, kod 101 i szczegóły tokens/max_tokens (C2.2)."""
    exc = DocumentTooLarge(_TOO_MANY_TOKENS, _TOKEN_LIMIT)
    assert str(exc) == "document too large for 'one'"
    assert exc.code == RetCode.ARGUMENT_ERROR
    assert exc.details == {"tokens": _TOO_MANY_TOKENS, "max_tokens": _TOKEN_LIMIT}
