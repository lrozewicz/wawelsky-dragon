"""Trasa dziennika audytu WD ``/api/wd/v1/audit`` (brief T4, kontrakt §2, §4).

Jedna trasa listująca wpisy malejąco po ``id``: filtry ``actor`` (dokładna etykieta, bez
rozróżniania wielkości liter), ``action``, ``from``/``to`` (ISO-8601; bez strefy = UTC)
plus paginacja bez clampu (``page`` ≥ 1, ``page_size`` 1..100 — poza zakresem → 400).
``from`` > ``to`` → ``ValidationFailed`` (400). Odpowiedź przechodzi przez ``_redact``,
który usuwa z ``details`` klucze zawierające ``password|token|secret`` (obrona w głąb).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.auth.principal import container_of
from app.api.hub_compat.sharepoint.dto import iso_ms
from app.api.wd.common import Envelope, Page, require_admin, wd_responses
from app.api.wd.system.schemas import AuditEntry
from app.core.errors import ValidationFailed
from app.services.audit import AuditRow, AuditService

router = APIRouter(
    prefix="/api/wd/v1",
    tags=["audit"],
    dependencies=[Depends(require_admin)],
)

_SENSITIVE = re.compile(r"password|token|secret", re.IGNORECASE)
_MILLIS_PER_SECOND = 1000

ActorQuery = Annotated[
    str | None, Query(description="Etykieta aktora (dokładna, bez wielkości liter)")
]
ActionQuery = Annotated[str | None, Query(description="Akcja audytu")]
FromQuery = Annotated[
    datetime | None, Query(alias="from", description="Początek przedziału (ISO 8601)")
]
ToQuery = Annotated[datetime | None, Query(description="Koniec przedziału (ISO 8601)")]
PageQuery = Annotated[int, Query(ge=1, description="Numer strony (od 1)")]
PageSizeQuery = Annotated[int, Query(ge=1, le=100, description="Rozmiar strony (1-100)")]


def _to_ms(moment: datetime | None) -> int | None:
    """``datetime`` → ms epoki; bez strefy przyjmujemy UTC (kontrakt §4)."""
    if moment is None:
        return None
    aware = moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
    return int(aware.timestamp() * _MILLIS_PER_SECOND)


def _redact(value: object) -> object:
    """Usuwa klucze wrażliwe z ``details``, rekurencyjnie po słownikach (kontrakt §4)."""
    if isinstance(value, dict):
        return {
            key: _redact(item) for key, item in value.items() if not _SENSITIVE.search(str(key))
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _entry(row: AuditRow) -> AuditEntry:
    """Wiersz repo → model ``AuditEntry``; ``details`` po redakcji (kontrakt §2, §4)."""
    details = _redact(row.details) if row.details is not None else None
    return AuditEntry(
        id=row.id,
        ts=iso_ms(row.ts),
        actor_id=row.actor_id,
        actor=row.actor_label,
        action=row.action,
        target_type=row.target_type,
        target_id=row.target_id,
        details=cast("dict[str, object] | None", details),
        ip=row.ip,
    )


@router.get(
    "/audit",
    operation_id="audit_list",
    summary="Lista wpisów dziennika audytu",
    status_code=status.HTTP_200_OK,
    response_model=Envelope[Page[AuditEntry]],
    responses=wd_responses(400, 401, 403),
)
async def list_audit(  # noqa: PLR0913, PLR0917 — filtry i paginacja z kontraktu §2
    request: Request,
    actor: ActorQuery = None,
    action: ActionQuery = None,
    from_: FromQuery = None,
    to: ToQuery = None,
    page: PageQuery = 1,
    page_size: PageSizeQuery = 20,
) -> Envelope[Page[AuditEntry]]:
    """Strona wpisów audytu malejąco po ``id``; ``from`` > ``to`` → 400 (kontrakt §4)."""
    from_ms = _to_ms(from_)
    to_ms = _to_ms(to)
    if from_ms is not None and to_ms is not None and from_ms > to_ms:
        raise ValidationFailed("`from` must not be later than `to`")
    audit = cast(AuditService, container_of(request).audit)
    rows, total = await audit.list_page(
        actor=actor,
        action=action,
        from_ms=from_ms,
        to_ms=to_ms,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return Envelope[Page[AuditEntry]](
        data=Page[AuditEntry](
            items=[_entry(row) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
        )
    )
