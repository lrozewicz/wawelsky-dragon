"""Widok użytkownika dla koperty ragflow — user_safe_dict (kontrakt C9, 07 §3.1)."""

from datetime import UTC, datetime

from app.services.users import UserRow

# Format dat w odpowiedziach RAGFlow (konwencja wspólna kontraktu E1-1).
DATE_FMT = "%Y-%m-%d %H:%M:%S"


def fmt_date(ms: int) -> str:
    """Milisekundy epoki → DATE_FMT w UTC (create_date/update_date/last_login_time)."""
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime(DATE_FMT)


def user_safe_dict(user: UserRow) -> dict[str, object]:
    """Pola jak upstream to_safe_dict(for_self=True); nigdy password/password_hash (C9)."""
    return {
        "id": user.id,
        "email": user.email,
        "nickname": user.nickname,
        "avatar": user.avatar,
        "language": user.language,
        "color_schema": "Bright",
        "timezone": user.timezone,
        "is_superuser": user.is_superuser,
        "is_active": "1" if user.is_active else "0",
        "last_login_time": fmt_date(user.last_login_time) if user.last_login_time else None,
        "create_time": user.create_time,
        "create_date": fmt_date(user.create_time),
        "update_time": user.update_time,
        "update_date": fmt_date(user.update_time),
        "login_channel": "keycloak" if user.auth_source == "oidc" else "password",
    }
