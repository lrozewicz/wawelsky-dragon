"""Widoki DTO powierzchni hub-compat: user_item, user_detail, key_record (kontrakt C7, 03 §4)."""

from collections.abc import Sequence

from app.core.timeutil import rfc1123
from app.services.api_keys import ApiKeyView
from app.services.users import UserRow

# Słowniki wartości bez rozgałęzień `if` — grep-test polityki zabrania ich obok `is_superuser`.
_TOGGLES: dict[bool, str] = {True: "on", False: "off"}
_FLAGS: dict[bool, str] = {True: "true", False: "false"}


def user_item(row: UserRow) -> dict[str, object]:
    """Wiersz listy użytkowników hub-compat: `is_active` jako `"1"/"0"`, data RFC 1123 (C7)."""
    return {
        "email": row.email,
        "nickname": row.nickname,
        "is_active": "1" if row.is_active else "0",
        "is_superuser": row.is_superuser,
        "create_date": rfc1123(row.create_time),
    }


def user_detail(row: UserRow) -> dict[str, object]:
    """Szczegóły użytkownika: `user_item` + pola profilu (C7, 03 §4)."""
    return {
        **user_item(row),
        "avatar": row.avatar,
        "language": row.language,
        "last_login_time": rfc1123(row.last_login_time) if row.last_login_time else None,
        "update_date": rfc1123(row.update_time),
        "status": "1" if row.is_active else "0",
        "login_channel": "keycloak" if row.auth_source == "oidc" else "password",
        "is_anonymous": False,
    }


_CHANGE_TEXTS = {
    "nickname": "nickname updated",
    "is_active": "is_active set to {active}",
    "is_superuser": "is_superuser set to {super_value}",
}


def changes_message(
    changes: Sequence[str], *, active: bool | None, super_value: bool | None
) -> str:
    """Komunikat PUT `/api/users/{email}` wg C8: fragmenty zmian po przecinku, `no changes`."""
    values = {"active": _TOGGLES[bool(active)], "super_value": _FLAGS[bool(super_value)]}
    parts = [_CHANGE_TEXTS[change].format(**values) for change in changes]
    return ", ".join(parts) or "no changes"


def key_record(view: ApiKeyView) -> dict[str, object]:
    """Rekord klucza API dla hub-compat: pełny token, `tenant_id` = id użytkownika (C7)."""
    return {
        "token": view.token,
        "create_date": rfc1123(view.create_time),
        "create_time": view.create_time,
        "tenant_id": view.user_id,
        "dialog_id": None,
        "source": None,
        "beta": "",
    }
