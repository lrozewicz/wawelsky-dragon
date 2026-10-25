"""Alias ``/api/v1`` zgodny z RAGFlow v0.24 — właściciel E2-2b.

Kontener na trasy wyłącznie v0.24 (``deprecated=True``). Na razie jedna trasa:
``POST /sessions/ask`` (02 §7.2, CONTRACT C4) — SSE nad podanymi datasetami bez czatu.
"""

from collections.abc import Mapping
from typing import Any, cast

from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse

from app.api.auth.principal import PrincipalDep, container_of, json_body
from app.api.ragflow.compat import CompatDep, CompatProfile
from app.api.ragflow.envelope import data_error
from app.api.ragflow.refusals import refuse
from app.api.ragflow.schemas.common import RagflowOk, extra_doc
from app.api.ragflow.schemas.completions import AskRequest
from app.api.ragflow.sse import sse_ask
from app.core.errors import PermissionDenied, ValidationFailed
from app.domain.policy import Principal
from app.services.chat import ChatService

router = APIRouter(prefix="/api/v1", tags=["sessions"])

# Nagłówki odpowiedzi SSE jak completions (C0 p. 6; upstream ask_about dodaje Content-Type).
_ASK_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
_ASK_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "model": RagflowOk[bool],
        "description": (
            'text/event-stream: ramki `data:{"code":0,"message":"","data":{…}}`, '
            'zakończone `data:{"code":0,"message":"","data":true}`'
        ),
        "content": {"text/event-stream": {"schema": {"type": "string"}}},
    }
}


def _ask_args(body: Mapping[str, Any]) -> str | tuple[str, tuple[str, ...]]:
    """Walidacja ciała ``/sessions/ask`` (upstream ``ask_about``): komunikat albo argumenty."""
    if not body.get("question"):
        return "`question` is required."
    if not body.get("dataset_ids"):
        return "`dataset_ids` is required."
    if not isinstance(body.get("dataset_ids"), list):
        return "`dataset_ids` should be a list."
    return str(body["question"]), tuple(str(one) for one in body["dataset_ids"])


async def _ask_stream(
    request: Request,
    principal: Principal,
    profile: CompatProfile,
    question: str,
    dataset_ids: tuple[str, ...],
) -> Response:
    """Usługa ask + tłumaczenie błędów na koperty v0.24; sukces → strumień SSE."""
    chat = cast(ChatService, container_of(request).chat)
    try:
        stream = await chat.ask(principal, question, dataset_ids)
    except PermissionDenied as err:  # cudzy/nieistniejący dataset → 102 (profil) z jego id
        bad = err.details.get("dataset_id") if err.details else None
        return refuse(
            request,
            principal,
            "sessions_ask",
            err,
            ids=(str(bad),) if bad is not None else dataset_ids,
            compat=profile,
        )
    except ValidationFailed as err:  # brak sparsowanego pliku: 102 (upstream get_error_data_result)
        return data_error(err.message)
    return StreamingResponse(
        sse_ask(stream.events), media_type="text/event-stream; charset=utf-8", headers=_ASK_HEADERS
    )


@router.post(
    "/sessions/ask",
    operation_id="sessions_ask",
    deprecated=True,
    responses=_ASK_RESPONSES,
    openapi_extra=extra_doc(AskRequest),
)
async def sessions_ask(request: Request, principal: PrincipalDep, profile: CompatDep) -> Response:
    """POST /api/v1/sessions/ask (C4): SSE nad ``dataset_ids`` bez czatu (tylko v0.24)."""
    parsed = _ask_args(await json_body(request))
    if isinstance(parsed, str):
        return data_error(parsed)
    return await _ask_stream(request, principal, profile, *parsed)
