"""Schematy modeli instancji dostawcy (K13 §3 p. 7-10, §4 p. 6-8; CONTRACT E3-6b §T3).

Ciała żądań istnieją wyłącznie dla dokumentu OpenAPI — trasy czytają je przez ``json_body``
i walidują regułami K13 (kontrakt C9, K3 §5: brak echa ``input`` w odpowiedziach).
"""

from pydantic import Field

from app.api.ragflow.schemas.common import RequestModel, ResponseModel

# Nazwa typu modelu w API — pole opisowe schematu (K13 §2).
MODEL_TYPE_DOC = "chat|embedding|rerank|vision"

# Nazwa pola z wymiarem embeddingu — rozszerzenie WD (K13 §0 p. 5).
WD_DIMENSION_DOC = "Wymiar embeddingu (tylko `embedding`; w WD pole własne z prefiksem `wd_`)."

# Opis `extra` — klucz `max_concurrency` (K13 poprawka 2026-10-10 p. 1 i p. 4).
EXTRA_DOC = (
    "Dodatkowe parametry modelu. Klucz `max_concurrency` (liczba całkowita 1-32) ogranicza liczbę "
    "równoległych wywołań modelu w jednym zadaniu workera (wizja/OCR i embedding); brak klucza = "
    "wartość domyślna (`WD_VLM_CONCURRENCY`/`WD_EMBED_CONCURRENCY`)."
)


class InstanceModel(ResponseModel):
    """Element ``GET /providers/{name}/instances/{instance}/models`` (K13 §3)."""

    name: str
    model_type: str = Field(description=MODEL_TYPE_DOC)
    max_tokens: int | None
    status: str = Field(description="`active` albo `inactive` (z `models.is_active`)")
    rank: int
    extra: dict[str, object] = Field(description=EXTRA_DOC)
    wd_model_id: str
    wd_dimension: int | None = Field(default=None, description="Wymiar z `models.dimension`")
    wd_is_default: bool


class SupportedModel(ResponseModel):
    """Element ``…/models?supported=true``: identyfikator z bramki instancji (K13 §3)."""

    name: str
    rank: int
    model_type: str | None = Field(
        default=None,
        description="Typ modelu z katalogu OpenRouter (`chat`/`embedding`/`rerank`), gdy znany",
    )


class InstanceModelAddRequest(RequestModel):
    """Ciało ``POST …/models`` (K13 §3 p. 8)."""

    model_name: str
    model_type: str = Field(description=MODEL_TYPE_DOC)
    max_tokens: int | None = Field(default=None, description="Domyślnie 8192")
    extra: dict[str, object] | None = Field(default=None, description=EXTRA_DOC)
    wd_dimension: int | None = Field(default=None, description=WD_DIMENSION_DOC)


class InstanceModelUpdateRequest(RequestModel):
    """Ciało ``PATCH …/models/{model_name}`` — wymagane co najmniej jedno pole (K13 §3 p. 9)."""

    status: str | None = Field(default=None, description="`active` albo `inactive`")
    max_tokens: int | None = None
    extra: dict[str, object] | None = Field(default=None, description=EXTRA_DOC)


class InstanceModelsDeleteRequest(RequestModel):
    """Ciało ``DELETE …/models`` (K13 §3 p. 10)."""

    model_name: list[str] = Field(description="Nazwy modeli do usunięcia")


# Modele żądań do rejestracji w komponentach OpenAPI (`app.api.openapi.REQUEST_MODELS`) —
# konwencja modułów schematów ragflow (K6 §4). Wpis w `openapi.py` należy do TL (patrz raport T3).
REQUEST_MODELS: tuple[type[RequestModel], ...] = (
    InstanceModelAddRequest,
    InstanceModelUpdateRequest,
    InstanceModelsDeleteRequest,
)
