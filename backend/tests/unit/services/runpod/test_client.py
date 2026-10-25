"""Klient RunPod: klasyfikacja błędów (auth, brak mocy, 404) i kształt żądań."""

import httpx
import pytest

from app.services.runpod.client import (
    RunpodAuthError,
    RunpodCapacityError,
    RunpodClient,
    RunpodError,
)
from app.services.runpod.hosted import HOSTED_MODELS, pod_body, proxy_url
from tests.fakes.runpod import FakeRunpod

HTTP_BAD_REQUEST = 400


def _client(fake: FakeRunpod, key: str = "rpa_test") -> RunpodClient:
    return RunpodClient(key, client=fake.client())


async def test_bad_key_is_an_auth_error() -> None:
    with pytest.raises(RunpodAuthError):
        await _client(FakeRunpod(), key="nope").verify()


async def test_capacity_message_is_classified() -> None:
    fake = FakeRunpod()
    fake.create_error = (500, "There are no instances currently available")
    with pytest.raises(RunpodCapacityError):
        await _client(fake).create_pod({"name": "x"})


async def test_other_errors_are_plain_errors() -> None:
    fake = FakeRunpod()
    fake.create_error = (400, "invalid image")
    with pytest.raises(RunpodError) as info:
        await _client(fake).create_pod({"name": "x"})
    assert not isinstance(info.value, RunpodCapacityError)
    assert info.value.status == HTTP_BAD_REQUEST


async def test_missing_pod_is_none_and_delete_is_idempotent() -> None:
    client = _client(FakeRunpod())
    assert await client.get_pod("nope") is None
    await client.delete_pod("nope")


async def test_network_failure_is_a_runpod_error() -> None:
    def boom(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    client = RunpodClient("k", client=httpx.AsyncClient(transport=httpx.MockTransport(boom)))
    with pytest.raises(RunpodError):
        await client.verify()


def test_pod_body_runs_vllm_with_token_and_http_port() -> None:
    model = HOSTED_MODELS["xiaomi-ocr-0-runpod"]
    body = pod_body(
        model,
        pod_name="abc",
        gpu_id="NVIDIA A40",
        api_token="tok",  # noqa: S106
        cloud="SECURE",
        data_center_ids=["EU-RO-1"],
    )
    assert body["gpu"] == {"id": "NVIDIA A40", "count": 1}
    assert body["ports"] == ["8000/http"] and body["dataCenterIds"] == ["EU-RO-1"]
    cmd = body["cmd"]
    assert cmd[cmd.index("--api-key") + 1] == "tok"
    assert cmd[cmd.index("--served-model-name") + 1] == "xiaomi-ocr-0-runpod"
    assert "dataCenterIds" not in pod_body(
        model,
        pod_name="a",
        gpu_id="g",
        api_token="t",  # noqa: S106
        cloud="SECURE",
        data_center_ids=[],
    )
    assert proxy_url("p1") == "https://p1-8000.proxy.runpod.net/v1"
