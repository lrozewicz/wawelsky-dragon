"""Testy unit czystych funkcji repozytoriów ingestii (brief T2) — bez bazy."""

import pytest

from app.db.repositories.chunk_vectors import table_name
from app.db.repositories.chunks import chunk_id
from app.db.repositories.documents import clock_hms

_CHUNK_ID_LEN = 16  # xxh64_hexdigest zwraca 16 znaków hex


def test_table_name() -> None:
    """Nazwa tabeli wektorów dla poprawnego wymiaru (brief T2)."""
    assert table_name(1024) == "chunk_vec_d1024"


@pytest.mark.parametrize("dim", [0, -1, True, "1024", 1.5, None])
def test_table_name_invalid(dim: object) -> None:
    """Nie-``int`` (także ``bool``) i wartości ≤ 0 → ValueError (brief T2)."""
    with pytest.raises(ValueError):
        table_name(dim)  # type: ignore[arg-type]


def test_clock_hms() -> None:
    """Prefiks linii progress_msg — godzina w UTC (brief T2)."""
    assert clock_hms(1790157600000 + 3_723_000) == "11:02:03"


def test_chunk_id_deterministic() -> None:
    """chunk_id: 16 znaków hex, deterministyczny, różny dla innej wartości ordinal."""
    first = chunk_id("d" * 32, "t" * 32, 0)
    assert len(first) == _CHUNK_ID_LEN
    int(first, 16)  # nie rzuca — poprawny zapis szesnastkowy
    assert first == chunk_id("d" * 32, "t" * 32, 0)
    assert first != chunk_id("d" * 32, "t" * 32, 1)
