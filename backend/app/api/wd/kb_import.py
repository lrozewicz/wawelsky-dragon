"""Trasy importu paczki ``.wdkb.zip`` (K19 §3 trasy 6-8 i 10) — wypełnia E7-1b.

Router istnieje i jest zarejestrowany w ``app/main.py`` od E7-1f: E7-1b dopisuje operacje
``dataset_import_create``, ``dataset_import_upload``, ``dataset_import_get``,
``dataset_import_delete`` bez dotykania ``main.py`` (jeden punkt rejestracji, CONTRACT §7).
Trasę 9 ``start`` dokłada T6.

Aktorem jest inicjator sesji albo superuser (K19 §Uprawnienia 6-10); dostęp i całą pracę
rozstrzyga ``KbImportService`` — warstwa API nie dotyka ``app.db`` (kontrakt ``api-no-db``)
i waliduje zwrócony ``dict`` schematem ``DatasetImport`` (kontrakt warstw).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Path, Request, status
from pydantic import BaseModel, Field

from app.api.auth.principal import PrincipalDep, container_of
from app.api.wd.common import Envelope, wd_responses
from app.api.wd.kb_schemas import DatasetImport, TaskRef
from app.services.kb_import import KbImportService

router = APIRouter(prefix="/api/wd/v1", tags=["kb-import"])

ImportIdPath = Annotated[str, Path(min_length=1, description="Identyfikator sesji importu")]
# Nagłówek ``Content-Range`` czytany bezpośrednio: ciało żądania jest strumieniem bajtów,
# nie modelem pydantic (``application/octet-stream``, K19 §3 trasa 7).
ContentRangeHeader = Annotated[
    str | None, Header(alias="Content-Range", description="Zakres porcji ``bytes a-b/n``")
]


class DatasetImportCreateRequest(BaseModel):
    """Ciało ``POST /dataset-imports`` (K19 §3, trasa 6).

    Ograniczenia (``file_name`` 1..255, ``size_bytes`` > 0) sprawdza usługa jako **400**
    ``validation_failed`` — nie pydantic (kontrakt nie dopuszcza ``422``).
    """

    file_name: str = Field(description="Nazwa wysyłanego pliku (1..255 znaków)")
    size_bytes: int = Field(description="Zadeklarowany rozmiar paczki w bajtach (> 0)")


class DatasetImportDeleted(BaseModel):
    """Odpowiedź ``DELETE /dataset-imports/{id}`` (K19 §3, trasa 10)."""

    deleted: bool = Field(description="Czy sesja importu została usunięta")


class DatasetImportStartRequest(BaseModel):
    """Ciało ``POST /dataset-imports/{id}/start`` (K19 §3, trasa 9).

    Limit nazwy (1..128) sprawdza usługa jako **400** ``validation_failed`` — nie pydantic
    (kontrakt nie dopuszcza ``422``). ``embedding_model`` ``null`` ⇒ model domyślny aktora.
    """

    name: str = Field(description="Nazwa docelowego datasetu (1..128 znaków)")
    embedding_model: str | None = Field(
        default=None, description="Model embeddingu albo null → model domyślny"
    )


def _service(request: Request) -> KbImportService:
    """Usługa importu z kontenera żądania (kontrakt C7)."""
    return KbImportService(container_of(request))


@router.post(
    "/dataset-imports",
    operation_id="dataset_import_create",
    summary="Zakłada sesję importu paczki",
    status_code=status.HTTP_201_CREATED,
    response_model=Envelope[DatasetImport],
    responses=wd_responses(400, 401, 403, 413),
)
async def dataset_import_create(
    request: Request, principal: PrincipalDep, body: DatasetImportCreateRequest
) -> Envelope[DatasetImport]:
    """Zakłada sesję uploadu (K19 §3, trasa 6); zwraca stan ``uploading``."""
    data = await _service(request).create(
        principal, file_name=body.file_name, size_bytes=body.size_bytes
    )
    return Envelope[DatasetImport](data=DatasetImport.model_validate(data))


@router.put(
    "/dataset-imports/{import_id}/content",
    operation_id="dataset_import_upload",
    summary="Wysyła porcję paczki",
    status_code=status.HTTP_200_OK,
    response_model=Envelope[DatasetImport],
    responses=wd_responses(400, 401, 403, 404, 409, 413),
)
async def dataset_import_upload(
    request: Request,
    import_id: ImportIdPath,
    principal: PrincipalDep,
    content_range: ContentRangeHeader = None,
) -> Envelope[DatasetImport]:
    """Przyjmuje porcję ``Content-Range`` (K19 §3, trasa 7); ciało czytane strumieniowo."""
    data = await _service(request).upload(
        principal, import_id, content_range=content_range, body=request.stream()
    )
    return Envelope[DatasetImport](data=DatasetImport.model_validate(data))


@router.get(
    "/dataset-imports/{import_id}",
    operation_id="dataset_import_get",
    summary="Stan sesji importu",
    status_code=status.HTTP_200_OK,
    response_model=Envelope[DatasetImport],
    responses=wd_responses(400, 401, 403, 404),
)
async def dataset_import_get(
    request: Request, import_id: ImportIdPath, principal: PrincipalDep
) -> Envelope[DatasetImport]:
    """Stan sesji dla inicjatora albo superusera (K19 §3, trasa 8)."""
    data = await _service(request).get(principal, import_id)
    return Envelope[DatasetImport](data=DatasetImport.model_validate(data))


@router.post(
    "/dataset-imports/{import_id}/start",
    operation_id="dataset_import_start",
    summary="Startuje import paczki",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=Envelope[TaskRef],
    responses=wd_responses(400, 401, 403, 404, 409),
)
async def dataset_import_start(
    request: Request,
    import_id: ImportIdPath,
    principal: PrincipalDep,
    body: DatasetImportStartRequest,
) -> Envelope[TaskRef]:
    """Przechodzi sesję ``ready`` → ``started`` i zleca zadanie (K19 §3, trasa 9)."""
    data = await _service(request).start(
        principal, import_id, name=body.name, embedding_model=body.embedding_model
    )
    return Envelope[TaskRef](data=TaskRef.model_validate(data))


@router.delete(
    "/dataset-imports/{import_id}",
    operation_id="dataset_import_delete",
    summary="Usuwa sesję importu",
    status_code=status.HTTP_200_OK,
    response_model=Envelope[DatasetImportDeleted],
    responses=wd_responses(400, 401, 403, 404, 409),
)
async def dataset_import_delete(
    request: Request, import_id: ImportIdPath, principal: PrincipalDep
) -> Envelope[DatasetImportDeleted]:
    """Usuwa wiersz sesji i plik paczki (K19 §3, trasa 10)."""
    await _service(request).delete(principal, import_id)
    return Envelope[DatasetImportDeleted](data=DatasetImportDeleted(deleted=True))
