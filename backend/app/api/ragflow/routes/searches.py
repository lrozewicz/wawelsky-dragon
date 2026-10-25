"""Trasy CRUD /api/v1/searches (K15 §2, CONTRACT E4-4a §D5-§D7) — wzór ``routes/chats.py``."""

from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.auth.principal import PrincipalDep, container_of, json_body
from app.api.ragflow.compat import CompatDep
from app.api.ragflow.envelope import data_error, ok, ok_true
from app.api.ragflow.normalize.searches import (
    parse_search_create,
    parse_search_list,
    parse_search_update,
)
from app.api.ragflow.present.searches import (
    search_create_result,
    search_detail,
    search_full,
    search_list,
)
from app.api.ragflow.refusals import refuse
from app.api.ragflow.schemas.common import RagflowOk, extra_doc, query_param
from app.api.ragflow.schemas.searches import (
    SearchApp,
    SearchCompletionRequest,
    SearchCreateRequest,
    SearchCreateResult,
    SearchList,
    SearchUpdateRequest,
    SearchUpdateResult,
)
from app.api.ragflow.sse import search_reference, sse_ask
from app.core.error_codes import RetCode
from app.core.errors import PermissionDenied, ValidationFailed
from app.services.searches import SearchesService

router = APIRouter(prefix="/api/v1", tags=["searches"])

# Komunikat odmowy ``GET /searches/{id}`` (upstream ``get_json_result(data=False, code=103)``).
_MSG_NO_PERMISSION = "Has no permission for this operation."

# Nagłówki odpowiedzi SSE completion — te same co ``legacy_v024._ASK_HEADERS`` (C0 p. 6,
# upstream ``search_api.py::completion`` dodaje identyczny zestaw).
_ASK_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
_COMPLETION_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "model": RagflowOk[bool],
        "description": (
            'text/event-stream: ramki `data:{"code":0,"message":"","data":{…}}`, '
            'zakończone `data:{"code":0,"message":"","data":true}`'
        ),
        "content": {"text/event-stream": {"schema": {"type": "string"}}},
    }
}


def _svc(request: Request) -> SearchesService:
    """Usługa wyszukiwarek per żądanie (wzór ``routes/chats.py``)."""
    return SearchesService(container_of(request))


@router.post(
    "/searches",
    operation_id="searches_create",
    responses={200: {"model": RagflowOk[SearchCreateResult]}},
    openapi_extra=extra_doc(SearchCreateRequest),
)
async def create_search(request: Request, principal: PrincipalDep) -> Response:
    """POST /searches (§D5): utworzenie wyszukiwarki; nazwa zajęta → dopisek ``(n)``."""
    inp = parse_search_create(await json_body(request))
    try:
        search_id = await _svc(request).create(
            principal,
            name=inp.name,
            description=inp.description,
            avatar=inp.avatar,
            search_config=inp.search_config,
            kb_ids=None,
        )
    except ValidationFailed as err:
        # 102 bez klucza ``data`` (upstream ``get_data_error_result``; złoto searches--06).
        return data_error(str(err))
    return ok(search_create_result(search_id))


@router.get(
    "/searches",
    operation_id="searches_list",
    responses={200: {"model": RagflowOk[SearchList]}},
    openapi_extra=extra_doc(
        query=[
            query_param("keywords", {"type": "string"}, "Filtr po fragmencie nazwy"),
            query_param("page", {"type": "integer"}, "Numer strony (od 1)"),
            query_param("page_size", {"type": "integer"}, "Liczba elementów na stronie"),
            query_param("orderby", {"type": "string"}, "Sortowanie: create_time|update_time|name"),
            query_param("desc", {"type": "boolean"}, "Kolejność malejąca"),
            query_param(
                "owner_ids",
                {"type": "array", "items": {"type": "string"}},
                "Właściciele wyników (parametr powtarzalny)",
            ),
        ]
    ),
)
async def list_searches(request: Request, principal: PrincipalDep) -> Response:
    """GET /searches (§D5): stronicowana lista wyszukiwarek principala."""
    query = parse_search_list(
        dict(request.query_params),
        request.query_params.getlist("owner_ids"),
        max_size=container_of(request).settings.max_page_size,
    )
    views, total = await _svc(request).list(
        principal,
        keywords=query.keywords,
        orderby=query.orderby,
        desc=query.desc,
        page=query.page,
        page_size=query.page_size,
        owner_ids=query.owner_ids,
    )
    return ok(search_list(views, total))


@router.get(
    "/searches/{search_id}",
    operation_id="searches_get",
    responses={200: {"model": RagflowOk[SearchApp]}},
)
async def get_search(search_id: str, request: Request, principal: PrincipalDep) -> Response:
    """GET /searches/{search_id} (§D5): szczegół; brak lub cudza → 103 ``data: false``."""
    try:
        view = await _svc(request).get(principal, search_id)
    except PermissionDenied:
        return JSONResponse(
            {"code": int(RetCode.OPERATING_ERROR), "data": False, "message": _MSG_NO_PERMISSION}
        )
    return ok(search_detail(view))


@router.put(
    "/searches/{search_id}",
    operation_id="searches_update",
    responses={200: {"model": RagflowOk[SearchUpdateResult]}},
    openapi_extra=extra_doc(SearchUpdateRequest),
)
async def update_search(
    search_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> Response:
    """PUT /searches/{search_id} (§D5): pełna podmiana pól; cudza lub brak → 109."""
    inp = parse_search_update(await json_body(request))
    try:
        view = await _svc(request).update(
            principal,
            search_id,
            name=inp.name,
            search_config=inp.search_config,
            description=inp.description,
            avatar=inp.avatar,
        )
    except PermissionDenied as err:
        return refuse(request, principal, "searches_update", err, compat=profile)
    except ValidationFailed as err:
        return data_error(str(err))
    return ok(search_full(view))


@router.delete(
    "/searches/{search_id}",
    operation_id="searches_delete",
    responses={200: {"model": RagflowOk[bool]}},
)
async def delete_search(
    search_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> Response:
    """DELETE /searches/{search_id} (§D5): twarde usunięcie; cudza lub brak → 109."""
    try:
        await _svc(request).delete(principal, search_id)
    except PermissionDenied as err:
        return refuse(request, principal, "searches_delete", err, compat=profile)
    return ok_true()


@router.post(
    "/searches/{search_id}/completions",
    operation_id="searches_completions",
    responses=_COMPLETION_RESPONSES,
    openapi_extra=extra_doc(SearchCompletionRequest),
)
@router.post("/searches/{search_id}/completion", include_in_schema=False)
async def completions_search(
    search_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> Response:
    """POST /searches/{search_id}/completions (§D7): SSE podsumowania AI nad datasetami.

    Alias ``/completion`` (upstream ``search_api.py``) obsługuje ten sam handler.
    Kolejność: 101 (brak ``question``) → 109 (własność, ``refuse``) → 102 ``kb_ids``.
    """
    body = await json_body(request)
    question = body.get("question")
    if not isinstance(question, str):  # 101 jak pozostałe trasy (§D5, złoto searches--22)
        raise ValidationFailed("required argument are missing: question; ")
    raw_kb_ids = body.get("kb_ids")
    body_kb_ids = [str(item) for item in raw_kb_ids] if isinstance(raw_kb_ids, list) else []
    try:
        stream = await _svc(request).ask(principal, search_id, question, body_kb_ids)
    except PermissionDenied as err:
        return refuse(request, principal, "searches_completions", err, compat=profile)
    except ValidationFailed as err:
        return data_error(str(err))
    return StreamingResponse(
        # Referencja v0.27 (z ``row_id``/``document_metadata``; §D7, złoto searches--21.sse) —
        # nie v0.24 ``ask_reference`` z ``/sessions/ask``.
        sse_ask(stream.events, reference=search_reference),
        media_type="text/event-stream; charset=utf-8",
        headers=_ASK_HEADERS,
    )
