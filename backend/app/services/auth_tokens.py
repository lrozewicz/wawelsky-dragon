"""Tokeny WD: JWT HS256 access/legacy, refresh token i hashe (kontrakt C4, 07 §4)."""

import hashlib
import secrets
from dataclasses import dataclass
from typing import Literal

import jwt

from app.core.config import Settings
from app.core.errors import Unauthorized

ISSUER = "wawelsky-dragon"
TokenType = Literal["access", "legacy"]


@dataclass(frozen=True)
class TokenClaims:
    """Claims tokena WD (`sub`, `typ`, `tv`, `jti`, `exp` w sekundach epoki)."""

    user_id: str  # sub
    typ: TokenType
    tv: int
    jti: str
    exp: int  # sekundy epoch


def issue_token(  # noqa: PLR0913 — sygnatura z kontraktu C4
    settings: Settings, now_ms: int, *, user_id: str, token_version: int, typ: TokenType, jti: str
) -> str:
    """JWT HS256: TTL z `access_token_ttl_min` (access) albo `legacy_token_ttl_days` (legacy)."""
    ttl_s = (
        settings.access_token_ttl_min * 60
        if typ == "access"
        else settings.legacy_token_ttl_days * 86400
    )
    return jwt.encode(
        {
            "iss": ISSUER,
            "sub": user_id,
            "typ": typ,
            "tv": token_version,
            "iat": now_ms // 1000,
            "exp": now_ms // 1000 + ttl_s,
            "jti": jti,
        },
        settings.secret_key.get_secret_value(),
        algorithm="HS256",
    )


def looks_like_wd_jwt(token: str) -> bool:
    """Szybki podgląd bez weryfikacji podpisu: 3 segmenty (wymusza PyJWT), HS256, nasz `iss`."""
    try:
        if jwt.get_unverified_header(token)["alg"] != "HS256":
            return False
        return bool(jwt.decode(token, options={"verify_signature": False})["iss"] == ISSUER)
    except (jwt.PyJWTError, ValueError, KeyError):
        return False


def decode_token(settings: Settings, now_ms: int, token: str) -> TokenClaims:
    """Weryfikacja podpisu/`iss` + ręczna kontrola wygaśnięcia (czas z Clock, nie z systemu)."""
    try:
        claims = jwt.decode(
            token,
            settings.secret_key.get_secret_value(),
            algorithms=["HS256"],
            issuer=ISSUER,
            options={"verify_exp": False, "require": ["exp", "iat", "sub", "iss"]},
        )
        if claims["exp"] * 1000 <= now_ms:
            raise Unauthorized("Invalid token")
        typ: TokenType = claims["typ"]
        if typ not in ("access", "legacy"):
            raise Unauthorized("Invalid token")
        return TokenClaims(
            user_id=claims["sub"], typ=typ, tv=claims["tv"], jti=claims["jti"], exp=claims["exp"]
        )
    except (jwt.PyJWTError, KeyError, ValueError):
        raise Unauthorized("Invalid token") from None


def new_refresh_token() -> str:
    """Losowy refresh token (`secrets.token_urlsafe(48)` — 64 znaki)."""
    return secrets.token_urlsafe(48)


def sha256_hex(value: str) -> str:
    """SHA-256 jako hex (hash tokenu do bazy)."""
    return hashlib.sha256(value.encode()).hexdigest()
