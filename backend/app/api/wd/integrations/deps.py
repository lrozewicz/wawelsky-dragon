"""Zależności tras WD integracji: straż administratora, aktor audytu i opisy błędów (kontrakt §0).

Decyzja o dostępie zapada wyłącznie w ``app.domain.policy`` (kontrakt C3) — ten moduł tylko
woła ``require`` z akcją ``MANAGE``; żadne porównanie ``is_superuser`` tu nie występuje.
"""

from typing import Annotated, Any

from fastapi import Depends, Request

from app.api.auth.principal import PrincipalDep, client_ip
from app.api.wd.integrations.schemas import WdErrorResponse
from app.domain.policy import Action, Principal, ResourceRef, require
from app.services.integrations import Actor

_RESPONSE_DESCRIPTIONS: dict[int, str] = {
    400: "Niepoprawne żądanie (walidacja ciała lub parametrów)",
    401: "Brak lub niepoprawne uwierzytelnienie",
    403: "Brak uprawnień administratora",
    404: "Nie znaleziono zasobu",
    409: "Konflikt ze stanem zasobu",
    502: "Błąd usługi zewnętrznej (Microsoft Graph)",
}


async def require_admin(principal: PrincipalDep) -> Principal:
    """Wymaga akcji ``manage`` na zasobie ``integration`` i zwraca principal (kontrakt §0 p. 2)."""
    require(principal, Action.MANAGE, ResourceRef(kind="integration", owner_id=None))
    return principal


def actor_dep(request: Request, principal: Annotated[Principal, Depends(require_admin)]) -> Actor:
    """Aktor audytu mutacji: etykieta i id principala oraz IP klienta (kontrakt §0 p. 3)."""
    return Actor(label=principal.email or "user", id=principal.user_id, ip=client_ip(request))


def wd_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """Opisy odpowiedzi błędów w OpenAPI: kod → koperta ``WdErrorResponse`` (kontrakt §0 p. 10)."""
    return {
        code: {"model": WdErrorResponse, "description": _RESPONSE_DESCRIPTIONS.get(code, "Błąd")}
        for code in codes
    }
