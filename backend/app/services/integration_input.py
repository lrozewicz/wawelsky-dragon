"""Parsery ciał JSON tras integracji SharePoint (kontrakt E4-3a §2).

Komunikaty 400 i kolejność walidacji dosłownie z oryginału
``sharepoint-sync/src/routes/integrations.ts`` (helpers ``requireString``,
``optionalString``, ``optionalStringArray``, ``optionalNumber``, ``optionalBoolean``).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar

from app.core.errors import ValidationFailed

__all__ = [
    "DEFAULT_EXCLUDED_LIBRARY_NAMES",
    "DEFAULT_IGNORED_EXTENSIONS",
    "DEFAULT_MAX_FILE_SIZE_BYTES",
    "DEFAULT_SCAN_INTERVAL_SECONDS",
    "IntegrationCreate",
    "IntegrationUpdate",
    "TestConnectionInput",
    "TestOverrides",
    "parse_create",
    "parse_test_connection",
    "parse_update",
]

DEFAULT_EXCLUDED_LIBRARY_NAMES = [
    "Site Assets",
    "Style Library",
    "Form Templates",
    "Site Pages",
    "Preservation Hold Library",
    "Customized Reports",
]
DEFAULT_IGNORED_EXTENSIONS = [
    "exe",
    "dll",
    "zip",
    "rar",
    "7z",
    "tar",
    "gz",
    "mp4",
    "mov",
    "avi",
    "iso",
    "dmg",
]
DEFAULT_MAX_FILE_SIZE_BYTES = 209_715_200
DEFAULT_SCAN_INTERVAL_SECONDS = 300


@dataclass(frozen=True)
class IntegrationCreate:
    """Zwalidowane ciało ``POST /api/integrations`` (listy to kopie)."""

    name: str
    dataset_id: str
    tenant_id: str
    client_id: str
    client_secret: str
    site_url: str
    excluded_library_names: list[str]
    max_file_size_bytes: int
    ignored_extensions: list[str]
    scan_interval_seconds: int
    delete_propagation: bool
    is_active: bool


@dataclass(frozen=True)
class IntegrationUpdate:
    """Ciało ``PUT /api/integrations/{id}``; ``None`` = pole bez zmiany."""

    name: str | None = None
    dataset_id: str | None = None
    tenant_id: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    site_url: str | None = None
    excluded_library_names: list[str] | None = None
    max_file_size_bytes: int | None = None
    ignored_extensions: list[str] | None = None
    scan_interval_seconds: int | None = None
    delete_propagation: bool | None = None
    is_active: bool | None = None


@dataclass(frozen=True)
class TestConnectionInput:
    """Ciało ``POST /api/integrations/test-connection``."""

    __test__: ClassVar[bool] = False  # pytest nie zbiera tej klasy jako testu

    tenant_id: str
    client_id: str
    client_secret: str
    site_url: str
    dataset_id: str | None
    excluded_library_names: list[str]


@dataclass(frozen=True)
class TestOverrides:
    """Nadpisania pól testu zapisanej integracji (``POST /api/integrations/{id}/test``).

    Wszystkie pola opcjonalne; ``None`` = użyj wartości zapisanej w bazie (kontrakt E4-3b §3).
    """

    __test__: ClassVar[bool] = False  # pytest nie zbiera tej klasy jako testu

    tenant_id: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    site_url: str | None = None
    dataset_id: str | None = None
    excluded_library_names: list[str] | None = None


def _required_string(body: Mapping[str, object], field: str) -> str:
    value = body.get(field)
    if not isinstance(value, str) or value.strip() == "":
        raise ValidationFailed(f"{field} is required and must be a non-empty string")
    return value.strip()


def _optional_string(
    body: Mapping[str, object], field: str, *, non_empty: bool = False
) -> str | None:
    """Opcjonalny string; ``non_empty`` (update) odrzuca ``""`` po ``strip()``."""
    value = body.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationFailed(f"{field} must be a string")
    if non_empty and value.strip() == "":
        raise ValidationFailed(f"{field} must be a non-empty string")
    return value.strip()


def _optional_secret(body: Mapping[str, object], field: str) -> str | None:
    """Sekret: brak/``None``/``""`` = bez zmiany (``None``); inaczej ``strip()``."""
    return _optional_string(body, field) or None


def _optional_string_list(body: Mapping[str, object], field: str) -> list[str] | None:
    value = body.get(field)
    if value is None:
        return None
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValidationFailed(f"{field} must be an array of strings")
    return list(value)


def _optional_number(body: Mapping[str, object], field: str, minimum: int) -> int | None:
    """Liczba: bez koercji (``bool`` to nie liczba), skończona, całkowita, ``>= minimum``."""
    value = body.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationFailed(f"{field} must be a number")
    if not math.isfinite(value):
        raise ValidationFailed(f"{field} must be a number")
    if value < minimum:
        raise ValidationFailed(f"{field} must be >= {minimum}")
    if value != int(value):
        raise ValidationFailed(f"{field} must be a number")
    return int(value)


def _optional_boolean(body: Mapping[str, object], field: str) -> bool | None:
    value = body.get(field)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValidationFailed(f"{field} must be a boolean")
    return value


def parse_create(body: Mapping[str, object]) -> IntegrationCreate:
    """Waliduje ciało create; pierwszy błąd wygrywa (kolejność jak w oryginale)."""
    name = _required_string(body, "name")
    dataset_id = _required_string(body, "dataset_id")
    tenant_id = _required_string(body, "tenant_id")
    client_id = _required_string(body, "client_id")
    client_secret = _required_string(body, "client_secret")
    site_url = _required_string(body, "site_url")
    excluded = _optional_string_list(body, "excluded_library_names")
    max_size = _optional_number(body, "max_file_size_bytes", 1)
    ignored = _optional_string_list(body, "ignored_extensions")
    interval = _optional_number(body, "scan_interval_seconds", 30)
    delete_propagation = _optional_boolean(body, "delete_propagation")
    is_active = _optional_boolean(body, "is_active")
    return IntegrationCreate(
        name,
        dataset_id,
        tenant_id,
        client_id,
        client_secret,
        site_url,
        list(DEFAULT_EXCLUDED_LIBRARY_NAMES) if excluded is None else excluded,
        DEFAULT_MAX_FILE_SIZE_BYTES if max_size is None else max_size,
        list(DEFAULT_IGNORED_EXTENSIONS) if ignored is None else ignored,
        DEFAULT_SCAN_INTERVAL_SECONDS if interval is None else interval,
        True if delete_propagation is None else delete_propagation,
        True if is_active is None else is_active,
    )


def parse_update(body: Mapping[str, object]) -> IntegrationUpdate:
    """Waliduje ciało update; brak/``None`` = bez zmiany, ``""`` w stringach = błąd."""
    return IntegrationUpdate(
        name=_optional_string(body, "name", non_empty=True),
        dataset_id=_optional_string(body, "dataset_id", non_empty=True),
        tenant_id=_optional_string(body, "tenant_id", non_empty=True),
        client_id=_optional_string(body, "client_id", non_empty=True),
        client_secret=_optional_secret(body, "client_secret"),
        site_url=_optional_string(body, "site_url", non_empty=True),
        excluded_library_names=_optional_string_list(body, "excluded_library_names"),
        max_file_size_bytes=_optional_number(body, "max_file_size_bytes", 1),
        ignored_extensions=_optional_string_list(body, "ignored_extensions"),
        scan_interval_seconds=_optional_number(body, "scan_interval_seconds", 30),
        delete_propagation=_optional_boolean(body, "delete_propagation"),
        is_active=_optional_boolean(body, "is_active"),
    )


def parse_test_connection(body: Mapping[str, object]) -> TestConnectionInput:
    """Waliduje ciało test-connection (wymagane creds; reszta opcjonalna)."""
    tenant_id = _required_string(body, "tenant_id")
    client_id = _required_string(body, "client_id")
    client_secret = _required_string(body, "client_secret")
    site_url = _required_string(body, "site_url")
    dataset_id = _optional_string(body, "dataset_id")
    excluded = _optional_string_list(body, "excluded_library_names")
    return TestConnectionInput(
        tenant_id,
        client_id,
        client_secret,
        site_url,
        dataset_id,
        list(DEFAULT_EXCLUDED_LIBRARY_NAMES) if excluded is None else excluded,
    )
