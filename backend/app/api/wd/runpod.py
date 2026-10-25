"""Trasy RunPod: klucz API, katalog GPU, preflight parsowania i wdrożenia modeli na GPU w chmurze.

Koperta WD (``{"data": …}``, błędy ``{"error": …}``). Operacje kosztowe (klucz, katalog, wdrożenie,
kasowanie) wymagają superusera (sprawdza je ``RunpodService``); preflight i odczyt wdrożeń działają
dla każdego uwierzytelnionego użytkownika. Brak wolnych maszyn → 409 ``gpu_unavailable`` ze
``details.alternatives`` (GPU o VRAM ≥ wybranego).
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query, Request, status
from pydantic import BaseModel, Field

from app.api.auth.principal import PrincipalDep, container_of
from app.api.wd.common import Envelope, Items, wd_responses
from app.services.runpod.service import RunpodService

router = APIRouter(prefix="/api/wd/v1/runpod", tags=["runpod"])

DeploymentIdPath = Annotated[str, Path(min_length=1, description="Identyfikator wdrożenia")]
Cloud = Literal["SECURE", "COMMUNITY"]


class KeyStatus(BaseModel):
    """Stan klucza API RunPod (sam klucz nigdy nie wraca)."""

    configured: bool = Field(description="Czy klucz jest zapisany")
    hint: str | None = Field(description="Końcówka klucza (…abcd) albo null")


class KeyBody(BaseModel):
    """Nowy klucz API RunPod."""

    api_key: str = Field(min_length=1, max_length=500, description="Klucz API RunPod")


class HostedModelView(BaseModel):
    """Model, który można uruchomić na RunPod."""

    name: str = Field(description="Nazwa modelu w rejestrze WD (to wpisujesz jako parser)")
    title: str = Field(description="Nazwa wyświetlana")
    hf_model: str = Field(description="Model na Hugging Face")
    min_vram_gb: int = Field(description="Minimalny VRAM GPU")
    recommended_vram_gb: int = Field(description="Zalecany VRAM GPU")


class DataCenterView(BaseModel):
    """Centrum danych z dostępnością GPU."""

    id: str = Field(description="Id centrum danych, np. EU-RO-1")
    name: str = Field(description="Nazwa centrum danych")
    region: str = Field(description="Region (EUROPE, NORTH_AMERICA, …)")
    country: str = Field(description="Kod kraju, np. RO")
    availability: str = Field(description="NONE, LOW, MEDIUM albo HIGH")


class GpuView(BaseModel):
    """GPU z katalogu RunPod."""

    id: str = Field(description="Id GPU do utworzenia poda")
    name: str = Field(description="Nazwa GPU")
    vram_gb: int = Field(description="VRAM w GB")
    price_per_hr: float = Field(description="Cena za godzinę (USD, 1 GPU)")
    availability: str = Field(description="NONE, LOW, MEDIUM albo HIGH")
    data_centers: list[DataCenterView] = Field(description="Centra z wolnymi GPU")
    fits: bool = Field(default=True, description="Czy VRAM wystarcza dla modelu")


class GpuCatalog(BaseModel):
    """Lista GPU po filtrach i dostępne wartości filtrów."""

    model: str = Field(description="Model, dla którego liczono wymagania")
    min_vram_gb: int = Field(description="Minimalny VRAM modelu")
    gpus: list[GpuView] = Field(description="GPU, najtańsze pierwsze")
    regions: list[str] = Field(description="Dostępne regiony")
    countries: list[str] = Field(description="Dostępne kraje")


class PreflightBody(BaseModel):
    """Dokumenty, które użytkownik chce sparsować."""

    dataset_id: str = Field(min_length=1, description="Id datasetu")
    document_ids: list[str] = Field(min_length=1, description="Id dokumentów")


class LastGpu(BaseModel):
    """GPU z poprzedniego wdrożenia (domyślny wybór w oknie pytania)."""

    id: str = Field(description="Id GPU")
    name: str = Field(description="Nazwa GPU")
    vram_gb: int = Field(description="VRAM w GB")


class Preflight(BaseModel):
    """Czy parsowanie wymaga włączenia poda RunPod."""

    needs_pod: bool = Field(description="True, gdy model działa na RunPod i pod jest wyłączony")
    model: str | None = Field(default=None, description="Nazwa modelu w rejestrze")
    title: str | None = Field(default=None, description="Nazwa wyświetlana modelu")
    state: str | None = Field(
        default=None, description="off, provisioning, starting, loading, ready"
    )
    deployment_id: str | None = Field(default=None, description="Trwające wdrożenie, jeśli jest")
    last_gpu: LastGpu | None = Field(default=None, description="GPU z poprzedniego wdrożenia")
    min_vram_gb: int | None = Field(default=None, description="Minimalny VRAM modelu")


class ParseRequest(BaseModel):
    """Dokumenty do sparsowania po gotowości poda."""

    dataset_id: str = Field(min_length=1, description="Id datasetu")
    document_ids: list[str] = Field(min_length=1, description="Id dokumentów")


class DeployBody(BaseModel):
    """Wdrożenie modelu na wskazanym GPU."""

    model: str = Field(min_length=1, description="Nazwa modelu z listy modeli")
    gpu_id: str = Field(min_length=1, description="Id GPU z katalogu")
    cloud: Cloud = Field(default="SECURE", description="SECURE albo COMMUNITY")
    region: str | None = Field(default=None, description="Zawężenie do regionu")
    country: str | None = Field(default=None, description="Zawężenie do kraju (kod ISO)")
    parse: list[ParseRequest] = Field(
        default_factory=list, description="Dokumenty do sparsowania, gdy model będzie gotowy"
    )


class GpuRef(BaseModel):
    """GPU wdrożenia."""

    id: str = Field(description="Id GPU")
    name: str = Field(description="Nazwa GPU")
    vram_gb: int = Field(description="VRAM w GB")


class Deployment(BaseModel):
    """Wdrożenie modelu na RunPod (pod)."""

    id: str = Field(description="Id wdrożenia")
    model: str = Field(description="Nazwa modelu")
    title: str = Field(description="Nazwa wyświetlana")
    status: str = Field(
        description=(
            "requested, provisioning, starting, loading, ready, terminating, terminated, failed"
        )
    )
    active: bool = Field(description="Czy pod trwa i generuje koszty")
    gpu: GpuRef = Field(description="GPU")
    cloud: str = Field(description="SECURE albo COMMUNITY")
    data_center_id: str | None = Field(description="Centrum danych przydzielone przez RunPod")
    price_per_hr: float = Field(description="Cena za godzinę (USD)")
    cost_so_far: float = Field(description="Szacowany koszt dotychczas (USD)")
    error: str | None = Field(description="Przyczyna błędu albo uwagi")
    pending_documents: int = Field(description="Dokumenty czekające na start parsowania")
    created_at: int = Field(description="Czas utworzenia (ms)")
    ready_at: int | None = Field(description="Czas gotowości modelu (ms)")
    ended_at: int | None = Field(description="Czas zakończenia (ms)")
    idle_shutdown_s: int = Field(description="Po ilu sekundach bez zadań pod jest kasowany")


def _svc(request: Request) -> RunpodService:
    return RunpodService(container_of(request))


@router.get(
    "/key",
    operation_id="runpod_key_status",
    summary="Stan klucza API RunPod",
    response_model=Envelope[KeyStatus],
    responses=wd_responses(401),
)
async def key_status(request: Request, principal: PrincipalDep) -> Envelope[KeyStatus]:
    """Czy klucz jest zapisany (bez jego wartości)."""
    return Envelope[KeyStatus](data=KeyStatus.model_validate(await _svc(request).key_status()))


@router.put(
    "/key",
    operation_id="runpod_key_set",
    summary="Zapisuje klucz API RunPod (po sprawdzeniu w RunPod)",
    response_model=Envelope[KeyStatus],
    responses=wd_responses(400, 401, 403, 502),
)
async def key_set(request: Request, principal: PrincipalDep, body: KeyBody) -> Envelope[KeyStatus]:
    """Superuser zapisuje klucz; zły klucz → 400."""
    data = await _svc(request).set_key(principal, body.api_key)
    return Envelope[KeyStatus](data=KeyStatus.model_validate(data))


@router.delete(
    "/key",
    operation_id="runpod_key_delete",
    summary="Usuwa klucz API RunPod",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=wd_responses(401, 403, 409),
)
async def key_delete(request: Request, principal: PrincipalDep) -> None:
    """Usuwa klucz; z działającymi podami → 409."""
    await _svc(request).remove_key(principal)


@router.get(
    "/models",
    operation_id="runpod_models",
    summary="Modele, które można uruchomić na RunPod",
    response_model=Envelope[Items[HostedModelView]],
    responses=wd_responses(401),
)
async def models(request: Request, principal: PrincipalDep) -> Envelope[Items[HostedModelView]]:
    """Lista modeli hostowanych."""
    items = [HostedModelView.model_validate(m) for m in _svc(request).hosted_models()]
    return Envelope[Items[HostedModelView]](data=Items[HostedModelView](items=items))


@router.get(
    "/gpus",
    operation_id="runpod_gpus",
    summary="Lista GPU RunPod z cenami i dostępnością (filtry: VRAM, region, kraj)",
    response_model=Envelope[GpuCatalog],
    responses=wd_responses(400, 401, 403, 409, 502),
)
async def gpus(  # noqa: PLR0913, PLR0917 — filtry panelu
    request: Request,
    principal: PrincipalDep,
    model: Annotated[str, Query(min_length=1)],
    cloud: Cloud = "SECURE",
    min_vram: Annotated[int | None, Query(ge=1)] = None,
    max_vram: Annotated[int | None, Query(ge=1)] = None,
    region: str | None = None,
    country: Annotated[str | None, Query(min_length=2, max_length=2)] = None,
    only_available: bool = False,
) -> Envelope[GpuCatalog]:
    """GPU posortowane od najtańszych; wymaga zapisanego klucza."""
    data = await _svc(request).catalog(
        principal,
        model=model,
        cloud=cloud,
        min_vram=min_vram,
        max_vram=max_vram,
        region=region,
        country=country,
        only_available=only_available,
    )
    return Envelope[GpuCatalog](data=GpuCatalog.model_validate(data))


@router.post(
    "/preflight",
    operation_id="runpod_preflight",
    summary="Czy parsowanie wymaga włączenia poda RunPod",
    response_model=Envelope[Preflight],
    responses=wd_responses(400, 401, 403, 404),
)
async def preflight(
    request: Request, principal: PrincipalDep, body: PreflightBody
) -> Envelope[Preflight]:
    """Wołane przez UI przed startem parsowania; bez efektów ubocznych."""
    data = await _svc(request).preflight(principal, body.dataset_id, body.document_ids)
    return Envelope[Preflight](data=Preflight.model_validate(data))


@router.post(
    "/deployments",
    operation_id="runpod_deploy",
    summary="Uruchamia model na GPU w RunPod",
    status_code=status.HTTP_201_CREATED,
    response_model=Envelope[Deployment],
    responses=wd_responses(400, 401, 403, 409, 502),
)
async def deploy(
    request: Request, principal: PrincipalDep, body: DeployBody
) -> Envelope[Deployment]:
    """Tworzy poda; po gotowości WD parsuje ``parse``. Brak GPU → 409 z zamiennikami."""
    data = await _svc(request).deploy(
        principal,
        model=body.model,
        gpu_id=body.gpu_id,
        cloud=body.cloud,
        region=body.region,
        country=body.country,
        parse=[p.model_dump() for p in body.parse],
    )
    return Envelope[Deployment](data=Deployment.model_validate(data))


@router.get(
    "/deployments",
    operation_id="runpod_deployments",
    summary="Ostatnie wdrożenia modeli na RunPod",
    response_model=Envelope[Items[Deployment]],
    responses=wd_responses(401),
)
async def deployments(request: Request, principal: PrincipalDep) -> Envelope[Items[Deployment]]:
    """Najnowsze pierwsze (aktywne i zakończone)."""
    rows = [Deployment.model_validate(d) for d in await _svc(request).list_deployments()]
    return Envelope[Items[Deployment]](data=Items[Deployment](items=rows))


@router.get(
    "/deployments/{deployment_id}",
    operation_id="runpod_deployment",
    summary="Stan wdrożenia",
    response_model=Envelope[Deployment],
    responses=wd_responses(401, 404),
)
async def deployment(
    request: Request, principal: PrincipalDep, deployment_id: DeploymentIdPath
) -> Envelope[Deployment]:
    """Stan do odpytywania z UI."""
    data = await _svc(request).get(deployment_id)
    return Envelope[Deployment](data=Deployment.model_validate(data))


@router.post(
    "/deployments/{deployment_id}/parse",
    operation_id="runpod_queue_parse",
    summary="Zleca parsowanie dokumentów po uruchomieniu poda (albo od razu, gdy działa)",
    response_model=Envelope[Deployment],
    responses=wd_responses(400, 401, 403, 404, 409),
)
async def queue_parse(
    request: Request, principal: PrincipalDep, deployment_id: DeploymentIdPath, body: ParseRequest
) -> Envelope[Deployment]:
    """Dla poda w trakcie wdrażania dopisuje dokumenty; dla gotowego startuje parsowanie."""
    data = await _svc(request).queue_parse(
        principal, deployment_id, body.dataset_id, body.document_ids
    )
    return Envelope[Deployment](data=Deployment.model_validate(data))


@router.delete(
    "/deployments/{deployment_id}",
    operation_id="runpod_terminate",
    summary="Kasuje poda (koniec kosztów)",
    response_model=Envelope[Deployment],
    responses=wd_responses(401, 403, 404, 502),
)
async def terminate(
    request: Request, principal: PrincipalDep, deployment_id: DeploymentIdPath
) -> Envelope[Deployment]:
    """Ręczne wyłączenie wdrożenia."""
    data = await _svc(request).terminate(principal, deployment_id)
    return Envelope[Deployment].model_validate({"data": data})
