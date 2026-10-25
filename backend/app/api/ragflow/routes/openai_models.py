"""Trasa ``GET /openai/{chat_id}/models`` (brief OD p. 3; 02-api §9 — rozszerzenie WD).

Odpowiedź w kształcie OpenAI (bez koperty RAGFlow), bo czyta ją klient OpenAI-compat.
Cudzy albo nieistniejący czat → 102 ``You don't own the chat <id>`` bez klucza ``data``
(upstream ``openai_api.py:274``; ten sam komunikat na ``/chats_openai`` w złocie
``errors_access--35``).
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.auth.principal import PrincipalDep, container_of
from app.api.ragflow.envelope import data_error
from app.api.ragflow.schemas.openai_models import OpenAIModels
from app.services.openai import ChatNotOwned, OpenAIService

router = APIRouter(prefix="/api/v1", tags=["openai_models"])

OWNED_BY = "wawelsky-dragon"


@router.get(
    "/openai/{chat_id}/models",
    operation_id="openai_models_list",
    responses={200: {"model": OpenAIModels}},
)
async def openai_models_list(
    chat_id: str, request: Request, principal: PrincipalDep
) -> JSONResponse:
    """Lista modeli przypisanych czatowi (jeden element: model czatu, 02-api §9)."""
    try:
        model = await OpenAIService(container_of(request)).chat_model_name(principal, chat_id)
    except ChatNotOwned as err:
        return data_error(str(err))
    return JSONResponse(
        {"object": "list", "data": [{"id": model, "object": "model", "owned_by": OWNED_BY}]}
    )
