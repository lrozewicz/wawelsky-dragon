"""Trasa SVC listy datasetów `/api/datasets` (03 §5, kontrakt E4-3a §4).

Odpowiednik `hub-compat/raglow-service/sharepoint-sync/src/routes/datasets.ts`: proxy do listy baz
wiedzy, potrzebne UI hub-compat do wypełnienia dropdownu w formularzu integracji.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.hub_compat.envelope import data
from app.api.hub_compat.route import SvcRoute
from app.api.hub_compat.security import require_secret
from app.api.hub_compat.sharepoint.setup import integration_service

router = APIRouter(
    route_class=SvcRoute,
    include_in_schema=False,
    dependencies=[Depends(require_secret)],
)


@router.get("/api/datasets")
async def list_datasets(request: Request) -> JSONResponse:
    """Datasety do formularza integracji; wszystkie, rosnąco po nazwie (K7 część 2 §7 p. 11)."""
    summaries = await integration_service(request).list_datasets()
    return data(
        [
            {
                "id": summary.id,
                "name": summary.name,
                "document_count": summary.document_count,
                "chunk_count": summary.chunk_count,
                "embedding_model": summary.embedding_model,
            }
            for summary in summaries
        ]
    )
