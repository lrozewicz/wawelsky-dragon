"""Wdrożenia na GPU serwera: panel, automat stanów i kasowanie przez atrapę ``gpu-agent``."""

# ruff: noqa: PLR2004

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.core.container import Container
from app.core.errors import Conflict, PermissionDenied, ValidationFailed
from app.db.repositories import models as models_repo
from app.db.repositories import runpod_pods as pods_repo
from app.db.uow import transaction
from app.domain.policy import Principal
from app.services.gpu_local import lifecycle
from app.services.gpu_local.lifecycle import register_local_models, tick_local
from app.services.gpu_local.service import LocalGpuService
from app.services.runpod import lifecycle as runpod_lifecycle
from app.services.runpod.guard import ensure_pod_ready
from app.services.runpod.hosted import LOCAL_CLOUD
from app.services.runpod.service import RunpodService
from app.worker.errors import PermanentError

pytestmark = pytest.mark.db

MODEL = "xiaomi-ocr-0-localhost"
UUID = "GPU-0f522488-66ae-c6cf-ecd0-5f0b7a7a321a"


class FakeAgent:
    """Agent w pamięci."""

    def __init__(self) -> None:
        self.free = 14391
        self.containers: dict[str, dict[str, Any]] = {}
        self.deleted: list[str] = []

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self._handle))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/gpus":
            gpu = {
                "index": 0,
                "uuid": UUID,
                "name": "RTX 4070 Ti SUPER",
                "memory_total_mb": 16376,
                "memory_free_mb": self.free,
                "memory_used_mb": 16376 - self.free,
                "utilization_pct": 1,
            }
            return httpx.Response(200, json={"gpus": [gpu]})
        if path == "/containers" and request.method == "POST":
            body = json.loads(request.content)
            self.containers[body["name"]] = {
                "name": body["name"],
                "state": "pulling",
                "error": None,
            }
            return httpx.Response(201, json={"name": body["name"], "state": "pulling"})
        name = path.removeprefix("/containers/")
        if request.method == "DELETE":
            self.deleted.append(name)
            self.containers.pop(name, None)
            return httpx.Response(204)
        found = self.containers.get(name)
        return httpx.Response(200, json=found) if found else httpx.Response(404, json={})


@pytest.fixture
def agent(container: Container) -> FakeAgent:
    fake_agent = FakeAgent()
    container.settings = container.settings.model_copy(
        update={"gpu_agent_url": "http://gpu-agent:9390"}
    )
    container.gpu_agent_http = fake_agent.client()  # type: ignore[attr-defined]
    return fake_agent


async def _row(container: Container, deployment_id: str) -> pods_repo.PodRow:
    assert container.sessionmaker is not None
    async with transaction(container.sessionmaker) as session:
        row = await pods_repo.get(session, deployment_id)
    assert row is not None
    return row


async def test_gpus_report_free_and_busy(
    container: Container, agent: FakeAgent, admin: Principal
) -> None:
    svc = LocalGpuService(container)
    data = await svc.gpus(admin, MODEL)
    assert data["agent"] == "ok"
    assert data["gpus"][0]["free"] is True
    assert data["gpus"][0]["vram_gb"] == 16
    agent.free = 4000
    assert (await svc.gpus(admin, MODEL))["gpus"][0]["free"] is False


async def test_without_agent_reports_not_configured_and_refuses_deploy(
    container: Container, admin: Principal
) -> None:
    svc = LocalGpuService(container)
    assert (await svc.gpus(admin, MODEL))["agent"] == "not_configured"
    with pytest.raises(Conflict):
        await svc.deploy(admin, model=MODEL, gpu_id=UUID)


async def test_only_superuser_and_only_local_models(
    container: Container, agent: FakeAgent, admin: Principal, user: Principal
) -> None:
    svc = LocalGpuService(container)
    with pytest.raises(ValidationFailed):
        await svc.gpus(admin, "xiaomi-ocr-0-runpod")
    with pytest.raises(PermissionDenied):
        await svc.gpus(user, MODEL)


async def test_deploy_rejects_busy_gpu(
    container: Container, agent: FakeAgent, admin: Principal
) -> None:
    agent.free = 4000
    with pytest.raises(Conflict):
        await LocalGpuService(container).deploy(admin, model=MODEL, gpu_id=UUID)
    assert agent.containers == {}


async def test_register_makes_model_selectable_as_parser(
    container: Container, agent: FakeAgent
) -> None:
    await register_local_models(container)
    assert container.sessionmaker is not None
    async with transaction(container.sessionmaker) as session:
        found = await models_repo.get_by_name(session, MODEL, "image2text")
    assert found is not None


async def test_full_lifecycle_and_terminate(
    container: Container,
    agent: FakeAgent,
    admin: Principal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = await LocalGpuService(container).deploy(admin, model=MODEL, gpu_id=UUID)
    assert view["status"] == "starting"
    assert view["cloud"] == LOCAL_CLOUD
    assert view["price_per_hr"] == 0
    row = await _row(container, view["id"])
    assert row.pod_id is not None
    with pytest.raises(PermanentError, match="this server"):
        await ensure_pod_ready(container, MODEL)

    agent.containers[row.pod_id]["state"] = "running"
    health = 502

    async def fake_health(_: str) -> int:
        return health

    monkeypatch.setattr(lifecycle, "health_status", fake_health)
    await tick_local(container)
    assert (await _row(container, row.id)).status == "loading"

    health = 200
    await tick_local(container)
    ready = await _row(container, row.id)
    assert ready.status == "ready"
    assert ready.base_url == f"http://{row.pod_id}:8000/v1"
    await ensure_pod_ready(container, MODEL)

    done = await RunpodService(container).terminate(admin, row.id)
    assert done["status"] == "terminated"
    assert agent.deleted == [row.pod_id]


async def test_container_gone_marks_failed(
    container: Container, agent: FakeAgent, admin: Principal
) -> None:
    view = await LocalGpuService(container).deploy(admin, model=MODEL, gpu_id=UUID)
    row = await _row(container, view["id"])
    assert row.pod_id is not None
    agent.containers[row.pod_id].update(state="failed", error="docker pull failed")
    await tick_local(container)
    failed = await _row(container, row.id)
    assert failed.status == "failed"
    assert "docker pull failed" in (failed.error or "")


async def test_runpod_tick_skips_local_rows_and_key_removal_ignores_them(
    container: Container, agent: FakeAgent, admin: Principal
) -> None:
    await LocalGpuService(container).deploy(admin, model=MODEL, gpu_id=UUID)
    assert await runpod_lifecycle.tick(container) == 0
    await RunpodService(container).remove_key(admin)


def test_model_lists_are_separate(container: Container) -> None:
    assert [m["name"] for m in RunpodService(container).hosted_models()] == ["xiaomi-ocr-0-runpod"]
    assert [m["name"] for m in LocalGpuService(container).models()] == [MODEL]


async def test_clear_history_is_per_provider(
    container: Container, agent: FakeAgent, admin: Principal
) -> None:
    svc = RunpodService(container)
    view = await LocalGpuService(container).deploy(admin, model=MODEL, gpu_id=UUID)
    await svc.terminate(admin, view["id"])
    assert await svc.clear_history(admin, local=False) == 0
    assert await svc.clear_history(admin, local=True) == 1
