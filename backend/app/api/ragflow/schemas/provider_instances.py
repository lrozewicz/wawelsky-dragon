"""Modele OpenAPI instancji dostawców (K13 §3, CONTRACT E3-6b §T2).

Żądania opisują tylko dokument (``extra_doc``); trasy czytają ciało przez ``json_body``, więc
walidacja pydantic nie echuje ``input`` (K3 §5). ``ProviderInstance`` (wpis listy) mieszka
w ``schemas/models.py`` — kształt dzielony ze złotem ``system--15``.
"""

from app.api.ragflow.schemas.common import RequestModel, ResponseModel


class ProviderInstanceDetail(ResponseModel):
    """Data GET /providers/{name}/instances/{instance} (K13 §3)."""

    id: str
    instance_name: str
    provider_id: str
    region: str
    base_url: str
    api_key: str
    status: str
    wd_managed: bool


class ProviderInstanceCreateRequest(RequestModel):
    """Ciało POST /providers/{name}/instances (K13 §3 p. 2)."""

    instance_name: str
    base_url: str
    api_key: str | None = None


class ProviderInstanceUpdateRequest(RequestModel):
    """Ciało PUT /providers/{name}/instances/{instance} (K13 §3 p. 4)."""

    instance_name: str
    base_url: str
    api_key: str | None = None


class ProviderInstancesDeleteRequest(RequestModel):
    """Ciało DELETE /providers/{name}/instances (K13 §3 p. 5)."""

    instances: list[str]


class ProviderConnectionRequest(RequestModel):
    """Ciało POST /providers/{name}/connection (K13 §3 p. 6)."""

    base_url: str | None = None
    api_key: str | None = None
    instance_id: str | None = None


REQUEST_MODELS: tuple[type[RequestModel], ...] = (
    ProviderInstanceCreateRequest,
    ProviderInstanceUpdateRequest,
    ProviderInstancesDeleteRequest,
    ProviderConnectionRequest,
)
