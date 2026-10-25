"""Testy runnera MCP (WP E6-0, kontrakt T3a) — bez sieci i bez Dockera."""

import json
import sys
from pathlib import Path

import httpx
import pytest
import record
import yaml
from mcp_runner import (
    _error_payload,
    load_mcp_scenario,
    mcp_golden_path,
    normalize_mcp_result,
)
from normalize import IdRegistry

DATASET_ID = "00564be4d3f14f4a8e0f6d3a7b1c41af"


class TestNormalizeMcpResult:
    def test_nested_hex32_id_normalized(self):
        ids = IdRegistry()
        payload = {
            "serverInfo": {"name": "ragflow-mcp-server", "version": "1.2.3"},
            "data": {"datasets": [{"id": DATASET_ID, "name": "d1"}]},
        }
        normalized = normalize_mcp_result(payload, ids)
        assert normalized["data"]["datasets"][0]["id"] == "<ID:id#1>"
        assert normalized["data"]["datasets"][0]["name"] == "d1"
        assert normalized["serverInfo"]["name"] == "ragflow-mcp-server"

    def test_json_text_content_expanded_and_normalized(self):
        ids = IdRegistry()
        text = json.dumps(
            {"code": 0, "data": {"datasets": [{"id": DATASET_ID, "name": "d1"}]}}
        )
        payload = {"content": [{"type": "text", "text": text}]}
        normalized = normalize_mcp_result(payload, ids)
        assert normalized["content"][0]["text"] == {
            "code": 0,
            "data": {"datasets": [{"id": "<ID:id#1>", "name": "d1"}]},
        }

    def test_plain_text_content_unchanged(self):
        ids = IdRegistry()
        payload = {"content": [{"type": "text", "text": "brak wynikow"}]}
        assert normalize_mcp_result(payload, ids) == payload

    def test_broken_json_text_unchanged(self):
        ids = IdRegistry()
        payload = {"content": [{"type": "text", "text": "{nie json"}]}
        assert normalize_mcp_result(payload, ids) == payload

    def test_experimental_headers_redacted(self):
        ids = IdRegistry()
        payload = {
            "capabilities": {
                "experimental": {
                    "headers": {
                        "authorization": "Bearer ragflow-abc",
                        "user-agent": "x",
                    }
                }
            }
        }
        normalized = normalize_mcp_result(payload, ids)
        assert normalized["capabilities"]["experimental"]["headers"] == {
            "authorization": "<HEADER>",
            "user-agent": "<HEADER>",
        }

    def test_experimental_without_headers_unchanged(self):
        ids = IdRegistry()
        payload = {"capabilities": {"experimental": {}}}
        assert normalize_mcp_result(payload, ids) == payload

    def test_api_key_absent_from_serialization(self):
        ids = IdRegistry()
        payload = {
            "capabilities": {
                "experimental": {"headers": {"authorization": "Bearer ragflow-abc"}}
            }
        }
        normalized = normalize_mcp_result(payload, ids)
        assert "ragflow-abc" not in json.dumps(normalized)


def _scenario(tmp_path: Path, **overrides) -> Path:
    data = {
        "name": "mcp",
        "description": "test",
        "steps": [
            {
                "id": "initialize",
                "transport": "streamable_http",
                "op": "initialize",
                "auth": "key",
            }
        ],
    }
    data.update(overrides)
    path = tmp_path / "mcp.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


class TestLoadMcpScenario:
    def test_valid_scenario_loads(self, tmp_path):
        scenario = load_mcp_scenario(_scenario(tmp_path))
        assert scenario["name"] == "mcp"
        assert scenario["steps"][0]["op"] == "initialize"

    def test_bad_transport_rejected(self, tmp_path):
        path = _scenario(tmp_path)
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        data["steps"][0]["transport"] = "websocket"
        path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        with pytest.raises(ValueError, match="transport"):
            load_mcp_scenario(path)

    def test_bad_op_rejected(self, tmp_path):
        path = _scenario(tmp_path)
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        data["steps"][0]["op"] = "subscribe"
        path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        with pytest.raises(ValueError, match="op"):
            load_mcp_scenario(path)

    def test_bad_auth_rejected(self, tmp_path):
        path = _scenario(tmp_path)
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        data["steps"][0]["auth"] = "basic"
        path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        with pytest.raises(ValueError, match="auth"):
            load_mcp_scenario(path)

    def test_duplicate_step_id_rejected(self, tmp_path):
        step = {
            "id": "list_tools",
            "transport": "sse",
            "op": "list_tools",
            "auth": "key",
        }
        path = _scenario(tmp_path, steps=[step, dict(step)])
        with pytest.raises(ValueError, match="zduplikowane"):
            load_mcp_scenario(path)


class TestMcpGoldenPath:
    def test_step_three_list_tools_filename(self):
        target = mcp_golden_path(Path("/out"), "mcp", 3, "list_tools")
        assert target == Path("/out/v0.27.2/mcp/mcp--03-list_tools.json")
        assert target.name == "mcp--03-list_tools.json"


def _status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://host.docker.internal:19382/mcp")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(str(status), request=request, response=response)


class TestErrorPayload:
    def test_http_status_extracted(self):
        payload = _error_payload(_status_error(401))
        assert payload["error_type"] == "HTTPStatusError"
        assert payload["http_status"] == 401

    def test_single_exception_group_unwrapped(self):
        group = ExceptionGroup("anyio", [_status_error(401)])  # noqa: F821 (3.11+)
        payload = _error_payload(group)
        assert payload["error_type"] == "HTTPStatusError"
        assert payload["http_status"] == 401


class TestRecordMcpFlag:
    def test_mcp_flag_parsed(self):
        assert record._parse_args(["--version", "v0.27.2", "--mcp"]).mcp is True
        assert record._parse_args(["--version", "v0.27.2"]).mcp is False

    def test_mcp_rejects_v0240(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["record.py", "--version", "v0.24.0", "--mcp"])
        assert record.main() == 2
