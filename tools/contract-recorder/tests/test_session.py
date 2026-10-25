"""Testy sesji bootstrapu (drugie konto + zapis/odczyt) i opcji CLI record.py — bez Dockera.

Zakres: WP E2-0, kontrakt C3 (RagflowSession, drugi uzytkownik), C4 (--keep/--attach/--out)
oraz zadanie T3 (--scenarios z wieloma wzorcami).
"""

import dataclasses
import json
import stat
from pathlib import Path

import pytest
import record
import rf_bootstrap
from rf_bootstrap import RagflowSession, load_session, save_session

VERSION = "v0.24.0"


def _session() -> RagflowSession:
    return RagflowSession(
        base_url="http://host.docker.internal:18380",
        api_key="api-key-1",
        auth="auth-1",
        chat_model="fake-chat___OpenAI-API@OpenAI-API-Compatible",
        embd_model="fake-embed-1024___OpenAI-API@OpenAI-API-Compatible",
        api_key_2="api-key-2",
        auth_2="auth-2",
    )


class TestSessionFile:
    def test_round_trip(self, tmp_path):
        path = save_session(_session(), VERSION, directory=tmp_path)
        assert path == tmp_path / f"wd-rec-session-{VERSION}.json"
        assert load_session(VERSION, directory=tmp_path) == _session()

    def test_file_holds_asdict(self, tmp_path):
        path = save_session(_session(), VERSION, directory=tmp_path)
        assert json.loads(path.read_text(encoding="utf-8")) == dataclasses.asdict(
            _session()
        )

    def test_file_mode_is_600(self, tmp_path):
        path = save_session(_session(), VERSION, directory=tmp_path)
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_session(VERSION, directory=tmp_path)

    def test_default_directory_is_tmp(self):
        assert rf_bootstrap.session_path(VERSION) == Path(
            f"/tmp/wd-rec-session-{VERSION}.json"
        )


class TestSecondAccount:
    def test_fields_default_to_empty(self):
        session = RagflowSession(
            base_url="u", api_key="k", auth="a", chat_model="c", embd_model="e"
        )
        assert (session.api_key_2, session.auth_2) == ("", "")

    def test_register_and_login_defaults_to_first_account(self):
        client = _FakeClient([_FakeResponse({"code": 0}), _login_response("AUTH-1")])
        assert rf_bootstrap._register_and_login(client, "v1") == "AUTH-1"
        assert client.calls[0][0] == "/v1/user/register"
        assert client.calls[0][1]["json"]["email"] == rf_bootstrap.RECORD_EMAIL
        assert client.calls[0][1]["json"]["nickname"] == rf_bootstrap.RECORD_NICKNAME

    def test_register_and_login_uses_given_identity(self):
        client = _FakeClient([_FakeResponse({"code": 0}), _login_response("AUTH-2")])
        assert (
            rf_bootstrap._register_and_login(client, "api/v1", "other@wd.test", "other")
            == "AUTH-2"
        )
        assert client.calls[0][0] == "/api/v1/users"
        assert client.calls[0][1]["json"]["email"] == "other@wd.test"
        assert client.calls[0][1]["json"]["nickname"] == "other"
        assert client.calls[1][0] == "/api/v1/auth/login"

    def test_register_tolerates_already_registered(self):
        client = _FakeClient(
            [
                _FakeResponse({"code": 102, "message": "Email has already registered"}),
                _login_response("AUTH-2"),
            ]
        )
        assert (
            rf_bootstrap._register_and_login(client, "v1", "x@wd.test", "x") == "AUTH-2"
        )

    def test_create_token_legacy_path(self):
        client = _FakeClient([_FakeResponse({"code": 0, "data": {"token": "tok-1"}})])
        assert rf_bootstrap._create_token(client, "v1", "AUTH-2") == "tok-1"
        assert client.calls == [
            ("/v1/system/new_token", {"headers": {"Authorization": "AUTH-2"}})
        ]

    def test_create_token_restful_path(self):
        client = _FakeClient([_FakeResponse({"code": 0, "data": {"token": "tok-2"}})])
        assert rf_bootstrap._create_token(client, "api/v1", "AUTH-2") == "tok-2"
        assert client.calls == [
            ("/api/v1/system/tokens", {"headers": {"Authorization": "AUTH-2"}})
        ]


class TestCollectScenarios:
    def test_two_patterns_are_merged(self, tmp_path, monkeypatch):
        monkeypatch.setattr(record, "SCRIPT_DIR", tmp_path)
        (tmp_path / "a.yaml").write_text("", encoding="utf-8")
        (tmp_path / "b.yaml").write_text("", encoding="utf-8")
        assert record._collect_scenarios(["a.yaml", "b.yaml"]) == [
            tmp_path / "a.yaml",
            tmp_path / "b.yaml",
        ]

    def test_same_file_from_two_patterns_once(self, tmp_path, monkeypatch):
        monkeypatch.setattr(record, "SCRIPT_DIR", tmp_path)
        (tmp_path / "a.yaml").write_text("", encoding="utf-8")
        assert record._collect_scenarios(["*.yaml", "a.yaml"]) == [tmp_path / "a.yaml"]

    def test_no_match_is_empty_list(self, tmp_path, monkeypatch):
        monkeypatch.setattr(record, "SCRIPT_DIR", tmp_path)
        assert record._collect_scenarios(["scenarios/*.yaml"]) == []

    def test_result_is_sorted(self, tmp_path, monkeypatch):
        monkeypatch.setattr(record, "SCRIPT_DIR", tmp_path)
        for name in ("b.yaml", "a.yaml", "c.yaml"):
            (tmp_path / name).write_text("", encoding="utf-8")
        assert record._collect_scenarios(["*.yaml"]) == [
            tmp_path / "a.yaml",
            tmp_path / "b.yaml",
            tmp_path / "c.yaml",
        ]


class TestParseArgs:
    def test_scenarios_accepts_many_patterns(self):
        args = record._parse_args(["--version", VERSION, "--scenarios", "a", "b"])
        assert args.scenarios == ["a", "b"]

    def test_scenarios_default(self):
        args = record._parse_args(["--version", VERSION])
        assert args.scenarios == ["scenarios/*.yaml"]

    def test_keep_and_attach_are_mutually_exclusive(self):
        with pytest.raises(SystemExit):
            record._parse_args(["--version", VERSION, "--keep", "--attach"])

    def test_out_is_path(self):
        args = record._parse_args(["--version", VERSION, "--out", "/tmp/golden"])
        assert args.out == Path("/tmp/golden")

    def test_defaults(self):
        args = record._parse_args(["--version", VERSION])
        assert (args.keep, args.attach, args.out) == (False, False, None)

    def test_keep_and_attach_alone_parse(self):
        assert record._parse_args(["--version", VERSION, "--keep"]).keep is True
        assert record._parse_args(["--version", VERSION, "--attach"]).attach is True


class _FakeResponse:
    def __init__(self, payload, headers=None, status_code=200):
        self._payload = payload
        self.headers = headers or {}
        self.status_code = status_code

    def json(self):
        return self._payload


class _FakeClient:
    """Podstawia httpx.Client: kolejne odpowiedzi wg listy, zapis wywolan w ``calls``."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self._responses.pop(0)


def _login_response(auth):
    return _FakeResponse({"code": 0}, headers={"Authorization": auth})
