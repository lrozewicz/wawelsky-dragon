"""Testy parserów wejścia integracji (brief T2a; komunikaty z integrations.ts:144-184)."""

import math
from collections.abc import Callable, Mapping

import pytest

from app.core.errors import ValidationFailed
from app.services.integration_input import (
    DEFAULT_EXCLUDED_LIBRARY_NAMES,
    DEFAULT_IGNORED_EXTENSIONS,
    DEFAULT_MAX_FILE_SIZE_BYTES,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    IntegrationUpdate,
    parse_create,
    parse_test_connection,
    parse_update,
)

BASE: dict[str, object] = {
    "name": " A ",
    "dataset_id": "d",
    "tenant_id": "t",
    "client_id": "c",
    "client_secret": " s ",
    "site_url": "https://x",
}
CREDS: dict[str, object] = {
    "tenant_id": "t",
    "client_id": "c",
    "client_secret": "s",
    "site_url": "https://x",
}
DEFAULT_INTERVAL = 300
DEFAULT_MAX_SIZE = 209_715_200
OVERRIDDEN_INTERVAL = 60


def _error(body: dict[str, object], parse: Callable[[Mapping[str, object]], object]) -> str:
    """Zwraca komunikat ValidationFailed z wywołania parsera (wymaga błędu)."""
    with pytest.raises(ValidationFailed) as exc:
        parse(body)
    return exc.value.message


def test_parse_create_strips_and_fills_defaults() -> None:
    """Przykład z briefu: trim wartości i domyślne listy/liczby/bool."""
    data = parse_create(BASE)
    assert (data.name, data.client_secret) == ("A", "s")
    assert data.scan_interval_seconds == DEFAULT_SCAN_INTERVAL_SECONDS == DEFAULT_INTERVAL
    assert data.max_file_size_bytes == DEFAULT_MAX_FILE_SIZE_BYTES == DEFAULT_MAX_SIZE
    assert data.delete_propagation is True and data.is_active is True
    assert data.excluded_library_names == DEFAULT_EXCLUDED_LIBRARY_NAMES
    assert data.ignored_extensions == DEFAULT_IGNORED_EXTENSIONS


def test_parse_create_list_values_and_integral_float() -> None:
    """Podane listy wracają jako kopie; 60.0 akceptowane jako int(60)."""
    data = parse_create({**BASE, "ignored_extensions": ["a"], "scan_interval_seconds": 60.0})
    assert data.ignored_extensions == ["a"]
    assert data.scan_interval_seconds == OVERRIDDEN_INTERVAL
    assert isinstance(data.scan_interval_seconds, int)


def test_returned_lists_are_copies_of_defaults() -> None:
    """Mutacja wyniku nie zmienia stałych DEFAULT_*."""
    created = parse_create(BASE)
    created.excluded_library_names.append("x")
    created.ignored_extensions.append("x")
    updated = parse_update({"ignored_extensions": ["a"]})
    assert updated.ignored_extensions is not None
    updated.ignored_extensions.append("x")
    assert "x" not in DEFAULT_EXCLUDED_LIBRARY_NAMES
    assert DEFAULT_IGNORED_EXTENSIONS[-1] == "dmg"


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (
            {k: v for k, v in BASE.items() if k != "name"},
            "name is required and must be a non-empty string",
        ),
        ({**BASE, "name": "  "}, "name is required and must be a non-empty string"),
        ({**BASE, "name": "", "is_active": 1}, "name is required and must be a non-empty string"),
        ({**BASE, "dataset_id": 5}, "dataset_id is required and must be a non-empty string"),
        ({**BASE, "scan_interval_seconds": 10}, "scan_interval_seconds must be >= 30"),
        ({**BASE, "scan_interval_seconds": "60"}, "scan_interval_seconds must be a number"),
        ({**BASE, "scan_interval_seconds": 30.5}, "scan_interval_seconds must be a number"),
        ({**BASE, "scan_interval_seconds": math.nan}, "scan_interval_seconds must be a number"),
        ({**BASE, "scan_interval_seconds": math.inf}, "scan_interval_seconds must be a number"),
        ({**BASE, "max_file_size_bytes": True}, "max_file_size_bytes must be a number"),
        ({**BASE, "max_file_size_bytes": 0}, "max_file_size_bytes must be >= 1"),
        ({**BASE, "is_active": 1}, "is_active must be a boolean"),
        ({**BASE, "delete_propagation": "true"}, "delete_propagation must be a boolean"),
        (
            {**BASE, "ignored_extensions": ["a", 1]},
            "ignored_extensions must be an array of strings",
        ),
        (
            {**BASE, "excluded_library_names": "x"},
            "excluded_library_names must be an array of strings",
        ),
    ],
)
def test_parse_create_errors(body: dict[str, object], message: str) -> None:
    """Błędne typy/wartości → dokładny komunikat oryginału."""
    assert _error(body, parse_create) == message


def test_parse_update_empty_and_null_are_none() -> None:
    """Brak/None = bez zmiany; puste ciało daje same None."""
    assert parse_update({}) == IntegrationUpdate()
    assert parse_update({"name": None, "client_secret": None}) == IntegrationUpdate()


def test_parse_update_values() -> None:
    """Wartości trimowane; pusty sekret = None; liczby/bool/listy."""
    data = parse_update(
        {
            "name": " N ",
            "client_secret": "",
            "is_active": False,
            "scan_interval_seconds": 60.0,
            "ignored_extensions": ["a"],
        }
    )
    assert (data.name, data.client_secret) == ("N", None)
    assert data.is_active is False
    assert data.scan_interval_seconds == OVERRIDDEN_INTERVAL
    assert data.ignored_extensions == ["a"]


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"name": ""}, "name must be a non-empty string"),
        ({"dataset_id": " "}, "dataset_id must be a non-empty string"),
        ({"tenant_id": 5}, "tenant_id must be a string"),
        ({"client_id": ""}, "client_id must be a non-empty string"),
        ({"site_url": ""}, "site_url must be a non-empty string"),
        ({"client_secret": 5}, "client_secret must be a string"),
        ({"excluded_library_names": [1]}, "excluded_library_names must be an array of strings"),
        ({"max_file_size_bytes": "x"}, "max_file_size_bytes must be a number"),
        ({"scan_interval_seconds": 29}, "scan_interval_seconds must be >= 30"),
        ({"delete_propagation": 1}, "delete_propagation must be a boolean"),
    ],
)
def test_parse_update_errors(body: dict[str, object], message: str) -> None:
    """Błędy update: puste stringi i złe typy (komunikaty kontraktu §2)."""
    assert _error(body, parse_update) == message


def test_parse_test_connection_dataset_and_defaults() -> None:
    """dataset_id opcjonalny (trim); brak → None i domyślna lista wykluczeń."""
    data = parse_test_connection(CREDS)
    assert data.dataset_id is None
    assert data.excluded_library_names == DEFAULT_EXCLUDED_LIBRARY_NAMES
    full = parse_test_connection({**CREDS, "dataset_id": " d ", "excluded_library_names": ["a"]})
    assert (full.dataset_id, full.excluded_library_names) == ("d", ["a"])


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (
            {k: v for k, v in CREDS.items() if k != "client_secret"},
            "client_secret is required and must be a non-empty string",
        ),
        ({**CREDS, "site_url": ""}, "site_url is required and must be a non-empty string"),
        ({**CREDS, "dataset_id": 5}, "dataset_id must be a string"),
    ],
)
def test_parse_test_connection_errors(body: dict[str, object], message: str) -> None:
    """Brak wymaganych pól → komunikat 'required'; dataset_id nie-string → 'must be a string'."""
    assert _error(body, parse_test_connection) == message
