"""Normalizacja wejścia tras metadanych datasetu (zadanie DS3, E2-1).

Kształty i komunikaty z upstream v0.27.2: ``dataset_api.py:1430,1471`` (konfiguracja,
``AutoMetadataConfig``/``AutoMetadataField`` z ``api/utils/validation_utils.py:414-427``),
``document_api.py:316,359`` (podsumowanie i masowa zmiana) oraz ``dataset_api.py:59``
(spłaszczenie). Komunikaty błędów kształtu są dosłowne z handlera upstream (kod 102),
a błąd walidacji pól modelu → 101 (``parse_model``).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints

from app.api.ragflow.compat import CompatProfile
from app.api.ragflow.normalize.common import Command, parse_model
from app.core.errors import Conflict, ValidationFailed
from app.domain.retrieval.metadata import MetadataCondition, parse_metadata_condition
from app.services.dataset_metadata import (
    MSG_CONDITION_OBJECT,
    MSG_DELETE_ENTRY,
    MSG_DOC_IDS_LIST,
    MSG_LISTS,
    MSG_SELECTOR_OBJECT,
    MSG_UPDATE_ENTRY,
)

# Upstream ``REST_API_MAX_IDS`` (api/utils/pagination_utils.py:20) — limit listy identyfikatorów.
MAX_IDS = 100
MSG_IDS_LIMIT = "{field} must contain at most {limit} IDs"
MSG_IDS_LACK = "Lack of dataset_ids in query parameters"  # komunikat trasy upstream:59


class MetadataField(Command):
    """Pole konfiguracji metadanych (upstream ``AutoMetadataField``)."""

    # Upstream obcina białe znaki klucza przed sprawdzeniem długości
    # (``StringConstraints(strip_whitespace=True, min_length=1, max_length=255)``,
    # api/utils/validation_utils.py:417-421) — sam ``min_length`` przepuściłby "   ".
    key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    type: Literal["string", "list", "time", "number"]
    description: str | None = Field(default=None, max_length=65535)
    enum: list[str] | None = None


class MetadataConfig(Command):
    """Ciało PUT ``metadata/config`` (upstream ``AutoMetadataConfig``)."""

    metadata: list[MetadataField] = Field(default_factory=list)
    built_in_metadata: list[MetadataField] = Field(default_factory=list)


@dataclass(frozen=True)
class MetadataUpdate:
    """Ciało POST ``metadata/update`` po sprawdzeniach kształtu (upstream:359-460)."""

    document_ids: tuple[str, ...]
    condition: MetadataCondition | None
    updates: tuple[dict[str, Any], ...]
    deletes: tuple[dict[str, Any], ...]


def metadata_config(body: Mapping[str, Any], profile: CompatProfile) -> MetadataConfig:
    """Walidacja PUT ``metadata/config`` (profil ignorowany — jedno ujęcie v0.27.2)."""
    return parse_model(MetadataConfig, body)


def metadata_update(body: Mapping[str, Any], profile: CompatProfile) -> MetadataUpdate:
    """Walidacja POST ``metadata/update`` — komunikaty kształtu 1:1 z upstream (102).

    Sprawdzane jest to samo, co w handlerze upstream: typ ``selector``/``updates``/
    ``deletes``, typ ``metadata_condition`` i ``document_ids``, obecność ``key``
    w każdej zmianie i ``value`` w każdej aktualizacji; warunek metadanych idzie do
    ``parse_metadata_condition`` (nieznany operator → 0 trafień, kod 0).
    """
    selector = body.get("selector") or {}
    updates = body.get("updates") or []
    deletes = body.get("deletes") or []
    if not isinstance(selector, Mapping):
        raise Conflict(MSG_SELECTOR_OBJECT)
    if not isinstance(updates, list) or not isinstance(deletes, list):
        raise Conflict(MSG_LISTS)
    metadata_condition = selector.get("metadata_condition") or {}
    if metadata_condition and not isinstance(metadata_condition, Mapping):
        raise Conflict(MSG_CONDITION_OBJECT)
    document_ids = selector.get("document_ids") or []
    if not isinstance(document_ids, list):
        raise Conflict(MSG_DOC_IDS_LIST)
    for update in updates:
        if not isinstance(update, Mapping) or not update.get("key") or "value" not in update:
            raise Conflict(MSG_UPDATE_ENTRY)
    for delete in deletes:
        if not isinstance(delete, Mapping) or not delete.get("key"):
            raise Conflict(MSG_DELETE_ENTRY)
    condition = parse_metadata_condition(metadata_condition) if metadata_condition else None
    return MetadataUpdate(
        document_ids=tuple(str(item) for item in document_ids),
        condition=condition,
        updates=tuple(dict(item) for item in updates),
        deletes=tuple(dict(item) for item in deletes),
    )


def metadata_doc_ids(query: Mapping[str, str]) -> tuple[str, ...] | None:
    """``doc_ids`` z query (przecinki) — brak/puste → None (upstream ``document_api.py:336``)."""
    raw = query.get("doc_ids") or ""
    if not raw:
        return None
    doc_ids = tuple(raw.split(","))
    if len(doc_ids) > MAX_IDS:
        raise ValidationFailed(MSG_IDS_LIMIT.format(field="doc_ids", limit=MAX_IDS))
    return doc_ids


def metadata_dataset_ids(query: Mapping[str, str]) -> tuple[str, ...]:
    """``dataset_ids`` z query (przecinki, puste odrzucone) — brak → 102 (upstream:59)."""
    dataset_ids = tuple(part for part in (query.get("dataset_ids") or "").split(",") if part)
    if not dataset_ids:
        raise Conflict(MSG_IDS_LACK)
    if len(dataset_ids) > MAX_IDS:
        raise ValidationFailed(MSG_IDS_LIMIT.format(field="dataset_ids", limit=MAX_IDS))
    return dataset_ids


def config_payload(config: MetadataConfig) -> dict[str, list[dict[str, Any]]]:
    """Konfiguracja do zapisu i odpowiedzi: ``model_dump`` pól z ``enum: null`` (upstream)."""
    return {
        "metadata": [field.model_dump() for field in config.metadata],
        "built_in_metadata": [field.model_dump() for field in config.built_in_metadata],
    }
