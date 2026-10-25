"""Modele OpenAPI metadanych datasetu (zadanie DS3, E2-1) — kształty złota --11..--18."""

from typing import Any, Literal

from app.api.ragflow.normalize.dataset_metadata import MetadataConfig
from app.api.ragflow.schemas.common import RequestModel, ResponseModel


class MetadataFieldConfig(ResponseModel):
    """Pole konfiguracji metadanych (``data.metadata[]``, --11/--12)."""

    key: str
    type: Literal["string", "list", "time", "number"]
    description: str | None
    enum: list[str] | None


class MetadataConfigData(ResponseModel):
    """Kształt data GET i PUT ``/datasets/{id}/metadata/config`` (--11/--12)."""

    metadata: list[MetadataFieldConfig]
    built_in_metadata: list[MetadataFieldConfig]


class MetadataSummaryFieldConfig(ResponseModel):
    """Pole podsumowania: typ wartości i pary (wartość, liczba) (--15/--17)."""

    type: Literal["string", "list", "time", "number"]
    values: list[list[str | int]]


class MetadataSummaryData(ResponseModel):
    """Kształt data GET ``/datasets/{id}/metadata/summary`` (--15/--17)."""

    summary: dict[str, MetadataSummaryFieldConfig]


class MetadataUpdateData(ResponseModel):
    """Kształt data POST ``/datasets/{id}/metadata/update`` (--16)."""

    matched_docs: int
    updated: int


class MetadataConfigRequest(RequestModel, MetadataConfig):
    """Ciało PUT ``metadata/config`` (normalize.dataset_metadata.MetadataConfig)."""


class MetadataUpdateRequest(RequestModel):
    """Ciało POST ``metadata/update`` — kształt wg upstream ``document_api.py:359-460``.

    Model opisuje wyłącznie OpenAPI: sprawdzenia (komunikaty 1:1 z upstream) robi
    ``normalize.dataset_metadata.metadata_update`` przed pydantic-em.
    """

    selector: dict[str, Any] | None = None
    updates: list[dict[str, Any]] | None = None
    deletes: list[dict[str, Any]] | None = None


REQUEST_MODELS: tuple[type[RequestModel], ...] = (MetadataConfigRequest, MetadataUpdateRequest)
