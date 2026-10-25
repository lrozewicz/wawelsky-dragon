"""Trasy OpenAI-compat ``chat/completions`` /api/v1 (brief OC p. 2-3; 02-api §9).

Kanoniczna ``POST /openai/{chat_id}/chat/completions`` (upstream ``openai_api.py:237``)
i alias ``POST /chats_openai/{chat_id}/chat/completions`` (upstream ``backward_compat.py:108``,
``deprecated: true``) obsługuje ten sam handler. Odpowiedź sukcesu ma kształt OpenAI
(``choices``/``usage``; SSE ``chat.completion.chunk`` + ``data:[DONE]``), a nie kopertę
RAGFlow. Kody odmowy bez klucza ``data``: cudzy/nieistniejący czat → 102, nieznany ``model``
→ 101 (złota ``errors_access--35``, ``openai_dify--10``).
"""

from typing import Any, cast

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.auth.principal import PrincipalDep, container_of, json_body
from app.api.ragflow.compat import CompatDep, CompatProfile
from app.api.ragflow.envelope import argument_error, data_error
from app.api.ragflow.normalize.completions import openai_request_error, parse_completion
from app.api.ragflow.present.openai_chat import (
    SSE_MEDIA_TYPE,
    CompletionMeta,
    completion_id,
    completion_json,
    request_tokens,
    sse_chunks,
)
from app.api.ragflow.schemas.common import extra_doc
from app.api.ragflow.schemas.completions import OpenAIChatCompletionRequest
from app.api.ragflow.schemas.openai_chat import OpenAIChatCompletion
from app.services.chat import ChatService
from app.services.openai import ChatNotOwned, OpenAIService, UnknownModel

router = APIRouter(prefix="/api/v1", tags=["openai"])

# Odpowiedź 200 obu tras: JSON ``chat.completion`` przy stream=false, SSE OpenAI przy stream=true.
_OPENAI_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "model": OpenAIChatCompletion,
        "description": (
            "stream=false: JSON `chat.completion`; stream=true: text/event-stream — ramki "
            '`data:{"choices":[{"delta":…}],"object":"chat.completion.chunk",…}` '
            "zakończone ramką z `finish_reason: stop` i `usage` oraz `data:[DONE]`"
        ),
        "content": {"text/event-stream": {"schema": {"type": "string"}}},
    }
}

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


async def _chat_completions(
    request: Request, principal: PrincipalDep, profile: CompatProfile, chat_id: str
) -> Response:
    """Wspólna obsługa kanonicznej trasy i aliasu (upstream :237-420).

    Kolejność jak u upstreamu (:243-281): walidacja kształtu żądania (102), właściciel czatu (102),
    potem istnienie ``model`` (101) — wszystkie przed jakąkolwiek odpowiedzią. ``model`` = „model”
    znaczy „model czatu” (:270-271); inna nazwa trafia do odpowiedzi jako wybrany model. Profil
    ``ragflow_0_24``: brak walidacji ``model`` i ``model`` odpowiedzi = nazwa z żądania (upstream
    v0.24, złoto ``openai_compat--02``/``openai_dify--09`` — C0 p. 7).
    """
    body = await json_body(request)
    requested = str(body.get("model") or "")
    # Walidacja wejścia przed sprawdzeniem czatu (upstream :243-262); 102 bez ``data``, jak
    # pozostałe błędy danych tej trasy — DEC-092 p. 2.
    if (invalid := openai_request_error(body)) is not None:
        return data_error(invalid)
    service = OpenAIService(container_of(request))
    try:
        chat = await service.chat(principal, chat_id)
        await service.check_model(requested, profile)
        model = await service.response_model(chat, requested, profile)
    except ChatNotOwned as err:
        return data_error(str(err))
    except UnknownModel as err:
        return argument_error(str(err))
    # ``metadata_condition`` walidujemy po czacie i modelu, jak upstream (:281-283; DEC-092 p. 2).
    # Źródło filtra dla ``parse_completion`` bez zmian — klucz najwyższego poziomu ciała.
    extra_body = body.get("extra_body")
    condition = extra_body.get("metadata_condition") if isinstance(extra_body, dict) else None
    if condition and not isinstance(condition, dict):
        return data_error("metadata_condition must be an object.")
    # Brak ``stream``: w v0.24 true (upstream v0.24 czyta flagę wprost), w v0.27 false
    # (upstream :333) — inaczej niż na trasach natywnych, gdzie domyślnie true (K4 §1).
    call = parse_completion(
        body, profile, path_chat_id=chat_id, stream_default=profile == "ragflow_0_24"
    )
    chat_service = cast(ChatService, container_of(request).chat)
    prompt, reasoning_tokens = request_tokens(call.req.messages)
    meta = CompletionMeta(
        id=completion_id(chat_id),
        model=model,
        created=int(container_of(request).clock.now_ms() // 1000),
    )
    if not call.stream:
        result = await chat_service.complete_once(principal, call.req)
        return JSONResponse(
            completion_json(
                meta=meta,
                content=result.answer,
                prompt=prompt,
                reasoning_tokens=reasoning_tokens,
            )
        )
    stream = await chat_service.start(principal, call.req)
    return StreamingResponse(
        sse_chunks(stream.events, meta=meta, prompt=prompt),
        media_type=SSE_MEDIA_TYPE,
        headers=_SSE_HEADERS,
    )


@router.post(
    "/openai/{chat_id}/chat/completions",
    operation_id="openai_chat_completions",
    responses=_OPENAI_RESPONSES,
    openapi_extra=extra_doc(OpenAIChatCompletionRequest),
)
async def openai_chat_completions(
    chat_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> Response:
    """POST /openai/{chat_id}/chat/completions (02-api §9; upstream ``openai_api.py:237``)."""
    return await _chat_completions(request, principal, profile, chat_id)


@router.post(
    "/chats_openai/{chat_id}/chat/completions",
    operation_id="chats_openai_chat_completions",
    deprecated=True,
    responses=_OPENAI_RESPONSES,
    openapi_extra=extra_doc(OpenAIChatCompletionRequest),
)
async def chats_openai_chat_completions(
    chat_id: str, request: Request, principal: PrincipalDep, profile: CompatDep
) -> Response:
    """POST /api/v1/chats_openai/{chat_id}/chat/completions (backward_compat.py:108).

    Alias deprecated obsługiwany tym samym handlerem co trasa kanoniczna — łącznie z kodem
    odmowy 102 dla cudzego czatu (złoto ``chats_openai___chat__completions/errors_access--35``).
    """
    return await _chat_completions(request, principal, profile, chat_id)
