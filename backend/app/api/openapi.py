"""Budowa dokumentu OpenAPI (K6 §4, kontrakt C2.2): komponenty żądań, błędy K3, bez 422."""

import json
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel

from app.api.ragflow.schemas import (
    auth,
    chats,
    chunks,
    completions,
    dataset_ingestions,
    dataset_metadata,
    datasets,
    dify,
    documents,
    documents_files,
    files,
    provider_instances,
    provider_models,
    retrieval,
    searches,
    sessions,
    system,
    users,
)
from app.api.ragflow.schemas.common import RagflowError

REQUEST_MODELS: tuple[type[BaseModel], ...] = (
    *auth.REQUEST_MODELS,
    *users.REQUEST_MODELS,
    *system.REQUEST_MODELS,
    *datasets.REQUEST_MODELS,
    *dataset_ingestions.REQUEST_MODELS,
    *dataset_metadata.REQUEST_MODELS,
    *dify.REQUEST_MODELS,
    *documents.REQUEST_MODELS,
    *documents_files.REQUEST_MODELS,
    *files.REQUEST_MODELS,
    *chunks.REQUEST_MODELS,
    *retrieval.REQUEST_MODELS,
    *searches.REQUEST_MODELS,
    *chats.REQUEST_MODELS,
    *sessions.REQUEST_MODELS,
    *completions.REQUEST_MODELS,
    *provider_instances.REQUEST_MODELS,
    *provider_models.REQUEST_MODELS,
)

ERR_401 = {
    "description": "Brak lub niepoprawne uwierzytelnienie (K3)",
    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/RagflowError"}}},
}
ERR_DEFAULT = {
    "description": "Błąd domenowy RAGFlow: HTTP 200 dla błędów domenowych (K3 #3), code ≠ 0",
    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/RagflowError"}}},
}

_METHODS = ("get", "post", "put", "patch", "delete")


def _strip_wd_422(schema: dict[str, Any]) -> None:
    """Usuwa deklarację 422 z operacji pod ``/api/wd/v1`` (kontrakt WP E4-3b §0 p. 6, §5)."""
    for path, path_item in schema["paths"].items():
        if not path.startswith("/api/wd/v1"):
            continue
        for method in _METHODS:
            if method in path_item:
                path_item[method]["responses"].pop("422", None)


def build_openapi(app: FastAPI) -> dict[str, Any]:
    """Dokument OpenAPI aplikacji; cache w ``app.openapi_schema`` (C2.2 krok po kroku)."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        routes=app.routes,
    )
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    models: tuple[type[BaseModel], ...] = (*REQUEST_MODELS, RagflowError)
    for model in models:
        js = model.model_json_schema(ref_template="#/components/schemas/{model}")
        defs: dict[str, Any] = js.pop("$defs", {})
        for name, body in (*defs.items(), (model.__name__, js)):
            if name in components and components[name] != body:
                raise ValueError(f"konflikt komponentu {name}")
            components[name] = body
    _strip_wd_422(schema)
    for path, path_item in schema["paths"].items():
        if not path.startswith("/api/v1"):
            continue
        for method in _METHODS:
            if method not in path_item:
                continue
            responses = path_item[method]["responses"]
            responses.pop("422", None)
            responses.setdefault("401", ERR_401)
            responses.setdefault("default", ERR_DEFAULT)
    for name in ("HTTPValidationError", "ValidationError"):
        # „Nie ma już" (C2.2): dump po każdym usunięciu — ref ValidationError siedzi
        # wewnątrz schematu HTTPValidationError, jeden dump przed pętlą zostawiłby sierotę.
        if f'"#/components/schemas/{name}"' not in json.dumps(schema):
            components.pop(name, None)
    schema["components"]["schemas"] = dict(sorted(components.items()))
    app.openapi_schema = schema
    return schema
