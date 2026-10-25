"""Pomocnik testu kształtów (K6 §5 p. 4, CONTRACT C4.2) — walidacja odpowiedzi
modelem 200 z openapi.json.
"""

import functools
import json
from collections.abc import Iterator, Sequence
from typing import Any, cast

import httpx
from fastapi.routing import APIRoute, _IncludedRouter
from pydantic import BaseModel
from starlette.routing import BaseRoute

from app.api.openapi_export import OPENAPI_PATH, export_settings
from app.api.ragflow.sse import TERMINATOR
from app.main import create_app


@functools.cache
def spec() -> dict[str, Any]:
    """openapi.json wczytany leniwie, raz (obraz test-ocr nie ma pliku — krok binaries)."""
    loaded: dict[str, Any] = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    return loaded


_OK = 200
_METHODS = ("get", "post", "put", "patch", "delete")


def operation(operation_id: str) -> dict[str, Any]:
    """Obiekt operacji z spec() o danym operationId; brak → KeyError(operation_id)."""
    for path_item in spec()["paths"].values():
        for method in _METHODS:
            candidate: dict[str, Any] = path_item.get(method) or {}
            if candidate.get("operationId") == operation_id:
                return candidate
    raise KeyError(operation_id)


def response_component(operation_id: str) -> str:
    """Nazwa komponentu z $ref odpowiedzi 200 (application/json) — część po ostatnim ``/``."""
    ref: str = operation(operation_id)["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    return ref.rsplit("/", 1)[-1]


def _flatten(routes: Sequence[BaseRoute]) -> Iterator[APIRoute]:
    """APIRoute z tras aplikacji; _IncludedRouter (fastapi 0.141, leniwe include) — rekurencyjnie."""  # noqa: E501
    for route in routes:
        if isinstance(route, _IncludedRouter):
            yield from _flatten(route.original_router.routes)
        elif isinstance(route, APIRoute):
            yield route


@functools.cache
def _routes() -> dict[str, APIRoute]:
    """Mapa operationId → APIRoute bieżącej aplikacji (budowana leniwie, raz)."""
    return {
        route.operation_id: route
        for route in _flatten(create_app(export_settings()).routes)
        if route.operation_id
    }


def response_model(operation_id: str) -> type[BaseModel]:
    """Model odpowiedzi 200 operacji z trasy FastAPI (route.responses[200]["model"])."""
    model: type[BaseModel] = _routes()[operation_id].responses[200]["model"]
    return model


def check(operation_id: str, resp: httpx.Response) -> str:
    """Waliduje odpowiedź JSON modelem 200; zwraca nazwę komponentu z openapi.json."""
    assert resp.status_code == _OK, f"{operation_id}: {resp.text}"
    assert resp.json()["code"] == 0, f"{operation_id}: {resp.text}"
    response_model(operation_id).model_validate(resp.json(), strict=True)
    return response_component(operation_id)


def check_raw(operation_id: str, resp: httpx.Response) -> str:
    """Waliduje odpowiedź JSON bez koperty ``code`` (system_healthz); zwraca nazwę komponentu."""
    assert resp.status_code == _OK, f"{operation_id}: {resp.text}"
    response_model(operation_id).model_validate(resp.json(), strict=True)
    return response_component(operation_id)


def check_sse(operation_id: str, resp: httpx.Response) -> str:
    """Waliduje strumień SSE: terminator oraz pierwszą i ostatnią ramkę modelem ``data``."""
    frames = resp.content.split(b"\n\n")[:-1]
    assert frames[-1] == TERMINATOR.removesuffix(b"\n\n"), f"{operation_id}: {resp.text}"
    # ramki[0][5:] — odcina prefiks ``data:`` (5 bajtów); model data z koperty Ok[CompletionData].
    model = cast(type[BaseModel], response_model(operation_id).model_fields["data"].annotation)
    model.model_validate(json.loads(frames[0][5:])["data"], strict=True)
    model.model_validate(json.loads(frames[-2][5:])["data"], strict=True)
    return model.__name__


def response_components() -> set[str]:
    """Zbiór komponentów 200 operacji /api/v1 z $ref plus CompletionData (SSE).

    Operacje bez ``200``, bez ``content``, bez ``application/json`` albo bez ``$ref`` pomijamy
    (przekierowania, download i operacje przed T2/T3); kompletność pilnuje test_openapi_current.py.
    """
    names: set[str] = {"CompletionData"}
    for path, path_item in spec()["paths"].items():
        if not path.startswith("/api/v1"):
            continue
        for method in _METHODS:
            op: dict[str, Any] = path_item.get(method) or {}
            responses = op.get("responses", {})
            content = responses.get("200", {}).get("content", {})
            schema: dict[str, Any] = content.get("application/json", {}).get("schema", {})
            ref: str | None = schema.get("$ref")
            if ref:
                names.add(ref.rsplit("/", 1)[-1])
    return names
