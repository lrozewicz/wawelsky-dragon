"""Trasy rekomendacji pytań /api/v1 (CONTRACT C6): kanoniczna i alias zgodnościowy.

Kanoniczna ``POST /chat/recommendation`` (chat_api.py:1202) i alias
``POST /sessions/related_questions`` (backward_compat.py:480, ``deprecated: true``)
obsługuje ta sama metoda ``ChatsService.recommend_questions`` — model czatu tenanta,
ten sam prompt i parametry generacji; alias nie ma własnej logiki.

``search_id`` w ciele (CONTRACT E4-4a §D7, T4) wskazuje wyszukiwarkę, z której
``search_config`` bierzemy model (``chat_id``) i ``llm_setting``; wyszukiwarka
nieistniejąca albo cudza odmawia tak samo jak trasy czatu (koperta ``refuse``).
"""

from fastapi import APIRouter, Request, Response

from app.api.auth.principal import PrincipalDep, container_of, json_body
from app.api.ragflow.compat import CompatDep, CompatProfile
from app.api.ragflow.envelope import ok
from app.api.ragflow.normalize.chats import parse_recommendation, parse_recommendation_search_id
from app.api.ragflow.refusals import refuse
from app.api.ragflow.schemas.chats import RelatedQuestionsRequest
from app.api.ragflow.schemas.common import RagflowOk, extra_doc
from app.core.errors import PermissionDenied
from app.domain.policy import Principal
from app.services.chats import ChatsService
from app.services.searches import SearchesService

router = APIRouter(prefix="/api/v1", tags=["chats"])

# Komunikat przekazywany profilowi odmowy, gdy ten nie ma własnego szablonu (§D7).
_MSG_NO_AUTHORIZATION = "no authorization"


def _svc(request: Request) -> ChatsService:
    """Usługa czatów per żądanie (K11 §1) — niesie metodę rekomendacji pytań."""
    return ChatsService(container_of(request))


async def _recommend(request: Request, principal: Principal, profile: CompatProfile) -> Response:
    """Wspólne ciało obu tras: pytanie, ``search_id`` i odmowa właściciela (§D7)."""
    body = await json_body(request)
    question = parse_recommendation(body)
    search_id = parse_recommendation_search_id(body)
    if search_id is None:
        return ok(await _svc(request).recommend_questions(question))
    searches = SearchesService(container_of(request))
    row = await searches.config_for_recommendation(principal, search_id)
    if row is None:
        return refuse(
            request,
            principal,
            "chat_recommendation",
            PermissionDenied(_MSG_NO_AUTHORIZATION),
            compat=profile,
        )
    return ok(
        await _svc(request).recommend_questions(
            question,
            model_id=row.search_config.get("chat_id"),
            llm_setting=row.search_config.get("llm_setting"),
        )
    )


@router.post(
    "/chat/recommendation",
    operation_id="chat_recommendation",
    responses={200: {"model": RagflowOk[list[str]]}},
    openapi_extra=extra_doc(RelatedQuestionsRequest),
)
async def chat_recommendation(
    request: Request, principal: PrincipalDep, profile: CompatDep
) -> Response:
    """POST /chat/recommendation (C6, chat_api.py:1202): pytania pokrewne z modelu czatu."""
    return await _recommend(request, principal, profile)


@router.post(
    "/sessions/related_questions",
    operation_id="sessions_related_questions",
    deprecated=True,
    responses={200: {"model": RagflowOk[list[str]]}},
    openapi_extra=extra_doc(RelatedQuestionsRequest),
)
async def related_questions(
    request: Request, principal: PrincipalDep, profile: CompatDep
) -> Response:
    """POST /sessions/related_questions (C6, backward_compat.py:480): alias deprecated."""
    return await _recommend(request, principal, profile)
