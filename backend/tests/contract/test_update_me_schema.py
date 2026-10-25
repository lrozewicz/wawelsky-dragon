"""Kontrakt E3-6a §3 (T5): ``UpdateMeRequest`` bez ``required`` i bez ``default`` w OpenAPI.

Test czyta wyłącznie commitowany dokument ``backend/openapi.json`` (wzorzec
``test_openapi_current.py``), bez uruchamiania aplikacji i bez bazy. ``openapi-typescript``
z domyślną opcją ``defaultNonNullable`` czyni pole opcjonalnym tylko wtedy, gdy w JSON Schema
nie ma ``default`` — dlatego generowany ``schema.gen.ts`` ma ``password?: string | null``.
Zachowanie modelu (``= None``) pilnuje osobny przypadek na samym pydanticu.
"""

from __future__ import annotations

import functools
import json
from typing import Any

import pytest

from app.api.openapi_export import OPENAPI_PATH
from app.api.ragflow.schemas.users import UpdateMeRequest

pytestmark = pytest.mark.contract

FIELDS = ("password", "new_password", "nickname", "avatar", "language", "timezone")


@functools.cache
def _schema() -> dict[str, Any]:
    """Schemat ``UpdateMeRequest`` z commitowanego dokumentu (leniwie, raz)."""
    document: dict[str, Any] = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    schema = document["components"]["schemas"]["UpdateMeRequest"]
    assert isinstance(schema, dict)
    return schema


def test_update_me_request_has_no_required_fields() -> None:
    """Brak ``required`` — każde pole ciała ``PATCH /users/me`` jest opcjonalne."""
    assert "required" not in _schema()


def test_update_me_request_properties_have_no_default() -> None:
    """Żadna właściwość nie ma ``default`` (inaczej schema.gen.ts wymagałby pola)."""
    properties = _schema()["properties"]

    assert set(properties) == set(FIELDS)
    offenders = [name for name, node in properties.items() if "default" in node]
    assert offenders == []


def test_update_me_request_still_accepts_an_empty_body() -> None:
    """Model pydantic bez zmian: puste ciało → wszystkie pola ``None`` (K3 §5)."""
    assert UpdateMeRequest().model_dump() == dict.fromkeys(FIELDS, None)
    assert UpdateMeRequest(language="pl").model_dump()["language"] == "pl"
