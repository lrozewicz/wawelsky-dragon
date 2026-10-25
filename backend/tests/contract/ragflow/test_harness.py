"""Samotest harnessu (T4b, T4c): gotowość serwera z resetem, kształt złota i replay vs złoto."""

from __future__ import annotations

import json
import shutil

import httpx
import pytest

from tests.contract.ragflow.compare import Diff, load_deviations, unmatched
from tests.contract.ragflow.harness import (
    DEVIATIONS_DIR,
    SELFTEST_GOLDEN_DIR,
    SELFTEST_SCENARIOS_DIR,
)

pytestmark = pytest.mark.contract


def test_server_ready_and_reset(wd_server) -> None:
    """/health/ready = 200; reset zwraca klucz ragflow-; /users/me działa na tym kluczu."""
    assert httpx.get(f"{wd_server.base_url}/health/ready").status_code == httpx.codes.OK
    api_key = wd_server.reset()
    assert api_key.startswith("ragflow-"), api_key
    me = httpx.get(
        f"{wd_server.base_url}/api/v1/users/me",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert me.json()["code"] == 0, me.text


def test_reset_session_second_user(wd_server) -> None:
    """Sesja replayu ma niepuste klucze i JWT obu kont; klucz drugiego nie widzi zasobów admina.

    Krok `auth: second` scenariuszy złota wymaga sesji z `api_key_2` (brief H), a drugi
    użytkownik ma być odizolowany od danych admina (K9: tylko admin ma zasoby po resecie).
    """
    session = wd_server.reset_session()
    assert session.api_key and session.auth and session.api_key_2 and session.auth_2, session
    assert session.api_key != session.api_key_2
    with httpx.Client(base_url=wd_server.base_url, timeout=30.0) as client:
        created = client.post(
            "/api/v1/datasets",
            json={"name": "wd_h_second_user_ds"},
            headers={"Authorization": f"Bearer {session.api_key}"},
        )
        assert created.json()["code"] == 0, created.text
        payload = client.get(
            "/api/v1/datasets", headers={"Authorization": f"Bearer {session.api_key_2}"}
        ).json()
        assert payload["code"] == 0, payload
        assert payload["data"] == [], payload["data"]


def test_selftest_replay_writes_golden_shape(replay) -> None:
    """Replay users_me zapisuje golden o oczekiwanym kształcie, bajt w bajt z commitowanym."""
    out = replay("users_me", scenarios_dir=SELFTEST_SCENARIOS_DIR)
    actual = out / "users__me__models" / "users_me--01.json"
    golden = SELFTEST_GOLDEN_DIR / "v0.27.2" / "users__me__models" / "users_me--01.json"
    assert actual.is_file(), f"brak pliku wyniku: {actual}"
    payload = json.loads(actual.read_text(encoding="utf-8"))
    assert payload["request"] == {
        "method": "GET",
        "path": "/api/v1/users/me/models",
        "query": {},
        "body": None,
    }, payload["request"]
    assert payload["status"] == httpx.codes.OK, payload["status"]
    assert payload["body"]["code"] == 0, payload["body"]
    assert payload["body"]["data"] == {
        "llm_id": "fake-chat",
        "embd_id": "fake-embed-1024",
        "img2txt_id": "fake-vision",
        "rerank_id": "fake-rerank",
        "asr_id": "",
        "tts_id": "",
    }, payload["body"]["data"]
    assert actual.read_bytes() == golden.read_bytes(), (
        f"wynik różni się od commitowanego złota: {golden}"
    )


def test_selftest_replay_matches_golden(replay, compare_dir) -> None:
    """Replay users_me zgadza się ze złotem samotestu: zero niezgodnych Diffów."""
    diffs = compare_dir(
        replay("users_me", scenarios_dir=SELFTEST_SCENARIOS_DIR),
        SELFTEST_GOLDEN_DIR / "v0.27.2",
        "users_me",
        scenarios_dir=SELFTEST_SCENARIOS_DIR,
    )
    problems = unmatched(diffs, load_deviations(DEVIATIONS_DIR / "users_me.yaml"))
    assert problems == [], "\n".join(problems)


def test_selftest_detects_single_change(replay, compare_dir, tmp_path) -> None:
    """Zmiana body.code w kopii złota = dokładnie jeden Diff value golden=1, actual=0."""
    shutil.copytree(SELFTEST_GOLDEN_DIR / "v0.27.2", tmp_path / "golden")
    changed = tmp_path / "golden" / "users__me__models" / "users_me--01.json"
    payload = json.loads(changed.read_text(encoding="utf-8"))
    payload["body"]["code"] = 1
    changed.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    diffs = compare_dir(
        replay("users_me", scenarios_dir=SELFTEST_SCENARIOS_DIR),
        tmp_path / "golden",
        "users_me",
        scenarios_dir=SELFTEST_SCENARIOS_DIR,
    )
    assert diffs == [
        Diff(
            file="users__me__models/users_me--01.json",
            path="body.code",
            kind="value",
            golden=1,
            actual=0,
        )
    ]
