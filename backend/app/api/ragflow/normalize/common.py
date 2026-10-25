"""Wspólne narzędzia normalizacji wejścia: Command, format błędów, parse_model, to_bool (C4)."""

import json
from collections.abc import Mapping

import pydantic
from fastapi import Request
from pydantic import BaseModel, ConfigDict

from app.api.ragflow.messages import MSG_FIELD_INVALID
from app.core.errors import ValidationFailed

# Upstream: value dłuższe niż 128 znaków skracane do 125 + '...' (validation_utils.py:227).
_VALUE_MAX_LEN = 128
_VALUE_HEAD_LEN = 125

_JSON_MIMETYPE = "application/json"
_MSG_BAD_CONTENT_TYPE = "Unsupported content type: Expected application/json, got {content_type}"
_MSG_MALFORMED_JSON = "Malformed JSON syntax: Missing commas/brackets or invalid encoding"
_MSG_NOT_OBJECT = "Invalid request payload: expected object, got {payload_type}"


class Command(BaseModel):
    """Wejściowy model żądania: nadmiarowe klucze ignorowane, obiekt zamrożony (C4)."""

    model_config = ConfigDict(extra="ignore", frozen=True)


def format_validation_error(err: pydantic.ValidationError) -> str:
    """Format upstream validation_utils.py:219-233 dosłownie.

    Dla każdego błędu: field jako loc łączone kropką, msg, value=str(input);
    value dłuższe niż 128 znaków → pierwsze 125 + '...'. Linie łączone '\\n'.
    """
    lines = []
    for error in err.errors():
        field = ".".join(map(str, error["loc"]))
        value = str(error["input"])
        if len(value) > _VALUE_MAX_LEN:
            value = value[:_VALUE_HEAD_LEN] + "..."
        lines.append(MSG_FIELD_INVALID.format(field=field, msg=error["msg"], value=value))
    return "\n".join(lines)


def parse_model[T: BaseModel](model: type[T], data: Mapping[str, object]) -> T:
    """Walidacja mapy na model; ValidationError → ValidationFailed z komunikatem upstream."""
    try:
        return model.model_validate(dict(data))
    except pydantic.ValidationError as err:
        raise ValidationFailed(format_validation_error(err)) from err


def to_bool(value: object) -> bool:
    """Flaga jak upstream: tylko łańcuch 'false' (case-insensitive) daje False."""
    return str(value).lower() != "false"


async def json_object_body(request: Request) -> dict[str, object]:
    """Ciało JSON trasy wg upstream ``validate_and_parse_json_request`` (VU:46-106) — błąd → 101.

    Kontrakt C9 (``json_body``) czyta ciało łagodnie; trasy RAGFlow wymagają ostrzej, jak
    upstream: najpierw ``Content-Type``, potem składnia JSON, na końcu typ ładunku. Puste
    ciało jest błędem składni (Flask ``get_json`` rzuca na pustym ciele), a JSON ``null``
    znaczy „brak pól" (``request.get_json() or {}``).
    """
    content_type = request.headers.get("content-type", "")
    mimetype = content_type.split(";")[0].strip().lower()
    if mimetype != _JSON_MIMETYPE:
        raise ValidationFailed(_MSG_BAD_CONTENT_TYPE.format(content_type=content_type))
    try:
        payload = json.loads(await request.body())
    except ValueError:
        raise ValidationFailed(_MSG_MALFORMED_JSON) from None
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValidationFailed(_MSG_NOT_OBJECT.format(payload_type=type(payload).__name__))
    return payload
