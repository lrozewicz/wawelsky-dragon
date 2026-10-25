"""Testy tokenów WD — kontrakt C4 (czas z FrozenClock, bez zegara systemowego)."""

import os

import jwt
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.core.errors import Unauthorized
from app.services.auth_tokens import (
    ISSUER,
    TokenClaims,
    TokenType,
    decode_token,
    issue_token,
    looks_like_wd_jwt,
    new_refresh_token,
    sha256_hex,
)
from tests.fakes.clock import FrozenClock

_NOW_MS = FrozenClock(1_790_157_600_000).now_ms()


@pytest.fixture(autouse=True)
def _clean_wd_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Izolacja od WD_* z env procesu — Settings() czyta tylko to, co test ustawi."""
    for name in list(os.environ):
        if name.startswith("WD_"):
            monkeypatch.delenv(name)


@pytest.fixture()
def settings() -> Settings:
    return Settings(env="test", secret_key=SecretStr("k" * 48))


def _issue(settings: Settings, *, typ: TokenType = "access", jti: str = "j1") -> str:
    return issue_token(settings, _NOW_MS, user_id="u" * 32, token_version=3, typ=typ, jti=jti)


def _manual_claims(**overrides: object) -> dict[str, object]:
    """Ręcznie zbudowane claims (wartość None usuwa klucz — np. brak exp)."""
    claims: dict[str, object] = {
        "iss": ISSUER,
        "sub": "u" * 32,
        "typ": "access",
        "tv": 1,
        "iat": _NOW_MS // 1000,
        "exp": _NOW_MS // 1000 + 900,
        "jti": "jm",
    }
    for key, value in overrides.items():
        if value is None:
            claims.pop(key, None)
        else:
            claims[key] = value
    return claims


def _tampered_signature() -> str:
    token = jwt.encode(_manual_claims(), "k" * 48, algorithm="HS256")
    return token[:-1] + ("A" if token[-1] != "A" else "B")


_INVALID_TOKENS = [
    pytest.param(jwt.encode(_manual_claims(), "x" * 48, algorithm="HS256"), id="other-secret"),
    pytest.param(_tampered_signature(), id="changed-signature"),
    pytest.param(
        jwt.encode(_manual_claims(iss="other"), "k" * 48, algorithm="HS256"), id="wrong-issuer"
    ),
    pytest.param(
        jwt.encode(_manual_claims(typ="refresh"), "k" * 48, algorithm="HS256"), id="bad-typ"
    ),
    pytest.param(
        jwt.encode(_manual_claims(exp=None), "k" * 48, algorithm="HS256"), id="missing-exp"
    ),
]


def test_issue_and_decode_access_token(settings: Settings) -> None:
    token = _issue(settings)
    assert decode_token(settings, _NOW_MS, token) == TokenClaims(
        user_id="u" * 32, typ="access", tv=3, jti="j1", exp=_NOW_MS // 1000 + 900
    )


def test_issue_and_decode_legacy_token(settings: Settings) -> None:
    token = _issue(settings, typ="legacy", jti="j2")
    claims = decode_token(settings, _NOW_MS, token)
    assert claims.exp == _NOW_MS // 1000 + 30 * 86400
    assert claims.typ == "legacy"


def test_decode_expired_token_raises_unauthorized(settings: Settings) -> None:
    token = _issue(settings)
    with pytest.raises(Unauthorized) as exc:
        decode_token(settings, _NOW_MS + 900_000, token)
    assert exc.value.message == "Invalid token"


def test_decode_token_just_before_expiry_is_ok(settings: Settings) -> None:
    token = _issue(settings, jti="j3")
    assert decode_token(settings, _NOW_MS + 899_000, token).jti == "j3"


@pytest.mark.parametrize("token", _INVALID_TOKENS)
def test_decode_rejects_invalid_tokens(settings: Settings, token: str) -> None:
    with pytest.raises(Unauthorized) as exc:
        decode_token(settings, _NOW_MS, token)
    assert exc.value.message == "Invalid token"


def test_looks_like_wd_jwt_true(settings: Settings) -> None:
    assert looks_like_wd_jwt(_issue(settings)) is True


@pytest.mark.parametrize(
    "token",
    [
        pytest.param("ragflow-abc", id="not-a-jwt"),
        pytest.param("a.b.c", id="garbage-segments"),
        pytest.param("", id="empty"),
        pytest.param(
            jwt.encode(_manual_claims(iss="other"), "k" * 48, algorithm="HS256"), id="wrong-issuer"
        ),
        pytest.param(jwt.encode(_manual_claims(), key=None, algorithm="none"), id="alg-none"),
    ],
)
def test_looks_like_wd_jwt_false(token: str) -> None:
    assert looks_like_wd_jwt(token) is False


def test_sha256_hex_known_vector() -> None:
    expected = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert sha256_hex("abc") == expected


def test_new_refresh_token_is_64_chars_and_unique() -> None:
    first, second = new_refresh_token(), new_refresh_token()
    assert len(first) == 64  # noqa: PLR2004 — token_urlsafe(48) daje dokładnie 64 znaki
    assert first != second
