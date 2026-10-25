"""Samotest harnessu replay v0.24.0 (K11 §10d p. 15): nagłówek zgodności w wrapperze i serwerze."""

from __future__ import annotations

import httpx
import pytest

from tests.contract.ragflow.harness import (
    COMPAT_HEADER,
    SELFTEST_SCENARIOS_DIR,
    ReplaySession,
    load_runner,
    v024_auth_headers,
)

pytestmark = pytest.mark.contract

# Sesja o kształcie ReplaySession; wartości kluczy są zmyślone — wrapper ich nie zmienia.
SESSION = ReplaySession(
    base_url="http://127.0.0.1:1",
    api_key="ragflow-admin",
    auth="Bearer jwt-admin",
    api_key_2="ragflow-second",
    auth_2="Bearer jwt-second",
)


def test_v024_auth_headers_key_and_none_modes() -> None:
    """Wrapper dokłada COMPAT_HEADER do wyników `key` i `none` (K11 §10d p. 15)."""
    wrapped = v024_auth_headers(load_runner().auth_headers)
    assert wrapped(SESSION, "key") == {
        "Authorization": "Bearer ragflow-admin",
        "X-RAGFlow-Compat": "0.24",
    }
    assert wrapped(SESSION, "none") == {"X-RAGFlow-Compat": "0.24"}


@pytest.mark.parametrize("mode", ["key", "none", "bad"])
def test_v024_auth_headers_keeps_original(mode: str) -> None:
    """Dla key/none/bad wynik zawiera nagłówek zgodności i zachowuje resztę oryginału (C5)."""
    original = load_runner().auth_headers
    wrapped = v024_auth_headers(original)
    headers = wrapped(SESSION, mode)
    assert headers["X-RAGFlow-Compat"] == "0.24"
    assert {key: value for key, value in headers.items() if key != "X-RAGFlow-Compat"} == original(
        SESSION, mode
    )


def test_v024_auth_headers_returns_new_dict() -> None:
    """Wrapper zwraca nowy dict, nie mutuje oryginału ani stałej COMPAT_HEADER."""
    original = load_runner().auth_headers
    wrapped = v024_auth_headers(original)
    base = original(SESSION, "none")
    wrapped(SESSION, "none")
    assert base == {}
    assert COMPAT_HEADER == {"X-RAGFlow-Compat": "0.24"}


def test_v024_compat_header_reaches_users_me(wd_server) -> None:
    """Żądanie z nagłówkiem zgodności do /api/v1/users/me (klucz admina) zwraca code 0 (C5)."""
    session = wd_server.reset_session()
    headers = v024_auth_headers(load_runner().auth_headers)(session, "key")
    assert headers["X-RAGFlow-Compat"] == "0.24"
    response = httpx.get(f"{wd_server.base_url}/api/v1/users/me", headers=headers, timeout=30.0)
    assert response.json()["code"] == 0, response.text


def test_replay_v024_patches_auth_headers(replay) -> None:
    """Fixture replay dla `version="v0.24.0"` podmienia runner.auth_headers na wersję z nagłówkiem.

    Replay scenariusza samotestowego bez złota v0.24.0 tylko nagrywa wynik; weryfikujemy samą
    podmianę (C5): po replayu `runner.auth_headers` dokłada X-RAGFlow-Compat, a dla `v0.27.2`
    zostaje oryginał.
    """
    runner = load_runner()
    original = runner.auth_headers
    replay("users_me", version="v0.27.2", scenarios_dir=SELFTEST_SCENARIOS_DIR)
    assert runner.auth_headers is original
    replay("users_me", version="v0.24.0", scenarios_dir=SELFTEST_SCENARIOS_DIR)
    assert runner.auth_headers is not original
    assert runner.auth_headers(SESSION, "none") == {"X-RAGFlow-Compat": "0.24"}
