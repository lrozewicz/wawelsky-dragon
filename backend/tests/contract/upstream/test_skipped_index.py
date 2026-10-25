"""Spójność `SKIPPED.md` z listą pominięć harnessu (CONTRACT §4) — bez serwera WD."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

HERE = Path(__file__).resolve().parent
CONFTEST_PATH = HERE / "conftest.py"
SKIPPED_PATH = HERE / "SKIPPED.md"
# Kategorie dozwolone w tabeli (CONTRACT §4); `błąd-WD` jest zakazana — błąd WD naprawiamy.
ALLOWED_CATEGORIES = frozenset({"poza-zakresem", "odchyłka-WD", "środowisko"})
# Kolumny tabeli SKIPPED.md: id | test(y) | kategoria | powód | odsyłacz.
COLUMNS = 5


def _harness_conftest() -> ModuleType:
    """Moduł `conftest.py` harnessu wczytany przez pytest (nazwa zależy od trybu importu)."""
    for module in sys.modules.values():
        module_file = getattr(module, "__file__", None)
        if module_file is not None and Path(module_file).resolve() == CONFTEST_PATH:
            return module
    raise AssertionError(f"pytest nie wczytał {CONFTEST_PATH}")


def _skipped_rows() -> dict[str, str]:
    """Wiersze tabeli `SKIPPED.md`: id -> kategoria (pomija nagłówek i separator tabeli)."""
    rows: dict[str, str] = {}
    for line in SKIPPED_PATH.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != COLUMNS or cells[0] == "id" or set(cells[0]) <= {"-", ":"}:
            continue
        rows[cells[0]] = cells[2]
    return rows


def _reason_id(reason: str) -> str:
    """Identyfikator wiersza z powodu markera (`SKIPPED.md#S-100` -> `S-100`)."""
    prefix, _, row_id = reason.partition("#")
    assert prefix == "SKIPPED.md", f"powód bez odsyłacza do SKIPPED.md: {reason!r}"
    return row_id


def _used_reason_ids() -> set[str]:
    """Id wierszy użyte przez harness: wartości `SKIPPED` i powody dynamiczne z `conftest.py`."""
    conftest = _harness_conftest()
    reasons: set[str] = set(conftest.SKIPPED.values()) | set(conftest.DYNAMIC_SKIPPED)
    return {_reason_id(reason) for reason in reasons}


def test_every_reason_has_a_row() -> None:
    """Każdy powód pominięcia wskazuje istniejący wiersz `SKIPPED.md`."""
    missing = _used_reason_ids() - set(_skipped_rows())
    assert not missing, f"powody bez wiersza w SKIPPED.md: {sorted(missing)}"


def test_every_row_is_used() -> None:
    """Każdy wiersz `SKIPPED.md` jest przez harness używany (żadnych martwych wierszy)."""
    unused = set(_skipped_rows()) - _used_reason_ids()
    assert not unused, f"wiersze SKIPPED.md bez użycia: {sorted(unused)}"


def test_categories_are_allowed() -> None:
    """Kategorie wierszy należą do zbioru z CONTRACT §4 (`błąd-WD` zakazana)."""
    bad = {
        row_id: category
        for row_id, category in _skipped_rows().items()
        if category not in ALLOWED_CATEGORIES
    }
    assert not bad, f"niedozwolone kategorie: {bad}"
