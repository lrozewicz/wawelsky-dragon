"""Trasy completions /api/v1 (CONTRACT C6; K4 §1.7): SSE bajtowo albo JSON."""

from typing import Any, cast

from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse

from app.api.auth.principal import PrincipalDep, container_of, json_body
from app.api.ragflow.compat import CompatDep, CompatProfile
from app.api.ragflow.envelope import ok
from app.api.ragflow.normalize.completions import parse_completion
from app.api.ragflow.present.completions import completion_data
from app.api.ragflow.refusals import refuse
from app.api.ragflow.schemas.common import RagflowOk, extra_doc
from app.api.ragflow.schemas.completions import CompletionData, CompletionRequest
from app.api.ragflow.sse import sse_native
from app.core.errors import PermissionDenied
from app.domain.policy import Principal
from app.services.chat import ChatService
from app.services.sessions import SessionsService

router = APIRouter(prefix="/api/v1", tags=["completions"])

# Odpowiedź 200 obu tras (C2.4): JSON przy stream=false, SSE wg K4 §1 przy stream=true.
_COMPLETION_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "model": RagflowOk[CompletionData],
        "description": (
            "stream=false: JSON; stream=true (domyślnie): text/event-stream wg K4 §1 — "
            'ramki `data:{"code":0,"message":"","data":<CompletionData>}` zakończone '
            '`data:{"code":0,"message":"","data":true}`'
        ),
        "content": {"text/event-stream": {"schema": {"type": "string"}}},
    }
}


async def _complete(
    request: Request, principal: Principal, profile: CompatProfile, path_chat_id: str | None
) -> Response:
    """Wspólna obsługa completions: JSON przy stream=False, inaczej strumień SSE (C6).

    Cudzy czat → 109 ``no authorization`` z ``data: false`` (upstream ``_ensure_owned_chat``,
    chat_api.py:190; złoto errors_access--33 i --34) — sprawdzenie przed ciałem odpowiedzi.
    Pozostałe wyjątki WDError (walidacja) lecą dalej — kopertę K3 skleja handler błędów.
    """
    call = parse_completion(await json_body(request), profile, path_chat_id=path_chat_id)
    route = "chats_completions" if path_chat_id is not None else "chat_completions"
    # Pre-check właściciela po normalizacji ``messages`` (upstream ``_ensure_owned_chat``,
    # chat_api.py:1266): czat nieistniejący i cudzy to u upstream ta sama odmowa (DEC-092 p. 1).
    # Profil 0.24 nie ma trasy ``chat_completions`` (``refusals_v024.py``), więc tam sprawdzamy
    # tylko wariant ścieżkowy — ``chat_completions`` zachowuje dzisiejsze 102 „Chat not found!".
    owned_check = profile == "ragflow_0_27" or route == "chats_completions"
    if call.req.chat_id is not None and owned_check:
        sessions = SessionsService(container_of(request))
        if not await sessions.ensure_owned(principal, call.req.chat_id):
            return refuse(request, principal, route, compat=profile)
    chat = cast(ChatService, container_of(request).chat)
    try:
        if not call.stream:
            return ok(completion_data(await chat.complete_once(principal, call.req), profile))
        stream = await chat.start(principal, call.req)
    except PermissionDenied as err:
        return refuse(request, principal, route, err, compat=profile)
    return StreamingResponse(
        sse_native(stream.events, stream.ids, legacy=call.legacy, profile=profile),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/chats/{chat_id}/completions",
    operation_id="chats_completions",
    responses=_COMPLETION_RESPONSES,
    openapi_extra=extra_doc(CompletionRequest),
)
async def chat_completions(
    chat_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> Response:
    """POST /api/v1/chats/{chat_id}/completions (C6): chat_id z ciała wygrywa ze ścieżki."""
    return await _complete(request, principal, profile, chat_id)


@router.post(
    "/chat/completions",
    operation_id="chat_completions",
    responses=_COMPLETION_RESPONSES,
    openapi_extra=extra_doc(CompletionRequest),
)
async def restful_completions(
    request: Request, principal: PrincipalDep, profile: CompatDep
) -> Response:
    """POST /api/v1/chat/completions (C6): chat_id tylko z ciała; brak → solo chat."""
    return await _complete(request, principal, profile, None)
