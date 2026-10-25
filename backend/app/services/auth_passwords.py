"""Prymitywy haseł: argon2id dla nowych hashy + weryfikator legacy werkzeug (kontrakt C4)."""

import hashlib
import hmac

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.errors import ValidationFailed

PASSWORD_MIN_LEN = 8
PASSWORD_MAX_LEN = 256

_HASHER = PasswordHasher()  # argon2id, parametry domyślne biblioteki


def hash_password(password: str) -> str:
    """Hash argon2id (`"$argon2id$..."`)."""
    return _HASHER.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    """Weryfikacja hasła; `None`/pusty/znany zepsuty format → `False` (bez wyjątku)."""
    if not stored_hash:
        return False
    if stored_hash.startswith("$argon2"):
        try:
            return _HASHER.verify(stored_hash, password)
        except (VerificationError, InvalidHashError):
            return False
    return _verify_werkzeug(stored_hash, password)


def needs_rehash(stored_hash: str) -> bool:
    """`True` dla legacy (`pbkdf2:`/`scrypt:`); argon2 wg parametrów bieżącego hashera."""
    if stored_hash.startswith(("pbkdf2:", "scrypt:")):
        return True
    return _HASHER.check_needs_rehash(stored_hash)


def validate_new_password(password: str) -> None:
    """Długość poza [8, 256] → `ValidationFailed` (bez reguł złożoności, NIST 800-63B)."""
    if not PASSWORD_MIN_LEN <= len(password) <= PASSWORD_MAX_LEN:
        raise ValidationFailed(
            f"Password must be between {PASSWORD_MIN_LEN} and {PASSWORD_MAX_LEN} characters."
        )


def _verify_werkzeug(stored_hash: str, password: str) -> bool:
    """Weryfikator formatu werkzeug `metoda$sól$hexdigest` — każdy zły format → `False`."""
    try:
        method, salt, hexdigest = stored_hash.split("$", 2)
        name, *params = method.split(":")
        if name == "pbkdf2":
            raw_hash, raw_iter = [*params, "", ""][:2]
            computed = hashlib.pbkdf2_hmac(
                raw_hash or "sha256", password.encode(), salt.encode(), int(raw_iter or 1_000_000)
            ).hex()
        elif name == "scrypt":
            raw_n, raw_r, raw_p = [*params, "", "", ""][:3]
            n, r, p = int(raw_n or 32768), int(raw_r or 8), int(raw_p or 1)
            computed = hashlib.scrypt(
                password.encode(), salt=salt.encode(), n=n, r=r, p=p, maxmem=132 * n * r * p
            ).hex()
        else:
            return False
        return hmac.compare_digest(computed, hexdigest)
    except (TypeError, ValueError):
        return False
