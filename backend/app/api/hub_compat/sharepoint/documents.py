"""Trasa SVC linku do dokumentu źródłowego `/api/documents/link` (03 §5, kontrakt E4-3a §4).

Odpowiednik `hub-compat/sharepoint-sync/src/routes/documents.ts:82-145`. Kształt `data`
jest camelCase jak w oryginale (UI hub-compat czyta `webUrl`), a brak mapowania/pliku w SharePoint
wraca 404 z kodem przyczyny — trasa buduje tę odpowiedź sama, bo `LinkNotFound` niesie `reason`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.api.hub_compat.envelope import data
from app.api.hub_compat.route import SvcRoute
from app.api.hub_compat.security import require_secret
from app.api.hub_compat.sharepoint.setup import integration_service
from app.core.errors import ValidationFailed
from app.services.integration_links import DocumentLink, LinkNotFound

router = APIRouter(
    route_class=SvcRoute,
    include_in_schema=False,
    dependencies=[Depends(require_secret)],
)

DOCUMENT_ID_REQUIRED = "documentId is required"
NOT_FOUND = 404


def _link_dto(link: DocumentLink) -> dict[str, object]:
    """Kształt `data` trasy: `webUrl`, `name`, `path`, `driveName` (kontrakt §4)."""
    return {
        "webUrl": link.web_url,
        "name": link.name,
        "path": link.path,
        "driveName": link.drive_name,
    }


@router.get("/api/documents/link")
async def document_link(
    request: Request, document_id: str | None = Query(default=None, alias="documentId")
) -> JSONResponse:
    """Link do elementu w SharePoint; brak `documentId` → 400, brak mapowania → 404 (§4)."""
    if not document_id:
        raise ValidationFailed(DOCUMENT_ID_REQUIRED)
    try:
        link = await integration_service(request).document_link(document_id)
    except LinkNotFound as exc:
        return JSONResponse({"error": exc.message, "code": exc.reason}, status_code=NOT_FOUND)
    return data(_link_dto(link))
