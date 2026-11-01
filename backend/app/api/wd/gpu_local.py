"""Trasy „GPU → Ten serwer”: karty i modele serwera WD oraz wdrożenie przez ``gpu-agent``.

Odczyt stanu, parsowanie i wyłączanie wdrożeń są wspólne z RunPod
(``/api/wd/v1/runpod/deployments``).
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request, status
from pydantic import BaseModel, Field

from app.api.auth.principal import PrincipalDep, container_of
from app.api.wd.common import Envelope, Items, wd_responses
from app.api.wd.runpod import Deployment, HostedModelView, ParseRequest
from app.services.gpu_local.service import LocalGpuService

router = APIRouter(prefix="/api/wd/v1/gpu/local", tags=["gpu-local"])


class LocalGpuView(BaseModel):
    """Karta GPU serwera WD."""

    id: str = Field(description="UUID karty z nvidia-smi")
    index: int = Field(description="Numer karty")
    name: str = Field(description="Nazwa karty")
    vram_gb: int = Field(description="VRAM w GB")
    memory_total_mb: int = Field(description="Cała pamięć (MiB)")
    memory_free_mb: int = Field(description="Wolna pamięć (MiB)")
    memory_used_mb: int = Field(description="Zajęta pamięć (MiB)")
    utilization_pct: int | None = Field(description="Obciążenie w procentach")
    free: bool = Field(description="Czy wolnej pamięci wystarczy dla wybranego modelu")


class LocalGpuList(BaseModel):
    """Karty serwera dla wybranego modelu i stan agenta."""

    agent: Literal["ok", "not_configured", "unreachable"] = Field(description="Stan gpu-agent")
    model: str = Field(description="Model, dla którego liczono wolne karty")
    min_vram_gb: int = Field(description="Minimalny wolny VRAM modelu")
    gpus: list[LocalGpuView] = Field(description="Karty serwera")


class LocalDeployBody(BaseModel):
    """Wdrożenie modelu na karcie serwera."""

    model: str = Field(min_length=1, description="Nazwa modelu z listy modeli")
    gpu_id: str = Field(min_length=1, description="UUID karty")
    parse: list[ParseRequest] = Field(
        default_factory=list, description="Dokumenty do sparsowania, gdy model będzie gotowy"
    )


def _svc(request: Request) -> LocalGpuService:
    return LocalGpuService(container_of(request))


@router.get(
    "/models",
    operation_id="gpu_local_models",
    summary="Modele, które można uruchomić na GPU tego serwera",
    response_model=Envelope[Items[HostedModelView]],
    responses=wd_responses(401),
)
async def models(request: Request, principal: PrincipalDep) -> Envelope[Items[HostedModelView]]:
    """Lista modeli."""
    items = [HostedModelView.model_validate(m) for m in _svc(request).models()]
    return Envelope[Items[HostedModelView]](data=Items[HostedModelView](items=items))


@router.get(
    "/gpus",
    operation_id="gpu_local_gpus",
    summary="Karty GPU tego serwera z VRAM i stanem wolna/zajęta",
    response_model=Envelope[LocalGpuList],
    responses=wd_responses(400, 401, 403),
)
async def gpus(
    request: Request, principal: PrincipalDep, model: Annotated[str, Query(min_length=1)]
) -> Envelope[LocalGpuList]:
    """Brak lub awaria agenta to pole ``agent``, nie błąd HTTP."""
    data = await _svc(request).gpus(principal, model)
    return Envelope[LocalGpuList](data=LocalGpuList.model_validate(data))


@router.post(
    "/deployments",
    operation_id="gpu_local_deploy",
    summary="Uruchamia model na GPU tego serwera",
    status_code=status.HTTP_201_CREATED,
    response_model=Envelope[Deployment],
    responses=wd_responses(400, 401, 403, 409, 502),
)
async def deploy(
    request: Request, principal: PrincipalDep, body: LocalDeployBody
) -> Envelope[Deployment]:
    """Zleca start kontenera; po gotowości WD parsuje ``parse``."""
    data = await _svc(request).deploy(
        principal,
        model=body.model,
        gpu_id=body.gpu_id,
        parse=[p.model_dump() for p in body.parse],
    )
    return Envelope[Deployment](data=Deployment.model_validate(data))
