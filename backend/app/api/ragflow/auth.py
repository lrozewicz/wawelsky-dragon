"""Trasy auth RAGFlow: login, refresh, logout, kanały logowania, logowanie Keycloak (C9, 07 §3)."""

from typing import cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.responses import RedirectResponse, Response

from app.api.auth.principal import PrincipalDep, client_ip, container_of, json_body
from app.api.ragflow.schemas.auth import (
    AccessToken,
    LoginChannel,
    LoginRequest,
    LogoutOk,
    SessionUser,
)
from app.api.ragflow.schemas.common import RagflowOk, extra_doc, query_param
from app.api.ragflow.user_view import user_safe_dict
from app.core.errors import AuthenticationFailed, NotFound
from app.services.auth import AccountDisabled, AuthService, SessionTokens
from app.services.oidc import OidcError
from app.services.users import UserService

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# Cookie sesji refresh (B3) — ścieżka ograniczona do tras auth.
_COOKIE = "wd_refresh"
_COOKIE_PATH = "/api/v1/auth"

# Cookie stanu przepływu OIDC (C9) — ścieżka ograniczona do callbacku.
_OIDC_COOKIE = "wd_oidc"
_OIDC_COOKIE_PATH = "/api/v1/auth/oauth/keycloak"


def _cookie_secure(request: Request) -> bool:
    """Flaga Secure cookie wg C1: dev/test bez Secure; w prod decyduje WD_COOKIE_SECURE.

    `auto` bierze pierwszą wartość `X-Forwarded-Proto` (proxy TLS ustawia `https`), a przy braku
    nagłówka — schemat żądania. Dzięki temu instalacja po HTTP w LAN nie traci sesji.
    """
    settings = container_of(request).settings
    if settings.env != "prod":
        return False
    if settings.cookie_secure != "auto":
        return settings.cookie_secure == "true"
    proto = request.headers.get("x-forwarded-proto")
    if proto:
        return proto.split(",")[0].strip().lower() == "https"
    return request.url.scheme == "https"


def _set_refresh_cookie(response: Response, tokens: SessionTokens, secure: bool) -> None:
    """Cookie wd_refresh: HttpOnly, SameSite=strict, Path=/api/v1/auth (C9, B3); Secure wg C1."""
    response.set_cookie(
        _COOKIE,
        tokens.refresh_token,
        max_age=tokens.refresh_max_age,
        path=_COOKIE_PATH,
        secure=secure,
        httponly=True,
        samesite="strict",
    )


def session_response(tokens: SessionTokens, message: str, request: Request) -> JSONResponse:
    """Wspólna odpowiedź loginu/rejestracji (i T7): koperta + Authorization + cookie (C9)."""
    data = {**user_safe_dict(tokens.user), "access_token": tokens.access_token}
    response = JSONResponse({"code": 0, "message": message, "data": data})
    response.headers["Authorization"] = tokens.legacy_token
    response.headers["Access-Control-Expose-Headers"] = "Authorization"
    _set_refresh_cookie(response, tokens, _cookie_secure(request))
    return response


@router.post(
    "/login",
    operation_id="auth_login",
    description=(
        "Błąd logowania/rejestracji: HTTP 200, code 109/403 (login) albo 103 "
        "(rejestracja wyłączona), `data: false`."
    ),
    responses={200: {"model": RagflowOk[SessionUser]}},
    openapi_extra=extra_doc(LoginRequest),
)
async def login(request: Request) -> JSONResponse:
    """Login lokalny; błędy uwierzytelnienia jak upstream: HTTP 200, code 109/403, data false."""
    body = await json_body(request)
    auth = cast(AuthService, container_of(request).auth)
    try:
        tokens = await auth.login_password(
            cast("str | None", body.get("email")),
            cast("str | None", body.get("password")),
            ip=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except (AuthenticationFailed, AccountDisabled) as err:
        return JSONResponse({"code": int(err.code), "message": err.message, "data": False})
    return session_response(tokens, "Welcome back!", request)


@router.post(
    "/refresh",
    operation_id="auth_refresh",
    responses={200: {"model": RagflowOk[AccessToken]}},
)
async def refresh(request: Request) -> JSONResponse:
    """Rotacja refresh tokenu z cookie wd_refresh; reuse rodziny → 401 (C9, 07 §3.2)."""
    auth = cast(AuthService, container_of(request).auth)
    tokens = await auth.refresh(
        request.cookies.get(_COOKIE),
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    response = JSONResponse(
        {
            "code": 0,
            "message": "success",
            "data": {"access_token": tokens.access_token, "expires_in": tokens.expires_in},
        }
    )
    _set_refresh_cookie(response, tokens, _cookie_secure(request))
    return response


@router.post(
    "/logout",
    operation_id="auth_logout",
    responses={200: {"model": LogoutOk}},
    openapi_extra=extra_doc(
        query=[
            query_param(
                "all", {"type": "boolean"}, "true: unieważnij wszystkie sesje użytkownika (C9)"
            )
        ]
    ),
)
async def logout(request: Request, principal: PrincipalDep) -> JSONResponse:
    """Wylogowanie; ?all=true unieważnia wszystkie tokeny użytkownika (C9, 07 §3.2).

    Pole logout_url (R10) tylko dla kont OIDC/both, gdy IdP poda end_session_endpoint.
    """
    container = container_of(request)
    auth = cast(AuthService, container.auth)
    all_sessions = request.query_params.get("all", "").lower() in ("1", "true")
    await auth.logout(principal, request.cookies.get(_COOKIE), all_sessions=all_sessions)
    body: dict[str, object] = {"code": 0, "message": "success", "data": True}
    if container.oidc is not None:
        url = await container.oidc.logout_url()
        users = cast(UserService, container.users)
        if url is not None and (await users.get(principal.user_id)).auth_source != "local":
            body["logout_url"] = url
    response = JSONResponse(body)
    response.delete_cookie(
        _COOKIE,
        path=_COOKIE_PATH,
        secure=_cookie_secure(request),
        httponly=True,
        samesite="strict",
    )
    return response


@router.get(
    "/login/channels",
    operation_id="auth_login_channels",
    responses={200: {"model": RagflowOk[list[LoginChannel]]}},
)
async def login_channels(request: Request) -> JSONResponse:
    """Kanały logowania; keycloak gdy issuer i client_id OIDC niepuste (C9, 07 §3.3)."""
    settings = container_of(request).settings
    enabled = bool(settings.oidc_issuer and settings.oidc_client_id)
    data: list[dict[str, str]] = (
        [{"channel": "keycloak", "display_name": "Keycloak", "icon": "sso"}] if enabled else []
    )
    return JSONResponse({"code": 0, "message": "success", "data": data})


@router.get(
    "/login/keycloak",
    operation_id="auth_login_keycloak",
    status_code=302,
    response_class=RedirectResponse,
    responses={
        302: {"description": "Przekierowanie (nagłówek Location) — IdP albo /?error=<slug> (C9)"}
    },
    openapi_extra=extra_doc(
        query=[
            query_param("redirect", {"type": "string"}, "Ścieżka powrotu po zalogowaniu (względna)")
        ]
    ),
)
async def login_keycloak(request: Request) -> RedirectResponse:
    """Początek logowania Keycloak: 302 do IdP + podpisane cookie stanu wd_oidc (C9, 07 §3.3)."""
    oidc = container_of(request).oidc
    if oidc is None or not oidc.enabled:
        raise NotFound("Invalid channel name: keycloak")
    start = await oidc.begin(request.query_params.get("redirect"))
    response = RedirectResponse(start.redirect_url, status_code=302)
    response.set_cookie(
        _OIDC_COOKIE,
        start.state_cookie,
        max_age=600,
        path=_OIDC_COOKIE_PATH,
        secure=_cookie_secure(request),
        httponly=True,
        samesite="lax",
    )
    return response


@router.get(
    "/oauth/keycloak/callback",
    operation_id="auth_keycloak_callback",
    status_code=302,
    response_class=RedirectResponse,
    responses={
        302: {"description": "Przekierowanie (nagłówek Location) — IdP albo /?error=<slug> (C9)"}
    },
    openapi_extra=extra_doc(
        query=[
            query_param("code", {"type": "string"}, "Kod autoryzacji z IdP"),
            query_param("state", {"type": "string"}, "Stan przepływu OIDC"),
        ]
    ),
)
async def oauth_keycloak_callback(request: Request) -> RedirectResponse:
    """Callback Keycloak: sesja WD jak przy loginie, albo 302 /?error=<slug> (C9, 07 §3.3)."""
    container = container_of(request)
    oidc = container.oidc
    if oidc is None or not oidc.enabled:
        raise NotFound("Invalid channel name: keycloak")
    try:
        user, redirect = await oidc.complete(
            code=request.query_params.get("code"),
            state=request.query_params.get("state"),
            state_cookie=request.cookies.get(_OIDC_COOKIE),
        )
    except OidcError as err:
        response = RedirectResponse(f"/?error={err.slug}", status_code=302)
        _clear_oidc_cookie(response, request)
        return response
    auth = cast(AuthService, container.auth)
    tokens = await auth.start_session(
        user.id, ip=client_ip(request), user_agent=request.headers.get("user-agent")
    )
    response = RedirectResponse(redirect, status_code=302)
    _set_refresh_cookie(response, tokens, _cookie_secure(request))
    _clear_oidc_cookie(response, request)
    return response


def _clear_oidc_cookie(response: Response, request: Request) -> None:
    """Kasowanie cookie stanu OIDC w obu gałęziach callbacku (C9); flagi jak przy ustawianiu."""
    response.delete_cookie(
        _OIDC_COOKIE,
        path=_OIDC_COOKIE_PATH,
        secure=_cookie_secure(request),
        httponly=True,
        samesite="lax",
    )
