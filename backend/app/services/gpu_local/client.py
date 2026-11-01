"""Klient usługi ``gpu-agent`` (sieć wewnętrzna stosu; token z ustawień, nigdy w logach)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

from app.services.runpod.client import RunpodError

if TYPE_CHECKING:
    from app.core.container import Container

TIMEOUT_S = 20.0
HTTP_NOT_FOUND = 404
HTTP_ERROR = 400


class GpuAgentError(RunpodError):
    """Agent odrzucił żądanie (``status``) albo jest nieosiągalny (``status`` 0)."""


class GpuAgentClient:
    """Lista GPU, start i kasowanie kontenerów modeli."""

    def __init__(self, base_url: str, token: str, *, http: httpx.AsyncClient | None = None) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}
        self._http = http

    async def _call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            if self._http is not None:
                return await self._request(self._http, method, path, **kwargs)
            async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
                return await self._request(client, method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise GpuAgentError("GPU agent is unreachable") from exc

    async def _request(
        self, client: httpx.AsyncClient, method: str, path: str, **kwargs: Any
    ) -> httpx.Response:
        return await client.request(method, self._base + path, headers=self._headers, **kwargs)

    @staticmethod
    def _raise_for(response: httpx.Response) -> None:
        if response.status_code < HTTP_ERROR:
            return
        try:
            message = str(response.json().get("error", "request failed"))
        except ValueError:
            message = "request failed"
        raise GpuAgentError(f"GPU agent: {message}", status=response.status_code)

    async def gpus(self) -> list[dict[str, Any]]:
        response = await self._call("GET", "/gpus")
        self._raise_for(response)
        gpus: list[dict[str, Any]] = response.json()["gpus"]
        return gpus

    async def start(self, *, model: str, name: str, gpu: str, api_token: str) -> None:
        body = {"model": model, "name": name, "gpu": gpu, "api_token": api_token}
        self._raise_for(await self._call("POST", "/containers", json=body))

    async def get_pod(self, name: str) -> dict[str, Any] | None:
        response = await self._call("GET", f"/containers/{name}")
        if response.status_code == HTTP_NOT_FOUND:
            return None
        self._raise_for(response)
        state: dict[str, Any] = response.json()
        return state

    async def delete_pod(self, name: str) -> None:
        self._raise_for(await self._call("DELETE", f"/containers/{name}"))


def local_client(container: Container) -> GpuAgentClient:
    """Klient z ustawień; bez ``WD_GPU_AGENT_URL`` wywołania kończą się ``GpuAgentError``."""
    settings = container.settings
    if not settings.gpu_agent_url:
        raise GpuAgentError("GPU agent is not configured")
    return GpuAgentClient(
        settings.gpu_agent_url,
        settings.gpu_agent_token.get_secret_value(),
        http=getattr(container, "gpu_agent_http", None),
    )
