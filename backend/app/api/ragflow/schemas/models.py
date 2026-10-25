"""Modele OpenAPI katalogu modeli i dostawców (02 §5.5, złoto system--11..15.json)."""

from app.api.ragflow.schemas.common import ResponseModel


class Model(ResponseModel):
    """Element GET /models (upstream v0.27.2 models_api_service.list_tenant_added_models)."""

    model_id: str
    tenant_id: str
    tenant_name: str
    model_type: list[str]
    name: str
    provider_id: str
    provider_name: str
    instance_id: str
    instance_name: str
    rank: int


class DefaultModel(ResponseModel):
    """Element models[] w GET /models/default (models_api_service.list_tenant_default_models)."""

    model_id: str
    model_provider: str
    model_instance: str
    model_name: str
    model_type: str
    enable: bool


class DefaultModels(ResponseModel):
    """Data GET /models/default."""

    models: list[DefaultModel]


class ProviderUrl(ResponseModel):
    """Blok url/base_url dostawcy (upstream provider_api_service:145); intl tylko dla wybranych."""

    default: str


class Provider(ResponseModel):
    """Element GET /providers (provider_api_service.list_providers)."""

    has_instance: bool
    model_types: list[str]
    name: str
    url: ProviderUrl


class ProviderDetail(ResponseModel):
    """Data GET /providers/{name} (provider_api_service.show_provider)."""

    base_url: ProviderUrl
    name: str
    total_models: int


class ProviderInstance(ResponseModel):
    """Element GET /providers/{name}/instances (provider_api_service.list_provider_instances)."""

    id: str
    instance_name: str
    provider_id: str
    region: str
    status: str
