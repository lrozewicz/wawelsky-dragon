"""Testy prymitywów haseł — kontrakt C4 (wektory werkzeug 3.1.3, hasło Secret-pass1)."""

import hashlib

import pytest

from app.core.errors import ValidationFailed
from app.services.auth_passwords import (
    hash_password,
    needs_rehash,
    validate_new_password,
    verify_password,
)

PBKDF2_VECTOR = (
    "pbkdf2:sha256:1000$5puxVbVe8jVXvmXN$"
    "2eb391738a99e70a6de98be41da2410de93f5f1010c118622579afa8de6b798d"
)
SCRYPT_VECTOR = (
    "scrypt:16384:8:1$DdkOQ0E5LOm1dkz0$"
    "afddb3562de97fbc57e7e2116870c59d655a4025548500351f76afdf22a4200d"
    "d4c4f5aeec5452bc6bb59c7d97adfd0dd2bb7729edeb3f641620ba445b5165c1"
)


def test_hash_password_is_argon2id_and_verifies() -> None:
    h = hash_password("Secret-pass1")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "Secret-pass1") is True
    assert verify_password(h, "bad") is False


def test_verify_password_pbkdf2_werkzeug_vector() -> None:
    assert verify_password(PBKDF2_VECTOR, "Secret-pass1") is True
    assert verify_password(PBKDF2_VECTOR, "Secret-pass2") is False


def test_verify_password_scrypt_werkzeug_vector() -> None:
    assert verify_password(SCRYPT_VECTOR, "Secret-pass1") is True


@pytest.mark.parametrize(
    "stored_hash",
    [None, "", "md5$a$b", "pbkdf2:sha256:abc$s$h", "$argon2id$zepsuty"],
)
def test_verify_password_broken_format_is_false(stored_hash: str | None) -> None:
    assert verify_password(stored_hash, "x") is False


def test_verify_password_pbkdf2_defaults() -> None:
    # Puste parametry metody → domyślne sha256 + 1_000_000 (kontrakt C4).
    expected = hashlib.pbkdf2_hmac("sha256", b"x", b"sol", 1_000_000).hex()
    assert verify_password("pbkdf2:$sol$" + expected, "x") is True


def test_verify_password_scrypt_defaults() -> None:
    # Puste parametry n:r:p → domyślne 32768:8:1 (kontrakt C4).
    expected = hashlib.scrypt(
        b"x", salt=b"sol", n=32768, r=8, p=1, maxmem=132 * 32768 * 8 * 1
    ).hex()
    assert verify_password("scrypt:$sol$" + expected, "x") is True


@pytest.mark.parametrize("stored_hash", ["pbkdf2:sha256:1000$a$b", "scrypt:16384:8:1$a$b"])
def test_needs_rehash_legacy_is_true(stored_hash: str) -> None:
    assert needs_rehash(stored_hash) is True


def test_needs_rehash_fresh_argon2_is_false() -> None:
    assert needs_rehash(hash_password("x" * 8)) is False


@pytest.mark.parametrize("password", ["1234567", "x" * 257])
def test_validate_new_password_rejects_bad_length(password: str) -> None:
    with pytest.raises(ValidationFailed) as exc:
        validate_new_password(password)
    assert exc.value.message == "Password must be between 8 and 256 characters."


@pytest.mark.parametrize("password", ["12345678", "x" * 256])
def test_validate_new_password_accepts_boundary_lengths(password: str) -> None:
    assert validate_new_password(password) is None
