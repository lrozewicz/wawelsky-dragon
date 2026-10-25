"""Kontrakt E2-H2 C4 (T4): pola opcjonalne żądań bez ``default``, ``knn_top_k`` integer.

Test czyta wyłącznie commitowany ``backend/openapi.json`` (wzorzec ``test_update_me_schema.py``).
Hak ``json_schema_extra`` w ``RequestModel`` wycina ``default: null``; bez ``default`` generator
``openapi-typescript`` (``defaultNonNullable``) wydaje ``pole?: T | null`` zamiast wymaganego.
``knn_top_k`` jest ``integer`` bez ``anyOf`` null (DEC-151: ``null`` → kod 102).
"""

from __future__ import annotations

import functools
import json
from typing import Any

import pytest

from app.api.openapi_export import OPENAPI_PATH

pytestmark = pytest.mark.contract

# Modele z briefu T4 (C4) + wspólny ``RetrievalRequest``.
_MODELS = (
    "UpdateDefaultModelsRequest",
    "ProviderInstanceCreateRequest",
    "ProviderInstanceUpdateRequest",
    "InstanceModelAddRequest",
    "RetrievalRequest",
)

# Wymagane pola K13 §3 — muszą zostać w ``required``.
_K13_REQUIRED = {
    "ProviderInstanceCreateRequest": ("instance_name", "base_url"),
    "ProviderInstanceUpdateRequest": ("instance_name", "base_url"),
    "InstanceModelAddRequest": ("model_name", "model_type"),
}


@functools.cache
def _schemas() -> dict[str, Any]:
    """Schematy komponentów z commitowanego dokumentu (leniwie, raz)."""
    document = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    schemas: dict[str, Any] = document["components"]["schemas"]
    return schemas


@pytest.mark.parametrize("name", _MODELS)
def test_null_defaults_are_stripped(name: str) -> None:
    """Żadna właściwość nie ma ``default: null`` (inaczej schema.gen.ts wymagałby pola)."""
    properties = _schemas()[name]["properties"]
    offenders = [f for f, node in properties.items() if node.get("default", "brak") is None]
    assert offenders == []


def test_knn_top_k_is_plain_integer_and_optional() -> None:
    """``knn_top_k`` = integer bez ``anyOf`` null; pole opcjonalne (poza ``required``)."""
    request = _schemas()["RetrievalRequest"]
    schema = request["properties"]["knn_top_k"]
    assert schema["type"] == "integer"
    assert "anyOf" not in schema
    assert "knn_top_k" not in request.get("required", ())


@pytest.mark.parametrize(("name", "fields"), _K13_REQUIRED.items())
def test_k13_required_fields_stay_required(name: str, fields: tuple[str, ...]) -> None:
    """K13 §3: ``instance_name``/``base_url`` oraz ``model_name``/``model_type`` nadal wymagane."""
    assert set(fields) <= set(_schemas()[name].get("required", ()))
