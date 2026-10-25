"""Szacunek rozmiaru paczki eksportu (K19 §3 trasa 1, model E7-H1/T5).

Test pilnuje trafności modelu ``estimate_package_bytes`` na liczbach ZMIERZONYCH (a nie na
odtworzonej formule): oczekiwany rozmiar paczki pochodzi z rzeczywistego eksportu, a asercja
wymaga odchyłki ≤ 25 % w obie strony — dla wariantu z wektorami i bez. Pomiar w
``docs/perf/E7-H1.md``. Model bez wektorów: pliki źródłowe 1:1 + tekst po DEFLATE
(``TEXT_DEFLATE_RATIO``); wektory: ``chunki·dim·4`` + nagłówek NPY na część.
"""

from __future__ import annotations

import pytest

from app.services.kb_export import estimate_package_bytes
from app.services.kb_package.format import VECTOR_PART_ROWS

TOLERANCE = 0.25

# „Rocznik GUS" — pomiar docs/perf/E7-H1.md: 7251 chunków wymiaru 1024, 3 dokumenty (jeden plik
# ~23 MB losowych bajtów, więc wpisy ``files/*`` są nieściśliwe), treść chunków 5 800 800 B.
# Rzeczywisty rozmiar paczki: z wektorami 52 605 944 B, bez wektorów 25 017 721 B.
_GUS = {
    "chunks": 7251,
    "file_bytes": 24_158_208,
    "content_bytes": 5_800_800,
    "dimension": 1024,
}
_GUS_ACTUAL_WITHOUT_VECTORS = 25_017_721
_GUS_ACTUAL_WITH_VECTORS = 52_605_944


def _ratio(estimate: int, actual: int) -> float:
    """Odchyłka względna szacunku od rzeczywistości (znakowana)."""
    return estimate / actual - 1


@pytest.mark.parametrize("include_vectors", [False, True])
def test_estimate_is_within_tolerance_for_the_measured_gus_package(include_vectors: bool) -> None:
    """Paczka z prawdziwego eksportu „rocznika GUS": odchyłka ≤ 25 % (z wektorami i bez)."""
    estimate = estimate_package_bytes(include_vectors=include_vectors, **_GUS)
    actual = _GUS_ACTUAL_WITH_VECTORS if include_vectors else _GUS_ACTUAL_WITHOUT_VECTORS
    assert abs(_ratio(estimate, actual)) <= TOLERANCE, (estimate, actual)


def test_vectors_add_chunks_times_dimension_times_four_plus_headers() -> None:
    """Wektory NPY float32 bez kompresji: ``chunki·dim·4`` + nagłówek na każdą część."""
    base = {
        "file_bytes": 0,
        "content_bytes": 0,
        "dimension": 1536,
        "include_vectors": True,
    }
    one_part = estimate_package_bytes(chunks=3, **base)
    two_parts = estimate_package_bytes(chunks=VECTOR_PART_ROWS + 1, **base)
    assert one_part == 3 * 1536 * 4 + 128
    assert two_parts == (VECTOR_PART_ROWS + 1) * 1536 * 4 + 2 * 128


def test_files_do_not_compress_and_text_does() -> None:
    """Pliki wchodzą wg rozmiaru, tekst po współczynniku DEFLATE (mniejszy niż 1:1)."""
    raw = 10_000
    assert (
        estimate_package_bytes(
            chunks=0, file_bytes=raw, content_bytes=0, dimension=1024, include_vectors=False
        )
        == raw
    )
    compressed_text = estimate_package_bytes(
        chunks=0, file_bytes=0, content_bytes=raw, dimension=1024, include_vectors=False
    )
    assert 0 < compressed_text < raw
