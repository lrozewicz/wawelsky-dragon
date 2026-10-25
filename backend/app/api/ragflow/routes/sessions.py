"""Trasy sesji /api/v1/chats/{chat_id}/sessions (CONTRACT C6) — handler ≤ 15 linii."""

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from app.api.auth.principal import PrincipalDep, container_of, json_body
from app.api.ragflow.compat import CompatDep
from app.api.ragflow.envelope import ok, ok_true
from app.api.ragflow.normalize.chats import parse_delete_ids
from app.api.ragflow.normalize.sessions import (
    parse_message_feedback,
    parse_session_create,
    parse_session_list,
    parse_session_rename,
    parse_session_user_v024,
)
from app.api.ragflow.present.sessions import session_detail
from app.api.ragflow.refusals import refuse
from app.api.ragflow.schemas.chats import BulkDeleteResult, DeleteIdsRequest
from app.api.ragflow.schemas.common import RagflowOk, extra_doc, query_param
from app.api.ragflow.schemas.sessions import (
    CreateSessionRequest,
    MessageFeedbackRequest,
    RenameSessionRequest,
    Session,
)
from app.core.errors import NotFound, PermissionDenied
from app.services.sessions import SessionsService

router = APIRouter(prefix="/api/v1", tags=["sessions"])


def ok_code_only() -> JSONResponse:
    """Koperta sukcesu 0.24 bez klucza ``data`` (C4; ``envelope.py`` bez zmian)."""
    return JSONResponse({"code": 0, "message": "success"})


def _svc(request: Request) -> SessionsService:
    """Usługa sesji per żądanie (K11 §1)."""
    return SessionsService(container_of(request))


@router.post(
    "/chats/{chat_id}/sessions",
    operation_id="sessions_create",
    responses={200: {"model": RagflowOk[Session]}},
    openapi_extra=extra_doc(CreateSessionRequest, required=False),
)
async def create_session(
    chat_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> Response:
    """POST /chats/{chat_id}/sessions (C6): nowa sesja z prologue."""
    # Czat nieistniejący i cudzy to u upstream ta sama odmowa 109 (``_ensure_owned_chat`` jest
    # pierwszą instrukcją, chat_api.py:836; złoto errors_access--28 i --46) — pre-check jak
    # w ``routes/chats.py::_update``, zanim czytamy ciało (DEC-091 p. 1).
    if not await _svc(request).ensure_owned(principal, chat_id):
        return refuse(request, principal, "sessions_create", compat=profile)
    body = await json_body(request)
    name = parse_session_create(body)
    # Profil 0.24: ``user_id`` z ciała trafia do sesji (upstream ``create``); 0.27 → podmiot.
    session_user = parse_session_user_v024(body) if profile == "ragflow_0_24" else None
    # Cudzy czat → 109 ``no authorization`` z ``data: false`` (upstream ``_ensure_owned_chat``,
    # chat_api.py:190; złoto errors_access--28).
    try:
        view = await _svc(request).create(principal, chat_id, name, user_id=session_user)
    except PermissionDenied as err:
        return refuse(request, principal, "sessions_create", err, compat=profile)
    return ok(session_detail(view, profile))


@router.get(
    "/chats/{chat_id}/sessions",
    operation_id="sessions_list",
    responses={200: {"model": RagflowOk[list[Session]]}},
    openapi_extra=extra_doc(
        query=[
            query_param("page", {"type": "integer"}, "Numer strony (od 1)"),
            query_param("page_size", {"type": "integer"}, "Liczba elementów na stronie"),
            query_param("orderby", {"type": "string"}, "Sortowanie: create_time|update_time|name"),
            query_param("desc", {"type": "boolean"}, "Kolejność malejąca (C5)"),
            query_param("id", {"type": "string"}, "Filtr po id sesji"),
            query_param("name", {"type": "string"}, "Filtr po dokładnej nazwie"),
            query_param("user_id", {"type": "string"}, "Filtr po id użytkownika"),
        ]
    ),
)
async def list_sessions(
    chat_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> Response:
    """GET /chats/{chat_id}/sessions (C6): stronicowana lista sesji czatu."""
    query = parse_session_list(
        dict(request.query_params),
        profile,
        max_size=container_of(request).settings.max_page_size,
    )
    # Czat cudzy i czat nieistniejący to u upstream ta sama odmowa 109 (``_ensure_owned_chat``,
    # chat_api.py:190) — złoto errors_access--29 (cudzy) i --46 (nieistniejący).
    try:
        views = await _svc(request).list(principal, chat_id, query)
    except (NotFound, PermissionDenied) as err:
        return refuse(request, principal, "sessions_list", err, compat=profile)
    return ok([session_detail(v, profile) for v in views])


@router.get(
    "/chats/{chat_id}/sessions/{session_id}",
    operation_id="sessions_get",
    responses={200: {"model": RagflowOk[Session]}},
)
async def get_session(
    session_id: str, chat_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> Response:
    """GET /chats/{chat_id}/sessions/{session_id} (C6): szczegół sesji z avatarem czatu."""
    # Cudzy czat → 109 (upstream ``_ensure_owned_chat``; złoto errors_access--30).
    try:
        view = await _svc(request).get(principal, chat_id, session_id)
    except PermissionDenied as err:
        return refuse(request, principal, "sessions_get", err, compat=profile)
    return ok(session_detail(view, profile, with_avatar=True))


@router.delete(
    "/chats/{chat_id}/sessions/{session_id}/messages/{message_id}",
    operation_id="sessions_message_delete",
    responses={200: {"model": RagflowOk[Session]}},
)
async def delete_message(  # noqa: PLR0913, PLR0917 — ścieżka + request + principal + profil
    message_id: str,
    session_id: str,
    chat_id: str,
    request: Request,
    principal: PrincipalDep,
    profile: CompatDep,
) -> Response:
    """DELETE …/messages/{message_id} (C6, chat_api.py:1000): usuwa parę pytanie+odpowiedź."""
    view = await _svc(request).delete_message(principal, chat_id, session_id, message_id)
    return ok(session_detail(view, profile))


@router.put(
    "/chats/{chat_id}/sessions/{session_id}/messages/{message_id}/feedback",
    operation_id="sessions_message_feedback",
    responses={200: {"model": RagflowOk[Session]}},
    openapi_extra=extra_doc(MessageFeedbackRequest),
)
async def message_feedback(  # noqa: PLR0913, PLR0917 — ścieżka + request + principal + profil
    message_id: str,
    session_id: str,
    chat_id: str,
    request: Request,
    principal: PrincipalDep,
    profile: CompatDep,
) -> Response:
    """PUT …/messages/{message_id}/feedback (C6, chat_api.py:1025): ocena odpowiedzi."""
    thumbup, feedback = parse_message_feedback(await json_body(request))
    view = await _svc(request).set_message_feedback(
        principal, chat_id, session_id, message_id, thumbup=thumbup, feedback=feedback
    )
    return ok(session_detail(view, profile))


@router.patch(
    "/chats/{chat_id}/sessions/{session_id}",
    operation_id="sessions_rename",
    responses={200: {"model": RagflowOk[Session]}},
    openapi_extra=extra_doc(RenameSessionRequest, required=False),
)
@router.put(
    "/chats/{chat_id}/sessions/{session_id}",
    operation_id="sessions_rename_legacy",
    deprecated=True,
    responses={200: {"model": RagflowOk[Session]}},
    openapi_extra=extra_doc(RenameSessionRequest, required=False),
)
async def rename_session(
    session_id: str, chat_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> Response:
    """PATCH i PUT /chats/{chat_id}/sessions/{session_id} (C6): zmiana nazwy sesji."""
    # 0.27: ``_ensure_owned_chat`` jest pierwszą instrukcją upstreamu (chat_api.py:920), więc
    # brak czatu to ta sama odmowa 109 co cudzy czat (DEC-091 p. 1). 0.24 sprawdza najpierw
    # sesję, potem czat (``sdk/session.py:114-117``) — kolejność bez zmian.
    if profile == "ragflow_0_27" and not await _svc(request).ensure_owned(principal, chat_id):
        return refuse(request, principal, "sessions_rename", compat=profile)
    name = parse_session_rename(await json_body(request))
    # Cudzy czat → 109 (upstream ``_ensure_owned_chat``; złoto errors_access--31).
    try:
        view = await _svc(request).rename(principal, chat_id, session_id, name)
    except PermissionDenied as err:
        return refuse(request, principal, "sessions_rename", err, compat=profile)
    if profile == "ragflow_0_24":
        # C4: PUT/PATCH w 0.24 zwraca sam kod (złoto ``chats___sessions___/chat_session--05.json``).
        return ok_code_only()
    return ok(session_detail(view, profile))


@router.delete(
    "/chats/{chat_id}/sessions",
    operation_id="sessions_delete",
    responses={200: {"model": RagflowOk[bool | BulkDeleteResult]}},
    openapi_extra=extra_doc(DeleteIdsRequest, required=False),
)
async def delete_sessions(
    chat_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> Response:
    """DELETE /chats/{chat_id}/sessions (C6): masowe usuwanie; częściowy sukces → errors."""
    # Brak czatu to ta sama odmowa 109 co cudzy czat (upstream ``_ensure_owned_chat``,
    # chat_api.py:949; złoto errors_access--51) — pre-check przed ciałem (DEC-091 p. 1).
    if not await _svc(request).ensure_owned(principal, chat_id):
        return refuse(request, principal, "sessions_delete", compat=profile)
    ids, delete_all = parse_delete_ids(await json_body(request))
    # Cudzy czat → 109 i nic nie znika z sesji właściciela (upstream ``_ensure_owned_chat``;
    # złoto errors_access--51, K11 §10c p. 10).
    try:
        res = await _svc(request).delete_many(principal, chat_id, ids, delete_all)
    except PermissionDenied as err:
        return refuse(request, principal, "sessions_delete", err, compat=profile)
    if res.nothing:
        return ok({})
    if res.errors:
        return ok({"success_count": res.success_count, "errors": res.errors})
    if profile == "ragflow_0_24":
        # Upstream v0.24 ``delete`` kończy ``get_result()`` — bez klucza ``data``
        # (złoto ``chats___sessions/chat_session--07.json``).
        return ok_code_only()
    return ok_true()
