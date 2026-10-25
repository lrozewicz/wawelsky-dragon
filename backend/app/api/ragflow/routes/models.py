"""Trasy /api/v1/models i /api/v1/providers (brief SYS p. 4, złoto system--11..15.json)."""

from __future__ import annotations

import hashlib
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.auth.principal import PrincipalDep, container_of
from app.api.ragflow.envelope import ok
from app.api.ragflow.schemas.common import RagflowOk
from app.api.ragflow.schemas.models import (
    DefaultModels,
    Model,
    Provider,
    ProviderDetail,
)
from app.core.errors import NotFound
from app.services.model_catalog import CatalogModel, ModelCatalogService, ProviderGroup

# Nazwa dostawcy i jej identyfikator mieszkają w warstwie usług (`provider_common`) — usługi
# nie mogą importować tras (import-linter „compat-isolated"), a potrzebują ich sonda i trasy
# instancji. Re-eksport zachowuje dotychczasowe nazwy publiczne tego modułu (CONTRACT E3-6b §T1).
from app.services.provider_common import PROVIDER_NAMES, provider_id, provider_name

# Jawny re-eksport (DEC-075): `PROVIDER_NAMES` nie jest używane w tym module, ale zostaje
# publiczną nazwą `routes.models` dla tras instancji (T2/T3).
__all__ = ["PROVIDER_NAMES", "provider_id", "provider_name"]

router = APIRouter(prefix="/api/v1", tags=["models"])

# Nazwa typu modelu w API: WD trzyma 'image2text' (DDL 0001), upstream i złoto — 'vision'.
MODEL_TYPE_NAMES: dict[str, str] = {"image2text": "vision"}

# Kolejność typów w /models/default — jak MODEL_TYPE_TO_FIELD upstreamu (modele z rejestru).
DEFAULT_ORDER: tuple[str, ...] = ("chat", "embedding", "rerank", "image2text")

# Ranga modelu: WD nie ma rangi fabrycznej, upstream domyślnie 500 (_to_int w models_api_service).
DEFAULT_RANK = 500

# Nazwa instancji dostawcy dla modeli bez ``instance_id``: syntetyczna „default" (K13 §0 p. 2).
INSTANCE_NAME = "default"

# model_types dostawcy to katalog zdolności fabryki; WD go nie ma (jedna bramka OpenAI-compatible)
# → pusta lista, jak w złocie system--13.json (brief SYS p. 2). Zbiór realnie używanych typów
# zwraca GET /models.
PROVIDER_MODEL_TYPES: list[str] = []


def model_type_name(raw: str) -> str:
    """Typ modelu w nazewnictwie upstreamu ('image2text' → 'vision')."""
    return MODEL_TYPE_NAMES.get(raw, raw)


def instance_id(raw: str, base_url: str | None) -> str:
    """Identyfikator instancji: ustalona grupa modeli (dostawca, base_url) — stabilny skrót."""
    return hashlib.sha256(f"wd-instance:{raw}:{base_url or ''}".encode()).hexdigest()[:32]


def model_entry(row: CatalogModel, *, tenant_id: str, tenant_name: str) -> dict[str, Any]:
    """Element GET /models (upstream models_api_service.list_tenant_added_models)."""
    return {
        "model_id": row.id,
        "tenant_id": tenant_id,
        "tenant_name": tenant_name,
        "model_type": [model_type_name(row.model_type)],
        "name": row.name,
        "provider_id": provider_id(row.provider),
        "provider_name": provider_name(row.provider),
        "instance_id": row.instance_id or instance_id(row.provider, row.base_url),
        "instance_name": row.instance_name or INSTANCE_NAME,
        "rank": DEFAULT_RANK,
    }


def default_entry(row: CatalogModel) -> dict[str, Any]:
    """Element ``models[]`` w GET /models/default (list_tenant_default_models upstreamu)."""
    return {
        "model_id": row.id,
        "model_provider": provider_name(row.provider),
        "model_instance": row.instance_name or INSTANCE_NAME,
        "model_name": row.name,
        "model_type": model_type_name(row.model_type),
        "enable": True,
    }


def provider_entry(group: ProviderGroup) -> dict[str, Any]:
    """Element GET /providers (provider_api_service.list_providers)."""
    return {
        "has_instance": group.has_instance,
        "model_types": list(PROVIDER_MODEL_TYPES),
        "name": provider_name(group.name),
        "url": {"default": group.base_url or ""},
    }


def provider_detail_entry(group: ProviderGroup) -> dict[str, Any]:
    """Data GET /providers/{name} (show_provider); total_models = liczba modeli rejestru."""
    return {
        "base_url": {"default": group.base_url or ""},
        "name": provider_name(group.name),
        "total_models": group.model_count,
    }


def _svc(request: Request) -> ModelCatalogService:
    """Usługa katalogu per żądanie (C0 p. 2)."""
    return ModelCatalogService(container_of(request))


async def _group(svc: ModelCatalogService, name_or_id: str) -> ProviderGroup:
    """Dostawca po nazwie upstreamu, nazwie kolumny albo id; brak → 102 (upstream show_provider)."""
    for group in await svc.providers():
        if name_or_id in (group.name, provider_name(group.name), provider_id(group.name)):
            return group
    raise NotFound(f"Provider {name_or_id} not found")


@router.get(
    "/models",
    operation_id="models_list",
    responses={200: {"model": RagflowOk[list[Model]]}},
)
async def list_models(request: Request, principal: PrincipalDep) -> JSONResponse:
    """Lista modeli rejestru WD z id dostawcy i instancji (złoto system--11.json)."""
    svc = _svc(request)
    rows = await svc.models()
    tenant = await svc.tenant_name(principal.user_id)
    return ok([model_entry(row, tenant_id=principal.user_id, tenant_name=tenant) for row in rows])


@router.get(
    "/models/default",
    operation_id="models_default",
    responses={200: {"model": RagflowOk[DefaultModels]}},
)
async def default_models(request: Request, principal: PrincipalDep) -> JSONResponse:
    """Domyślne modele w kolejności typów upstreamu (złoto system--12.json)."""
    rows = {row.model_type: row for row in await _svc(request).defaults()}
    ordered = [rows[name] for name in DEFAULT_ORDER if name in rows]
    return ok({"models": [default_entry(row) for row in ordered]})


@router.get(
    "/providers",
    operation_id="providers_list",
    responses={200: {"model": RagflowOk[list[Provider]]}},
    tags=["providers"],
)
async def list_providers(request: Request, principal: PrincipalDep) -> JSONResponse:
    """Dostawcy obecni w rejestrze modeli (złoto system--13.json)."""
    return ok([provider_entry(group) for group in await _svc(request).providers()])


@router.get(
    "/providers/{name}",
    operation_id="provider_get",
    responses={200: {"model": RagflowOk[ProviderDetail]}},
    tags=["providers"],
)
async def get_provider(name: str, request: Request, principal: PrincipalDep) -> JSONResponse:
    """Dostawca po nazwie albo id (złoto system--14.json)."""
    return ok(provider_detail_entry(await _group(_svc(request), name)))
