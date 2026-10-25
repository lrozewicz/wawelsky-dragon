"""Profil zgodności API ragflow (C7): nagłówek/query, klucz API, domyślna z Settings."""

from typing import Annotated, Literal, cast

from fastapi import Depends, Request

from app.api.auth.principal import container_of, get_principal
from app.api.ragflow.messages import MSG_COMPAT_INVALID
from app.core.errors import ValidationFailed
from app.domain.policy import Principal
from app.services.api_keys import ApiKeyService

CompatProfile = Literal["ragflow_0_27", "ragflow_0_24"]

# Wartości nagłówka/query → profil (C7).
_COMPAT_BY_VALUE: dict[str, CompatProfile] = {
    "0.24": "ragflow_0_24",
    "0.27": "ragflow_0_27",
}


def explicit_compat(request: Request) -> CompatProfile | None:
    """Profil 0.24/0.27 jawnie z żądania: nagłówek ``X-RAGFlow-Compat``, potem query (C4).

    Nieznana wartość i brak obu → ``None`` (bez wyjątków) — handler błędu nie może rzucać.
    """
    value = request.headers.get("x-ragflow-compat", "") or request.query_params.get("compat", "")
    return _COMPAT_BY_VALUE.get(value)


async def get_compat_profile(
    request: Request,
    principal: Principal = Depends(get_principal),  # noqa: B008 — DI FastAPI, sygnatura C7
) -> CompatProfile:
    """Profil zgodności żądania (C7) — kolejność: jwt/session, nagłówek→query, klucz, domyślna."""
    if principal.auth_kind in ("jwt", "session_cookie"):
        return "ragflow_0_27"
    value = request.headers.get("x-ragflow-compat", "") or request.query_params.get("compat", "")
    if value:
        profile = _COMPAT_BY_VALUE.get(value)
        if profile is None:
            raise ValidationFailed(MSG_COMPAT_INVALID.format(value=value))
        return profile
    if principal.api_key_id:
        service = cast(ApiKeyService, container_of(request).api_keys)
        stored = await service.compat_profile(principal.api_key_id)
        if stored is not None:
            return stored
    return container_of(request).settings.api_compat_default


CompatDep = Annotated[CompatProfile, Depends(get_compat_profile)]
