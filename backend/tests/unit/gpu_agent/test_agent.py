"""Agent GPU: walidacja żądań i lista dozwolonych; Docker i nvidia-smi zastąpione atrapami."""

# ruff: noqa: PLR2004, S106

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from typing import Any

import pytest

from app.gpu_agent.docker_api import DockerApi
from app.gpu_agent.server import (
    OWNER_LABEL,
    Agent,
    AgentError,
    GpuInfo,
    gpu_util_for,
    make_handler,
    parse_smi,
)
from app.services.runpod.hosted import HOSTED_MODELS

MODEL = "xiaomi-ocr-0-localhost"
NAME = "wd-gpu-abc123def456"
UUID = "GPU-0f522488-66ae-c6cf-ecd0-5f0b7a7a321a"
TOKEN = "t" * 32
NET = "wd-net"
AGENT_TOKEN = "agent-token-0123456789"  # noqa: S105
GPU = GpuInfo(0, UUID, "RTX 4070 Ti SUPER", 16376, 14391, 1549, 3)


class FakeDocker(DockerApi):
    """Docker w pamięci: obraz jest, kontenery tworzone i kasowane przez żądania."""

    def __init__(self) -> None:
        super().__init__("/nonexistent")
        self.calls: list[tuple[str, str, Any]] = []
        self.containers: dict[str, dict[str, Any]] = {}
        self.fail_create = False

    def request(  # noqa: PLR0911
        self, method: str, path: str, body: Any = None
    ) -> tuple[int, bytes]:
        self.calls.append((method, path, body))
        if path.startswith("/images/"):
            return 200, b"{}"
        if path.startswith("/containers/create"):
            if self.fail_create:
                return 500, b'{"message":"boom"}'
            name = path.split("name=")[1]
            self.containers[name] = {
                "Config": {"Labels": body["Labels"]},
                "State": {"Running": True},
            }
            return 201, b"{}"
        name = path.split("/")[2].split("?", maxsplit=1)[0]
        if method == "POST":
            return 204, b""
        if method == "DELETE":
            self.containers.pop(name, None)
            return 204, b""
        if name in self.containers:
            return 200, json.dumps(self.containers[name]).encode()
        return 404, b"{}"


@pytest.fixture
def docker() -> FakeDocker:
    return FakeDocker()


@pytest.fixture
def agent(docker: FakeDocker) -> Agent:
    return Agent(docker, lambda: [GPU], network=NET, hf_volume="hf")


def body(**changes: str) -> dict[str, str]:
    return {"model": MODEL, "name": NAME, "gpu": UUID, "api_token": TOKEN, **changes}


def test_parse_smi_handles_missing_utilization_and_short_lines() -> None:
    rows = parse_smi(f"0, {UUID}, RTX 4070 Ti SUPER, 16376, 14391, 1549, [N/A]\nbroken,line\n")
    assert len(rows) == 1
    assert rows[0].memory_free_mb == 14391
    assert rows[0].utilization_pct is None


def test_gpu_util_targets_recommended_vram_and_is_capped() -> None:
    model = HOSTED_MODELS[MODEL]
    assert gpu_util_for(model, GPU) == pytest.approx(0.5, abs=0.01)
    small = GpuInfo(0, UUID, "x", 8192, 8192, 0, 0)
    assert gpu_util_for(model, small) == pytest.approx(0.85)


def test_start_uses_only_spec_from_code(agent: Agent, docker: FakeDocker) -> None:
    extra = {**body(), "image": "evil/image", "cmd": ["sh"], "binds": ["/:/host"]}
    agent.start(extra, background=False)
    create = next(c for c in docker.calls if c[1].startswith("/containers/create"))
    spec = create[2]
    assert spec["Image"] == HOSTED_MODELS[MODEL].image
    assert "sh" not in spec["Cmd"]
    assert spec["HostConfig"]["Binds"] == ["hf:/root/.cache/huggingface"]
    assert spec["HostConfig"]["NetworkMode"] == NET
    assert f"NVIDIA_VISIBLE_DEVICES={UUID}" in spec["Env"]
    assert "Privileged" not in spec["HostConfig"]
    assert agent.state(NAME) == {"name": NAME, "state": "running", "error": None}


@pytest.mark.parametrize(
    "changes",
    [
        {"model": "xiaomi-ocr-0-runpod"},
        {"model": "evil"},
        {"name": "postgres"},
        {"name": "wd-gpu-../../x"},
        {"gpu": "GPU-;rm"},
        {"gpu": "GPU-00000000-0000"},
        {"api_token": "short"},
        {"api_token": "x" * 20 + " --evil"},
    ],
)
def test_start_rejects_bad_input(agent: Agent, docker: FakeDocker, changes: dict[str, str]) -> None:
    with pytest.raises(AgentError):
        agent.start(body(**changes), background=False)
    assert not any(c[0] == "POST" for c in docker.calls)


def test_start_refuses_when_vram_is_taken(docker: FakeDocker) -> None:
    busy = GpuInfo(0, UUID, "x", 16376, 4000, 12000, 90)
    agent = Agent(docker, lambda: [busy], network=NET, hf_volume="hf")
    with pytest.raises(AgentError) as exc:
        agent.start(body(), background=False)
    assert exc.value.status == 409


def test_failed_start_is_reported(agent: Agent, docker: FakeDocker) -> None:
    docker.fail_create = True
    agent.start(body(), background=False)
    state = agent.state(NAME)
    assert state is not None
    assert state["state"] == "failed"
    assert "boom" in state["error"]


def test_foreign_container_is_invisible_and_untouched(agent: Agent, docker: FakeDocker) -> None:
    docker.containers[NAME] = {
        "Config": {"Labels": {OWNER_LABEL: "other"}},
        "State": {"Running": True},
    }
    assert agent.state(NAME) is None
    agent.stop(NAME)
    assert NAME in docker.containers


def test_stop_rejects_other_names(agent: Agent, docker: FakeDocker) -> None:
    with pytest.raises(AgentError):
        agent.stop("wawelsky-dragon-mariadb-1")
    assert docker.calls == []


@pytest.fixture
def server(agent: Agent) -> Iterator[int]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(agent, AGENT_TOKEN))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_address[1]
    httpd.shutdown()


def call(port: int, method: str, path: str, *, token: str | None = AGENT_TOKEN) -> int:
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    conn.request(method, path, headers=headers)
    status = conn.getresponse().status
    conn.close()
    return status


def test_http_requires_token_except_health(server: int) -> None:
    assert call(server, "GET", "/health", token=None) == 200
    assert call(server, "GET", "/gpus", token=None) == 401
    assert call(server, "GET", "/gpus", token="wrong") == 401
    assert call(server, "DELETE", f"/containers/{NAME}", token=None) == 401
    assert call(server, "GET", "/gpus") == 200
    assert call(server, "GET", f"/containers/{NAME}") == 404
    assert call(server, "GET", "/containers/..%2Fetc") == 400
