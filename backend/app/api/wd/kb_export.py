"""Trasy eksportu paczki ``.wdkb.zip`` (K19 §3 trasy 1-2 i 5) — wypełnia E7-1a.

Router istnieje i jest zarejestrowany w ``app/main.py`` od E7-1f: E7-1a dopisuje operacje
``dataset_export_preview``, ``dataset_export`` i ``dataset_export_download`` bez dotykania
``main.py`` (jeden punkt rejestracji, CONTRACT §7).

Aktorem tras 1-2 jest zwykły zalogowany użytkownik — dostęp rozstrzyga ``KbExportService``
(``app.domain.policy``), a warstwa API waliduje zwrócone ``dict`` modelami z ``kb_schemas``.
Trasa 5 (pobranie) nie zna aktora: autoryzuje ją podpis HMAC w parametrach ``exp``/``sig``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.api.auth.principal import PrincipalDep, container_of
from app.api.wd.common import Envelope, wd_responses
from app.api.wd.kb_schemas import ExportPreview, TaskRef
from app.core.errors import InvalidSignature
from app.services.kb_export import KbExportService

router = APIRouter(prefix="/api/wd/v1", tags=["kb-export"])

DatasetIdPath = Annotated[str, Path(min_length=1, description="Identyfikator datasetu")]
TaskIdPath = Annotated[str, Path(min_length=1, description="Identyfikator zadania")]
ExpQuery = Annotated[int | None, Query(description="Sekundowa data wygaśnięcia linku")]
SigQuery = Annotated[str | None, Query(description="Podpis HMAC linku pobrania")]

# K19 §3 trasa 5: brak ``exp`` albo ``sig`` traktujemy jak zły podpis (403 ``invalid_signature``).
_MSG_PARAMS_MISSING = "Download link requires exp and sig"


class ExportRequest(BaseModel):
    """Ciało ``POST /datasets/{id}/export`` (K19 §3, trasa 2)."""

    include_vectors: bool = Field(default=True, description="Czy paczka ma nieść wektory")


def _service(request: Request) -> KbExportService:
    """Usługa eksportu z kontenera żądania (kontrakt C7)."""
    return KbExportService(container_of(request))


@router.get(
    "/datasets/{dataset_id}/export/preview",
    operation_id="dataset_export_preview",
    summary="Szacuje eksport datasetu",
    status_code=status.HTTP_200_OK,
    response_model=Envelope[ExportPreview],
    responses=wd_responses(400, 401, 403, 404),
)
async def dataset_export_preview(
    request: Request, dataset_id: DatasetIdPath, principal: PrincipalDep
) -> Envelope[ExportPreview]:
    """Szacunek eksportu dla właściciela albo superusera (K19 §3, trasa 1)."""
    data = await _service(request).preview(principal, dataset_id)
    return Envelope[ExportPreview](data=ExportPreview.model_validate(data))


@router.post(
    "/datasets/{dataset_id}/export",
    operation_id="dataset_export",
    summary="Zleca eksport datasetu",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=Envelope[TaskRef],
    responses=wd_responses(400, 401, 403, 404, 409, 413),
)
async def dataset_export(
    request: Request, dataset_id: DatasetIdPath, principal: PrincipalDep, body: ExportRequest
) -> Envelope[TaskRef]:
    """Zleca zadanie ``export_dataset`` (K19 §3, trasa 2); zwraca ``queued``."""
    data = await _service(request).start(
        principal, dataset_id, include_vectors=body.include_vectors
    )
    return Envelope[TaskRef](data=TaskRef.model_validate(data))


@router.get(
    "/exports/{task_id}/download",
    operation_id="dataset_export_download",
    summary="Pobiera paczkę eksportu pod podpisanym linkiem",
    status_code=status.HTTP_200_OK,
    response_class=FileResponse,
    responses=wd_responses(403, 410),
)
async def dataset_export_download(
    request: Request, task_id: TaskIdPath, exp: ExpQuery = None, sig: SigQuery = None
) -> FileResponse:
    """Strumień paczki ``.wdkb.zip`` — bez aktora, wyłącznie z podpisem (K19 §3, trasa 5)."""
    if exp is None or sig is None:
        raise InvalidSignature(_MSG_PARAMS_MISSING)
    path, file_name = await _service(request).download(task_id, exp=exp, sig=sig)
    return FileResponse(path, media_type="application/zip", filename=file_name)
