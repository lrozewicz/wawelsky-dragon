"""Wspólne modele i pomocniki OpenAPI (K6 §3-§4, kontrakt C2.1) — nazwy i pola dosłownie."""

from collections.abc import Mapping, Sequence
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ResponseModel(BaseModel):
    """Baza modeli odpowiedzi: nadmiarowe klucze zakazane (K6 §5 p. 4)."""

    model_config = ConfigDict(extra="forbid")


def _strip_null_defaults(schema: dict[str, Any]) -> None:
    """Usuwa ``default: null`` z właściwości schematu (K6 §3, C4).

    Pydantic dopisuje ``"default": null`` polom ``T | None = None``, a generator
    ``openapi-typescript`` (``defaultNonNullable``) czyni pola z ``default``
    WYMAGANYMI w ``schema.gen.ts``. Bez klucza ``default`` generator wydaje
    ``pole?: T | null``. Wywoływane przez ``json_schema_extra`` modelu żądań.
    """
    for prop in schema.get("properties", {}).values():
        if prop.get("default", object()) is None:
            del prop["default"]


class RequestModel(BaseModel):
    """Baza modeli żądań: pola ``default=None`` opcjonalne w ``schema.gen.ts`` (C4)."""

    model_config = ConfigDict(json_schema_extra=_strip_null_defaults)


class RagflowOk(ResponseModel, Generic[T]):  # noqa: UP046 — zapis z kontraktu C2.1, dosłownie
    """Koperta sukcesu RAGFlow (K3 #3)."""

    code: Literal[0]
    message: str
    data: T


class RagflowOkEmpty(ResponseModel):
    """Koperta sukcesu bez ``data`` (ok_result())."""

    code: Literal[0]
    message: str


class RagflowError(ResponseModel):
    """Koperta błędu RAGFlow: 401 i ``default`` (K3, kontrakt C2.2)."""

    code: int = Field(description="Kod błędu RAGFlow, różny od 0 (K3)")
    message: str
    data: None


class WdErrorBody(ResponseModel):
    """Ciało błędu wd (K3 #4)."""

    code: str
    message: str
    details: Any


class WdError(ResponseModel):
    """Koperta wd (K3 #4) — /health/ready 503."""

    error: WdErrorBody


class DocAgg(ResponseModel):
    """Wspólne: retrieval (T2) i reference completions (T3)."""

    count: int
    doc_id: str
    doc_name: str


def query_param(name: str, schema: dict[str, Any], description: str) -> dict[str, Any]:
    """Parametr zapytania OpenAPI (C2.1): name, in=query, required=False, schema, description."""
    return {
        "name": name,
        "in": "query",
        "required": False,
        "schema": schema,
        "description": description,
    }


def extra_doc(
    body: type[BaseModel] | None = None,
    *,
    required: bool = True,
    media_type: str = "application/json",
    query: Sequence[dict[str, Any]] = (),
    also: Mapping[str, type[BaseModel]] | None = None,
) -> dict[str, Any]:
    """Wartość openapi_extra: requestBody z $ref i parameters z query (gdy niepuste).

    ``also`` dokłada kolejne warianty treści żądania (media type → model); trasa ``POST /files``
    przyjmuje ``multipart/form-data`` uploadu ORAZ ``application/json`` folderu (C3).
    """
    doc: dict[str, Any] = {}
    if body is not None:
        body_ref = f"#/components/schemas/{body.__name__}"
        content = {media_type: {"schema": {"$ref": body_ref}}}
        for extra_media, extra_body in (also or {}).items():
            extra_ref = f"#/components/schemas/{extra_body.__name__}"
            content[extra_media] = {"schema": {"$ref": extra_ref}}
        doc["requestBody"] = {"required": required, "content": content}
    if query:
        doc["parameters"] = list(query)
    return doc
