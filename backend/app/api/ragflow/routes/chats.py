"""Trasy CRUD /api/v1/chats (CONTRACT C6) — handler ≤ 15 linii, komunikaty C8."""

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from app.api.auth.principal import PrincipalDep, container_of, json_body
from app.api.ragflow.compat import CompatDep, CompatProfile
from app.api.ragflow.envelope import data_error, ok, ok_true
from app.api.ragflow.normalize.chats import (
    parse_chat_create,
    parse_chat_list,
    parse_chat_update,
    parse_delete_ids,
)
from app.api.ragflow.present.chats import chat_detail, chat_list
from app.api.ragflow.refusals import refuse
from app.api.ragflow.schemas.chats import (
    BulkDeleteResult,
    Chat,
    ChatList,
    CreateChatRequest,
    DeleteIdsRequest,
    UpdateChatRequest,
)
from app.api.ragflow.schemas.common import RagflowOk, extra_doc, query_param
from app.core.errors import Conflict, NotFound, PermissionDenied
from app.domain.policy import Principal
from app.services.chats import ChatsService

router = APIRouter(prefix="/api/v1", tags=["chats"])

# C4: komunikaty v0.24 różne od kanonicznych — klucz = komunikat serwisu, wartość = złoto
# (``chats___/chat_extras--22.json``: ``Duplicated chat name in updating chat.``).
_MESSAGES_V024 = {"duplicated chat name": "Duplicated chat name in updating chat."}


def ok_code_only() -> JSONResponse:
    """Koperta sukcesu 0.24 bez klucza ``data`` (C4; ``envelope.py`` bez zmian)."""
    return JSONResponse({"code": 0, "message": "success"})


def _svc(request: Request) -> ChatsService:
    """Usługa czatów per żądanie (K11 §1)."""
    return ChatsService(container_of(request))


@router.post(
    "/chats",
    operation_id="chats_create",
    responses={200: {"model": RagflowOk[Chat]}},
    openapi_extra=extra_doc(CreateChatRequest),
)
async def create_chat(request: Request, principal: PrincipalDep, profile: CompatDep) -> Response:
    """POST /chats (C6): utworzenie asystenta."""
    inp = parse_chat_create(await json_body(request), profile)
    return ok(chat_detail(await _svc(request).create(principal, inp), profile))


@router.get(
    "/chats",
    operation_id="chats_list",
    responses={200: {"model": RagflowOk[ChatList]}},
    openapi_extra=extra_doc(
        query=[
            query_param("page", {"type": "integer"}, "Numer strony (od 1)"),
            query_param("page_size", {"type": "integer"}, "Liczba elementów na stronie"),
            query_param("orderby", {"type": "string"}, "Sortowanie: create_time|update_time|name"),
            query_param("desc", {"type": "boolean"}, "Kolejność malejąca (C5)"),
            query_param("id", {"type": "string"}, "Filtr po id czatu"),
            query_param("name", {"type": "string"}, "Filtr po dokładnej nazwie"),
            query_param("keywords", {"type": "string"}, "Wyszukiwanie słów kluczowych (C5)"),
        ]
    ),
)
async def list_chats(request: Request, principal: PrincipalDep, profile: CompatDep) -> Response:
    """GET /chats (C6): stronicowana lista wg widoczności (R6)."""
    query = parse_chat_list(
        dict(request.query_params), profile, max_size=container_of(request).settings.max_page_size
    )
    views, total = await _svc(request).list(principal, query)
    return ok(chat_list(views, total, profile))


@router.get(
    "/chats/{chat_id}",
    operation_id="chats_get",
    responses={200: {"model": RagflowOk[Chat]}},
)
async def get_chat(
    chat_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> Response:
    """GET /chats/{chat_id} (C6): szczegół asystenta."""
    # Cudzy czat: upstream ``get_chat`` (chat_api.py:571-591) nie oddaje szczegółu komuś,
    # kto nie ma czatu wśród swoich tenantów → 109 ``no authorization`` (złoto --25).
    try:
        view = await _svc(request).get(principal, chat_id)
    except PermissionDenied as err:
        return refuse(request, principal, "chats_get", err, compat=profile)
    return ok(chat_detail(view, profile))


@router.put(
    "/chats/{chat_id}",
    operation_id="chats_replace",
    responses={200: {"model": RagflowOk[Chat]}},
    openapi_extra=extra_doc(UpdateChatRequest, required=False),
)
async def update_chat(
    chat_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> Response:
    """PUT /chats/{chat_id} (C6): pełna podmiana pól (merge=False)."""
    return await _update(chat_id, request, principal, profile, merge=False)


@router.patch(
    "/chats/{chat_id}",
    operation_id="chats_update",
    responses={200: {"model": RagflowOk[Chat]}},
    openapi_extra=extra_doc(UpdateChatRequest, required=False),
)
async def patch_chat(
    chat_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> Response:
    """PATCH /chats/{chat_id} (C6): doklejenie pól (merge=True)."""
    return await _update(chat_id, request, principal, profile, merge=True)


async def _update(
    chat_id: str,
    request: Request,
    principal: Principal,
    profile: CompatProfile,
    *,
    merge: bool,
) -> Response:
    """PUT/PATCH czatu: brak czatu u właściciela → 109, nazwa zajęta → 102 bez ``data``.

    Port ``chat_api.py:597`` i ``:680``: ``_ensure_owned_chat`` przed ciałem żądania,
    a ``get_data_error_result`` u upstream nie ma klucza ``data``.
    """
    svc = _svc(request)
    if not await svc.ensure_owned(principal, chat_id):
        return refuse(request, principal, "chats_update", compat=profile)
    inp = parse_chat_update(await json_body(request), profile, patch=merge)
    try:
        view = await svc.update(principal, chat_id, inp, merge=merge)
    except Conflict as err:
        # Profil 0.24 ma własną treść komunikatu o zajętej nazwie (C4); 0.27 bez zmian.
        message = str(err)
        if profile == "ragflow_0_24":
            message = _MESSAGES_V024.get(message, message)
        return data_error(message)
    if profile == "ragflow_0_24" and not merge:
        # C4: sam PUT w 0.24 zwraca sam kod (złoto ``chats___/chat_extras--19.json``);
        # PATCH zostaje z pełnym szczegółem (C4: „PATCH bez zmian").
        return ok_code_only()
    return ok(chat_detail(view, profile))


@router.delete(
    "/chats/{chat_id}",
    operation_id="chats_delete",
    responses={200: {"model": RagflowOk[bool]}},
)
async def delete_chat(chat_id: str, request: Request, principal: PrincipalDep) -> Response:
    """DELETE /chats/{chat_id} (C6, R3): twarde usunięcie, zawsze data=true."""
    await _svc(request).delete(principal, chat_id)
    return ok_true()


@router.delete(
    "/chats",
    operation_id="chats_delete_many",
    responses={200: {"model": RagflowOk[BulkDeleteResult]}},
    openapi_extra=extra_doc(DeleteIdsRequest, required=False),
)
async def delete_chats(request: Request, principal: PrincipalDep, profile: CompatDep) -> Response:
    """DELETE /chats (C6, R4): masowe usuwanie; sukces częściowy → success_count + errors."""
    ids, delete_all = parse_delete_ids(await json_body(request))
    try:
        res = await _svc(request).delete_many(principal, ids, delete_all)
    except NotFound as err:
        # Samo odrzucenie (0 usunięć) u upstream to ``get_data_error_result`` (102 bez ``data``;
        # złoto --52), a nie koperta handlera błędów — i nie usuwa niczego (K11 §10c p. 10).
        return refuse(request, principal, "chats_delete_many", err, compat=profile)
    if res.nothing:
        return ok({})
    if res.errors:
        return ok({"success_count": res.success_count, "errors": res.errors})
    return ok({"success_count": res.success_count})
