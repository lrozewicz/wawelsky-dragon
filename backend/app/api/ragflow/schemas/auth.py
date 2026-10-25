"""Modele OpenAPI auth (C1, C3): widok użytkownika, sesja, tokeny, kanały logowania."""

from typing import Literal

from app.api.ragflow.schemas.common import RequestModel, ResponseModel


class User(ResponseModel):
    """Widok użytkownika (user_safe_dict, 07 §3.1) — klucze i kolejność dosłownie."""

    id: str
    email: str
    nickname: str
    avatar: str | None
    language: str
    color_schema: str
    timezone: str | None
    is_superuser: bool
    is_active: str
    last_login_time: str | None
    create_time: int
    create_date: str
    update_time: int
    update_date: str
    login_channel: str


class SessionUser(User):
    """Data loginu/rejestracji: User + access_token (session_response, C9)."""

    access_token: str


class AccessToken(ResponseModel):
    """Data auth_refresh (C9, 07 §3.2): token + czas życia w sekundach."""

    access_token: str
    expires_in: int


class LogoutOk(ResponseModel):
    """Odpowiedź auth_logout: data=true; logout_url tylko dla kont OIDC (R10)."""

    code: Literal[0]
    message: str
    data: bool
    logout_url: str | None = None


class LoginChannel(ResponseModel):
    """Element listy kanałów logowania (07 §3.3)."""

    channel: str
    display_name: str
    icon: str


class LoginRequest(RequestModel):
    """Ciało auth_login; brak pól → code 109 (handler rzuca, ciało wymagane)."""

    email: str | None = None
    password: str | None = None


REQUEST_MODELS: tuple[type[RequestModel], ...] = (LoginRequest,)
