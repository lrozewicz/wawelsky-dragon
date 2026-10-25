"""Test normalizatora zrzutu MySQL 8 → MariaDB (brief T3, p. 1)."""

from pathlib import Path

from tests.fixtures.ragflow_v024.normalize import normalize

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "ragflow_v024"


def test_normalize_leaves_mysql8_dump_unchanged() -> None:
    """Zrzut fixture'u ładuje się na MariaDB bez zmian — reguł nie ma, funkcja jest identycznością.

    Test jest strażnikiem: gdy nowy zrzut wniesie składnię MySQL 8 nieobsługiwaną przez MariaDB,
    ten test padnie i wymusi dopisanie reguły w `normalize`.
    """
    schema = (FIXTURES_DIR / "schema.sql").read_text(encoding="utf-8")
    data = (FIXTURES_DIR / "data.sql").read_text(encoding="utf-8")

    assert normalize(schema) == schema
    assert normalize(data) == data
    assert normalize(normalize(schema)) == normalize(schema)  # idempotencja
