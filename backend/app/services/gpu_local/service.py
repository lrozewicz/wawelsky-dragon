"""Usługa panelu „GPU → Ten serwer”: lista kart i modeli oraz wdrożenie przez ``gpu-agent``.

Zapisy i lista kart wymagają superusera; odczyt, kasowanie i parsowanie wdrożeń są w
``RunpodService`` (wspólna tabela i stany).
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING, Any

from app.core.crypto import encrypt
from app.core.errors import Conflict, UpstreamError, ValidationFailed
from app.db.repositories import runpod_pods as pods_repo
from app.db.uow import transaction
from app.domain.policy import Principal
from app.services.gpu_local.client import GpuAgentClient, GpuAgentError, local_client
from app.services.provider_common import require_superuser
from app.services.runpod.hosted import (
    LOCAL_CLOUD,
    PROVIDER_LOCAL,
    HostedModel,
    get_model,
    models_for,
)
from app.services.runpod.lifecycle import PANEL_ORIGIN, PARSE_ORIGIN
from app.services.runpod.registry import ensure_registered
from app.services.runpod.service import RunpodService

if TYPE_CHECKING:
    from app.core.container import Container

MIB_PER_GB = 1024
HTTP_CONFLICT = 409


class LocalGpuService:
    """Operacje panelu dla GPU serwera WD."""

    def __init__(self, container: Container) -> None:
        self._c = container

    def models(self) -> list[dict[str, Any]]:
        """Modele, które można uruchomić na GPU tego serwera."""
        return [
            {
                "name": m.name,
                "title": m.title,
                "hf_model": m.hf_model,
                "min_vram_gb": m.min_vram_gb,
                "recommended_vram_gb": m.recommended_vram_gb,
            }
            for m in models_for(PROVIDER_LOCAL)
        ]

    async def gpus(self, principal: Principal, model: str) -> dict[str, Any]:
        """Karty z VRAM i stanem wolna/zajęta dla modelu oraz stan agenta."""
        require_superuser(principal)
        hosted = self._hosted(model)
        base = {"model": hosted.name, "min_vram_gb": hosted.min_vram_gb}
        if not self._c.settings.gpu_agent_url:
            return {**base, "agent": "not_configured", "gpus": []}
        try:
            raw = await local_client(self._c).gpus()
        except GpuAgentError:
            return {**base, "agent": "unreachable", "gpus": []}
        return {**base, "agent": "ok", "gpus": [_gpu_view(g, hosted) for g in raw]}

    async def deploy(
        self,
        principal: Principal,
        *,
        model: str,
        gpu_id: str,
        parse: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Zakłada wdrożenie i zleca agentowi start; po gotowości WD samo uruchamia ``parse``."""
        require_superuser(principal)
        hosted = self._hosted(model)
        assert self._c.sessionmaker is not None  # noqa: S101
        async with transaction(self._c.sessionmaker) as session:
            active = [
                r for r in await pods_repo.list_active(session) if r.model_name == hosted.name
            ]
        if active:
            raise Conflict(
                f"{hosted.title} is already being deployed or running",
                details={"deployment_id": active[0].id},
            )
        client = self._client()
        gpu = await self._choose(client, hosted, gpu_id)
        deployment_id = self._c.id_gen.new_id()
        name = f"wd-gpu-{deployment_id[-12:].lower()}"
        token = secrets.token_urlsafe(32)
        await self._insert(principal, hosted, gpu, deployment_id, token, parse or [])
        await ensure_registered(
            self._c, hosted, base_url=None, api_token=None, created_by=principal.user_id
        )
        try:
            await client.start(model=hosted.name, name=name, gpu=gpu["uuid"], api_token=token)
        except GpuAgentError as exc:
            await self._finish_failed(deployment_id, exc.message)
            if exc.status == HTTP_CONFLICT:
                raise Conflict(exc.message) from exc
            raise UpstreamError(exc.message) from exc
        async with transaction(self._c.sessionmaker) as session:
            await pods_repo.update_fields(
                session,
                deployment_id,
                now_ms=self._c.clock.now_ms(),
                status="starting",
                pod_id=name,
            )
        return await RunpodService(self._c).get(deployment_id)

    def _hosted(self, name: str) -> HostedModel:
        hosted = get_model(name)
        if hosted is None or hosted.provider != PROVIDER_LOCAL:
            raise ValidationFailed(f"model cannot run on this server: {name}")
        return hosted

    def _client(self) -> GpuAgentClient:
        try:
            return local_client(self._c)
        except GpuAgentError as exc:
            raise Conflict(exc.message) from exc

    async def _choose(
        self, client: GpuAgentClient, hosted: HostedModel, gpu_id: str
    ) -> dict[str, Any]:
        try:
            gpus = await client.gpus()
        except GpuAgentError as exc:
            raise UpstreamError(exc.message) from exc
        gpu = next((g for g in gpus if g["uuid"] == gpu_id), None)
        if gpu is None:
            raise ValidationFailed(f"unknown GPU: {gpu_id}")
        if not _is_free(gpu, hosted):
            raise Conflict(f"{hosted.title} needs {hosted.min_vram_gb} GB of free VRAM")
        return gpu

    async def _insert(  # noqa: PLR0913, PLR0917
        self,
        principal: Principal,
        hosted: HostedModel,
        gpu: dict[str, Any],
        deployment_id: str,
        token: str,
        parse: list[dict[str, Any]],
    ) -> None:
        assert self._c.sessionmaker is not None  # noqa: S101
        enc = encrypt(
            self._c.settings.crypto_key.get_secret_value(),
            token.encode(),
            f"runpod-pod:{deployment_id}".encode(),
        )
        async with transaction(self._c.sessionmaker) as session:
            await pods_repo.insert(
                session,
                deployment_id=deployment_id,
                model_name=hosted.name,
                origin=PARSE_ORIGIN if parse else PANEL_ORIGIN,
                gpu_id=gpu["uuid"],
                gpu_name=gpu["name"],
                vram_gb=_total_gb(gpu),
                cloud=LOCAL_CLOUD,
                data_center_ids=[],
                price_per_hr=0.0,
                api_token_enc=enc,
                pending_parse=parse,
                created_by=principal.user_id,
                now_ms=self._c.clock.now_ms(),
            )

    async def _finish_failed(self, deployment_id: str, error: str) -> None:
        assert self._c.sessionmaker is not None  # noqa: S101
        now = self._c.clock.now_ms()
        async with transaction(self._c.sessionmaker) as session:
            await pods_repo.update_fields(
                session,
                deployment_id,
                now_ms=now,
                status="failed",
                error=error[:900],
                end_time=now,
            )


def _total_gb(gpu: dict[str, Any]) -> int:
    return round(int(gpu["memory_total_mb"]) / MIB_PER_GB)


def _is_free(gpu: dict[str, Any], hosted: HostedModel) -> bool:
    return int(gpu["memory_free_mb"]) >= hosted.min_vram_gb * MIB_PER_GB


def _gpu_view(gpu: dict[str, Any], hosted: HostedModel) -> dict[str, Any]:
    return {
        "id": gpu["uuid"],
        "index": gpu["index"],
        "name": gpu["name"],
        "vram_gb": _total_gb(gpu),
        "memory_total_mb": gpu["memory_total_mb"],
        "memory_free_mb": gpu["memory_free_mb"],
        "memory_used_mb": gpu["memory_used_mb"],
        "utilization_pct": gpu["utilization_pct"],
        "free": _is_free(gpu, hosted),
    }
