"""Prezentery metadanych datasetu (zadanie DS3, E2-1) — kształty odpowiedzi v0.27.2."""

from collections.abc import Mapping, Sequence
from typing import Any

from app.services.dataset_metadata import (
    BUILT_IN_KEY,
    METADATA_KEY,
    MetadataSummaryField,
    MetadataUpdateResult,
)


def metadata_field(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Pole konfiguracji metadanych: zawsze 4 klucze złota --11/--12 (``enum`` null gdy brak)."""
    enum = raw.get("enum")
    return {
        "key": raw.get("key"),
        "type": raw.get("type"),
        "description": raw.get("description"),
        "enum": list(enum) if isinstance(enum, list) else None,
    }


def config_data(config: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    """Kształt data GET i PUT ``metadata/config`` (--11/--12): dwie listy pól, w tej kolejności."""
    return {
        METADATA_KEY: [metadata_field(field) for field in config[METADATA_KEY]],
        BUILT_IN_KEY: [metadata_field(field) for field in config[BUILT_IN_KEY]],
    }


def summary_data(summary: Mapping[str, MetadataSummaryField]) -> dict[str, Any]:
    """Kształt data GET ``metadata/summary`` (--15/--17): ``summary`` z listami par wartości."""
    return {
        "summary": {
            key: {"type": field.type, "values": [[value, count] for value, count in field.values]}
            for key, field in summary.items()
        }
    }


def update_data(result: MetadataUpdateResult) -> dict[str, Any]:
    """Kształt data POST ``metadata/update`` (--16)."""
    return {"matched_docs": result.matched_docs, "updated": result.updated}


def flattened_data(
    flattened: Mapping[str, Mapping[str, Sequence[str]]],
) -> dict[str, dict[str, list[str]]]:
    """Kształt data GET ``metadata/flattened`` (--18): pola i wartości posortowane po kluczu."""
    return {
        field: {value: list(doc_ids) for value, doc_ids in sorted(values.items())}
        for field, values in sorted(flattened.items())
    }
