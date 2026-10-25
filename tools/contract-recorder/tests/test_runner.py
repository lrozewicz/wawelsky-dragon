"""Testy runnera scenariuszy (SP-5, kontrakt C2) — bez Dockera."""

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import runner
import yaml
from runner import (
    AUTH_MODES,
    auth_headers,
    binary_body,
    check_expect,
    endpoint_dir,
    load_scenario,
    run_scenario,
)

SCENARIO_NAMES = (
    "datasets_crud",
    "documents_parse",
    "chunks_list",
    "retrieval",
    "chat_session",
    "completion",
    "openai_compat",
)
SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "scenarios"


class TestEndpointDir:
    @pytest.mark.parametrize(
        ("path_template", "expected"),
        [
            ("/api/v1/datasets", "datasets"),
            ("/api/v1/datasets/{dataset_id}", "datasets___"),
            ("/api/v1/chats/{chat_id}/completions", "chats___completions"),
            (
                "/api/v1/chats_openai/{chat_id}/chat/completions",
                "chats_openai___chat__completions",
            ),
        ],
    )
    def test_contract_examples(self, path_template, expected):
        assert endpoint_dir(path_template) == expected


class TestLoadScenario:
    @pytest.mark.parametrize("name", SCENARIO_NAMES)
    def test_scenario_files_valid(self, name):
        scenario = load_scenario(SCENARIOS_DIR / f"{name}.yaml")
        assert scenario["name"] == name
        steps = scenario["steps"]
        step_ids = [step["id"] for step in steps]
        assert len(step_ids) == len(set(step_ids))
        for step in steps:
            assert step["method"] in runner.METHODS
            assert step["path"].startswith("/api/v1/")


class _Session:
    """Zamiennik RagflowSession (rf_bootstrap wymaga pycryptodomex)."""

    base_url = "http://testserver"
    api_key = "test-key"


class TestRunScenario:
    def test_records_normalized_golden(self, tmp_path, monkeypatch):
        dataset_id = "a" * 32

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/datasets":
                if request.method == "POST":
                    return httpx.Response(
                        200,
                        json={
                            "code": 0,
                            "data": {"id": dataset_id, "name": "wd_rec_ds"},
                        },
                    )
                if request.method == "GET":
                    return httpx.Response(
                        200,
                        json={
                            "code": 0,
                            "data": [{"id": dataset_id, "name": "wd_rec_ds_renamed"}],
                        },
                    )
                return httpx.Response(200, json={"code": 0, "data": True})
            if request.method == "PUT":
                return httpx.Response(
                    200,
                    json={
                        "code": 0,
                        "data": {"id": dataset_id, "name": "wd_rec_ds_renamed"},
                    },
                )
            raise AssertionError(
                f"nieoczekiwane żądanie: {request.method} {request.url}"
            )

        real_client = httpx.Client

        def patched_client(**kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real_client(**kwargs)

        monkeypatch.setattr(runner.httpx, "Client", patched_client)
        scenario = load_scenario(SCENARIOS_DIR / "datasets_crud.yaml")
        saved = run_scenario(_Session(), scenario, "v0.24.0", tmp_path)
        assert saved == 5
        created = tmp_path / "v0.24.0" / "datasets" / "datasets_crud--01.json"
        payload = json.loads(created.read_text(encoding="utf-8"))
        assert payload["request"]["method"] == "POST"
        assert payload["request"]["body"]["name"] == "wd_rec_ds"
        assert payload["body"]["data"]["id"] == "<ID:dataset#1>"
        deleted = tmp_path / "v0.24.0" / "datasets" / "datasets_crud--05.json"
        deleted_payload = json.loads(deleted.read_text(encoding="utf-8"))
        assert deleted_payload["request"]["body"] == {"ids": ["<ID:dataset#1>"]}

    def test_step_versions_skipped_but_numbered(self, tmp_path, monkeypatch):
        dataset_id = "b" * 32

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/datasets":
                return httpx.Response(200, json={"code": 0, "data": {"id": dataset_id}})
            return httpx.Response(200, json={"code": 0, "data": True})

        real_client = httpx.Client

        def patched_client(**kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real_client(**kwargs)

        monkeypatch.setattr(runner.httpx, "Client", patched_client)
        scenario = {
            "name": "versions_probe",
            "steps": [
                {
                    "id": "create_dataset",
                    "method": "POST",
                    "path": "/api/v1/datasets",
                    "json": {"name": "wd_rec_probe"},
                    "record": False,
                    "capture": {"dataset_id": "data.id"},
                },
                {
                    "id": "parse_v0_24",
                    "method": "POST",
                    "path": "/api/v1/datasets/{dataset_id}/chunks",
                    "versions": ["v0.24.0"],
                    "json": {"document_ids": ["x"]},
                },
                {
                    "id": "parse_v0_27",
                    "method": "POST",
                    "path": "/api/v1/datasets/{dataset_id}/documents/parse",
                    "versions": ["v0.27.2"],
                    "json": {"document_ids": ["x"]},
                },
            ],
        }
        saved = run_scenario(_Session(), scenario, "v0.27.2", tmp_path)
        assert saved == 1
        recorded = (
            tmp_path
            / "v0.27.2"
            / "datasets___documents__parse"
            / "versions_probe--03.json"
        )
        assert recorded.exists()
        assert not (tmp_path / "v0.27.2" / "datasets___").exists()

    def test_poll_records_final_response(self, tmp_path, monkeypatch):
        dataset_id = "c" * 32
        state = {"runs": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            state["runs"] += 1
            run_status = "RUNNING" if state["runs"] < 3 else "DONE"
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {"docs": [{"id": dataset_id, "run": run_status}]},
                },
            )

        real_client = httpx.Client

        def patched_client(**kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real_client(**kwargs)

        monkeypatch.setattr(runner.httpx, "Client", patched_client)
        monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)
        scenario = {
            "name": "poll_probe",
            "steps": [
                {
                    "id": "poll_done",
                    "method": "GET",
                    "path": "/api/v1/documents",
                    "query": {"page": 1},
                    "poll": {
                        "until": {"path": "data.docs.0.run", "equals": "DONE"},
                        "interval_s": 0,
                        "timeout_s": 5,
                    },
                }
            ],
        }
        saved = run_scenario(_Session(), scenario, "v0.24.0", tmp_path)
        assert saved == 1
        assert state["runs"] == 3
        recorded = tmp_path / "v0.24.0" / "documents" / "poll_probe--01.json"
        payload = json.loads(recorded.read_text(encoding="utf-8"))
        assert payload["body"]["data"]["docs"][0]["run"] == "DONE"

    def test_error_code_fails_scenario(self, tmp_path, monkeypatch):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"code": 102, "message": "don't own"})

        real_client = httpx.Client

        def patched_client(**kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real_client(**kwargs)

        monkeypatch.setattr(runner.httpx, "Client", patched_client)
        scenario = {
            "name": "fail_probe",
            "steps": [
                {"id": "list", "method": "GET", "path": "/api/v1/datasets"},
            ],
        }
        with pytest.raises(RuntimeError, match="code=102"):
            run_scenario(_Session(), scenario, "v0.24.0", tmp_path)


def _session() -> SimpleNamespace:
    """Sesja duck-typing wg C3 (bez importu rf_bootstrap/RagflowSession)."""
    return SimpleNamespace(
        base_url="http://testserver",
        api_key="test-key",
        auth="jwt-token",
        api_key_2="second-key",
        auth_2="second-jwt",
    )


def _patch_client(monkeypatch, handler) -> None:
    real_client = httpx.Client

    def patched_client(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(**kwargs)

    monkeypatch.setattr(runner.httpx, "Client", patched_client)


def _write_scenario(tmp_path: Path, name: str, steps: list[dict]) -> Path:
    path = tmp_path / f"{name}.yaml"
    path.write_text(
        yaml.safe_dump({"name": name, "steps": steps}, allow_unicode=True),
        encoding="utf-8",
    )
    return path


class TestAuthHeaders:
    def test_auth_modes_are_frozen(self):
        assert AUTH_MODES == ("key", "jwt", "second", "second_jwt", "none", "bad")

    @pytest.mark.parametrize(
        ("mode", "expected"),
        [
            ("key", {"Authorization": "Bearer test-key"}),
            ("jwt", {"Authorization": "jwt-token"}),
            ("second", {"Authorization": "Bearer second-key"}),
            ("second_jwt", {"Authorization": "second-jwt"}),
            ("none", {}),
            ("bad", {"Authorization": "Bearer ragflow-invalid-key-0000"}),
        ],
    )
    def test_contract_examples(self, mode, expected):
        assert auth_headers(_session(), mode) == expected

    def test_unknown_mode_raises(self):
        with pytest.raises(ValueError, match="auth"):
            auth_headers(_session(), "bad_mode")


class TestCheckExpect:
    def test_any_ignores_error_response(self):
        check_expect({"id": "x", "expect": "any"}, 500, {"code": 102})

    def test_matching_status_passes(self):
        check_expect({"id": "x", "expect": {"status": 200}}, 200, {"code": 0})

    def test_matching_status_and_code_passes(self):
        check_expect(
            {"id": "x", "expect": {"status": 404, "code": 102}}, 404, {"code": 102}
        )

    def test_status_mismatch_raises(self):
        with pytest.raises(RuntimeError, match="404"):
            check_expect({"id": "x", "expect": {"status": 404}}, 200, {"code": 0})

    def test_code_mismatch_raises(self):
        with pytest.raises(RuntimeError, match="102"):
            check_expect({"id": "x", "expect": {"code": 102}}, 200, {"code": 0})

    def test_code_missing_in_non_json_body_raises(self):
        with pytest.raises(RuntimeError, match="code"):
            check_expect({"id": "x", "expect": {"code": 0}}, 200, "not-json")


class TestBinaryBody:
    def test_contract_example(self):
        assert binary_body(b"abc") == {
            "length": 3,
            "sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        }


class TestEndpointDirExtensions:
    @pytest.mark.parametrize(
        ("path_template", "expected"),
        [
            ("/v1/system/healthz", "v1__system__healthz"),
            ("/dify/retrieval/health", "dify__retrieval__health"),
            ("/api/v1/datasets/{dataset_id}", "datasets___"),
        ],
    )
    def test_contract_examples(self, path_template, expected):
        assert endpoint_dir(path_template) == expected


class TestLoadScenarioExtensions:
    def test_accepts_new_fields(self, tmp_path):
        scenario = load_scenario(
            _write_scenario(
                tmp_path,
                "ext_valid",
                [
                    {
                        "id": "health",
                        "method": "GET",
                        "path": "/v1/system/healthz",
                        "auth": "none",
                        "expect": {"status": 200, "code": 0},
                    },
                    {
                        "id": "blob",
                        "method": "GET",
                        "path": "/api/v1/datasets",
                        "auth": "second_jwt",
                        "expect": "any",
                        "binary": True,
                    },
                ],
            )
        )
        assert scenario["steps"][0]["auth"] == "none"
        assert scenario["steps"][1]["binary"] is True

    @pytest.mark.parametrize(
        "extra",
        [
            {"auth": "bad_mode"},
            {"expect": "sometimes"},
            {"expect": {"foo": 1}},
            {"expect": {"status": "404"}},
            {"expect": {"code": "0"}},
            {"binary": "yes"},
        ],
    )
    def test_rejects_invalid_fields(self, tmp_path, extra):
        step = {"id": "x", "method": "GET", "path": "/api/v1/datasets"}
        step.update(extra)
        path = _write_scenario(tmp_path, "ext_invalid", [step])
        with pytest.raises(ValueError):
            load_scenario(path)


class TestRunScenarioExtensions:
    def test_expect_status_404_is_recorded(self, tmp_path, monkeypatch):
        dataset_id = "d" * 32

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/datasets":
                return httpx.Response(200, json={"code": 0, "data": {"id": dataset_id}})
            return httpx.Response(404, json={"code": 102, "message": "not found"})

        _patch_client(monkeypatch, handler)
        scenario = {
            "name": "expect_404",
            "steps": [
                {
                    "id": "create_dataset",
                    "method": "POST",
                    "path": "/api/v1/datasets",
                    "json": {"name": "wd_rec_expect"},
                    "record": False,
                    "capture": {"dataset_id": "data.id"},
                },
                {
                    "id": "missing",
                    "method": "GET",
                    "path": "/api/v1/datasets/{dataset_id}/documents",
                    "expect": {"status": 404},
                },
            ],
        }
        saved = run_scenario(_session(), scenario, "v0.27.2", tmp_path)
        assert saved == 1
        recorded = tmp_path / "v0.27.2" / "datasets___documents" / "expect_404--02.json"
        payload = json.loads(recorded.read_text(encoding="utf-8"))
        assert payload["status"] == 404
        assert payload["body"]["code"] == 102
        assert list(payload) == ["request", "status", "headers", "body"]

    def test_expect_status_mismatch_fails_scenario(self, tmp_path, monkeypatch):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"code": 0})

        _patch_client(monkeypatch, handler)
        scenario = {
            "name": "expect_mismatch",
            "steps": [
                {
                    "id": "missing",
                    "method": "GET",
                    "path": "/api/v1/datasets",
                    "expect": {"status": 404},
                }
            ],
        }
        with pytest.raises(RuntimeError, match="404"):
            run_scenario(_session(), scenario, "v0.27.2", tmp_path)

    def test_binary_step_records_digest(self, tmp_path, monkeypatch):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=b"abc",
                headers={"content-type": "application/octet-stream"},
            )

        _patch_client(monkeypatch, handler)
        scenario = {
            "name": "binary_probe",
            "steps": [
                {
                    "id": "blob",
                    "method": "GET",
                    "path": "/v1/system/healthz",
                    "binary": True,
                }
            ],
        }
        saved = run_scenario(_session(), scenario, "v0.27.2", tmp_path)
        assert saved == 1
        recorded = (
            tmp_path / "v0.27.2" / "v1__system__healthz" / "binary_probe--01.json"
        )
        payload = json.loads(recorded.read_text(encoding="utf-8"))
        assert payload["body"] == {
            "length": 3,
            "sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        }
        assert payload["headers"]["content-length"] == "3"
        assert payload["headers"]["content-type"] == "application/octet-stream"

    def test_auth_none_sends_no_authorization(self, tmp_path, monkeypatch):
        seen: dict[str, str | None] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["authorization"] = request.headers.get("authorization")
            return httpx.Response(200, json={"code": 0, "data": True})

        _patch_client(monkeypatch, handler)
        scenario = {
            "name": "auth_none",
            "steps": [
                {
                    "id": "health",
                    "method": "GET",
                    "path": "/v1/system/healthz",
                    "auth": "none",
                    "expect": "any",
                }
            ],
        }
        assert run_scenario(_session(), scenario, "v0.27.2", tmp_path) == 1
        assert seen["authorization"] is None

    def test_auth_second_uses_second_key(self, tmp_path, monkeypatch):
        seen: dict[str, str | None] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["authorization"] = request.headers.get("authorization")
            return httpx.Response(200, json={"code": 0, "data": True})

        _patch_client(monkeypatch, handler)
        scenario = {
            "name": "auth_second",
            "steps": [
                {
                    "id": "list",
                    "method": "GET",
                    "path": "/api/v1/datasets",
                    "auth": "second",
                    "expect": "any",
                }
            ],
        }
        assert run_scenario(_session(), scenario, "v0.27.2", tmp_path) == 1
        assert seen["authorization"] == "Bearer second-key"
