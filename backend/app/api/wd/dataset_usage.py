"""Trasa użycia datasetu przed usunięciem (K20 §4) — ``GET /datasets/{id}/usage``.

Koperta WD K3 §3 (``{"data": …}``, błędy ``{"error": …}``). Dostęp jak usunięcie datasetu
(``DatasetUsageService.usage``): brak albo brak odczytu → 404 ``not_found``, widoczny bez prawa
usunięcia → 403 ``forbidden``. Trasa tylko do odczytu — nie zmienia zachowania
``DELETE /api/v1/datasets`` (Q52).
"""

from typing import Annotated

from fastapi import APIRouter, Path, Request, status
from pydantic import BaseModel, Field

from app.api.auth.principal import PrincipalDep, container_of
from app.api.wd.common import Envelope, wd_responses
from app.services.dataset_usage import DatasetUsageService

router = APIRouter(prefix="/api/wd/v1", tags=["datasets"])

DatasetIdPath = Annotated[str, Path(min_length=1, description="Identyfikator datasetu")]


class UsageItem(BaseModel):
    """Pozycja listy użycia: czat albo wyszukiwarka powiązana z datasetem (K20 §4)."""

    id: str = Field(description="Identyfikator zasobu (32 hex)")
    name: str = Field(description="Nazwa zasobu")


class DatasetUsage(BaseModel):
    """Użycie datasetu (K20 §4): widoczne powiązania, ukryte liczniki, ucięcie list."""

    chats: list[UsageItem] = Field(description="Czaty widoczne dla aktora z wiązaniem do datasetu")
    searches: list[UsageItem] = Field(
        description="Wyszukiwarki widoczne dla aktora z wiązaniem do datasetu"
    )
    hidden_chats: int = Field(description="Liczba wiązań w czatach niewidocznych dla aktora")
    hidden_searches: int = Field(
        description="Liczba wiązań w wyszukiwarkach niewidocznych dla aktora"
    )
    truncated: bool = Field(description="Czy którąś z list ucięto do 50 pozycji")


@router.get(
    "/datasets/{dataset_id}/usage",
    operation_id="dataset_usage",
    summary="Wymienia powiązania datasetu (czaty i wyszukiwarki) przed usunięciem",
    status_code=status.HTTP_200_OK,
    response_model=Envelope[DatasetUsage],
    responses=wd_responses(400, 401, 403, 404),
)
async def dataset_usage(
    request: Request, dataset_id: DatasetIdPath, principal: PrincipalDep
) -> Envelope[DatasetUsage]:
    """Użycie datasetu dla właściciela albo superusera (K20 §4)."""
    data = await DatasetUsageService(container_of(request)).usage(principal, dataset_id)
    return Envelope[DatasetUsage](data=DatasetUsage.model_validate(data))
