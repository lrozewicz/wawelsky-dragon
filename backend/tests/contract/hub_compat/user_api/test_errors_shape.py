"""Kształt błędów powierzchni hub-compat (brief T6a, kontrakt C7 i C8; AG-18).

Każdy błąd SVC to `{"error": "<komunikat>"}`; walidacja daje **400** (nigdy 422),
a statusy 401/404/405/409 mają tę samą kopertę.
"""

from typing import Any

import httpx
import pytest

pytestmark = [pytest.mark.db, pytest.mark.contract, pytest.mark.hub_compat]

_BAD_REQUEST = 400
_UNAUTHORIZED = 401
_NOT_FOUND = 404
_METHOD_NOT_ALLOWED = 405
_CONFLICT = 409
_UNPROCESSABLE = 422

_ANN = "ann%40x.pl"
# Hasło atrapy (nie jest prawdziwym sekretem), ≥ 8 znaków wg validate_new_password.
_PASSWORD = "Sup3r-secret-pw"  # noqa: S105


def _assert_error(envelope: Any, status: int) -> None:
    """Koperta błędu SVC: dokładnie status i `{"error": <niepusty string>}` (nigdy 422)."""
    assert envelope.status_code == status
    assert envelope.status_code != _UNPROCESSABLE
    body = envelope.json()
    assert set(body) == {"error"}
    assert isinstance(body["error"], str)
    assert body["error"]


async def test_ag18_error_shape_and_400_not_422(
    svc: httpx.AsyncClient, anon: httpx.AsyncClient, prefix: str
) -> None:
    """AG-18: walidacja → 400, nigdy 422; wszystkie błędy SVC mają kształt `{error}`."""
    raw = await svc.post(
        f"{prefix}/api/users",
        content=b"to nie jest JSON",
        headers={"Content-Type": "application/json"},
    )
    _assert_error(raw, _BAD_REQUEST)
    assert raw.json() == {"error": "email and password are required"}

    not_dict = await svc.post(f"{prefix}/api/users", json=["ann@x.pl", _PASSWORD])
    _assert_error(not_dict, _BAD_REQUEST)

    missing = await svc.post(f"{prefix}/api/users", json={"email": "ann@x.pl"})
    _assert_error(missing, _BAD_REQUEST)

    wrong_type = await svc.post(f"{prefix}/api/users", json={"email": 123, "password": _PASSWORD})
    _assert_error(wrong_type, _BAD_REQUEST)

    wrong_nickname = await svc.post(
        f"{prefix}/api/users", json={"email": "ann@x.pl", "password": _PASSWORD, "nickname": 123}
    )
    _assert_error(wrong_nickname, _BAD_REQUEST)

    await svc.post(f"{prefix}/api/users", json={"email": "ann@x.pl", "password": _PASSWORD})
    duplicate = await svc.post(
        f"{prefix}/api/users", json={"email": "ANN@x.pl", "password": _PASSWORD}
    )
    _assert_error(duplicate, _CONFLICT)
    assert duplicate.json() == {"error": "User already exists"}

    not_found = await svc.get(f"{prefix}/api/users/ghost%40nowhere.test")
    _assert_error(not_found, _NOT_FOUND)

    method = await svc.patch(f"{prefix}/api/access")
    _assert_error(method, _METHOD_NOT_ALLOWED)
    assert method.json() == {"error": "Method not allowed"}

    no_secret = await anon.get(f"{prefix}/api/access", params={"email": "x@x.pl"})
    _assert_error(no_secret, _UNAUTHORIZED)
    assert no_secret.json() == {"error": "Unauthorized"}
