"""Tworzenie poda w RunPod: wiersz wdrożenia, rejestracja modelu w WD i wywołanie ``POST /pods``.

Wydzielone z ``RunpodService`` (limit rozmiaru pliku). Nie zna konkretnych modeli: wszystko, co
potrzebne do uruchomienia, bierze z ``HostedModel``.
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from app.core.crypto import encrypt
from app.core.errors import Conflict, UpstreamError
from app.db.repositories import runpod_pods as pods_repo
from app.db.uow import transaction
from app.domain.policy import Principal
from app.services.runpod import catalog as gpu_catalog
from app.services.runpod import keystore
from app.services.runpod.client import HttpClient, RunpodCapacityError, RunpodError
from app.services.runpod.hosted import HostedModel, pod_body
from app.services.runpod.lifecycle import PANEL_ORIGIN, PARSE_ORIGIN
from app.services.runpod.registry import ensure_registered

if TYPE_CHECKING:
    from app.core.container import Container


class GpuUnavailable(Conflict):
    """Brak wolnych maszyn dla GPU; ``details.alternatives`` = zamienniki o VRAM ≥ wybranego."""

    slug = "gpu_unavailable"


def gpu_view(gpu: gpu_catalog.Gpu) -> dict[str, Any]:
    """GPU do JSON-a panelu."""
    return {
        "id": gpu.id,
        "name": gpu.name,
        "vram_gb": gpu.vram_gb,
        "price_per_hr": gpu.price_per_hr,
        "availability": gpu.availability,
        "data_centers": [asdict(dc) for dc in gpu.data_centers],
    }


def unavailable(
    chosen: gpu_catalog.Gpu,
    gpus: list[gpu_catalog.Gpu],
    region: str | None,
    country: str | None,
) -> GpuUnavailable:
    pool = gpu_catalog.filter_gpus(gpus, only_available=True, region=region, country=country)
    alts = gpu_catalog.alternatives(pool, chosen) or gpu_catalog.alternatives(
        gpu_catalog.filter_gpus(gpus, only_available=True), chosen
    )
    return GpuUnavailable(
        f"{chosen.name} is not available right now",
        details={"alternatives": [gpu_view(g) for g in alts]},
    )


class PodDeployer:
    """Zakłada wdrożenie i poda (stan dalej prowadzi ``lifecycle``)."""

    def __init__(
        self,
        container: Container,
        http: HttpClient | None,
        get: Callable[[str], Awaitable[dict[str, Any]]],
    ) -> None:
        self._c = container
        self._http = http
        self._get = get

    async def create(  # noqa: PLR0913, PLR0917
        self,
        principal: Principal,
        hosted: HostedModel,
        chosen: gpu_catalog.Gpu,
        gpus: list[gpu_catalog.Gpu],
        cloud: str,
        centers: list[str],
        parse: list[dict[str, Any]],
    ) -> dict[str, Any]:
        assert self._c.sessionmaker is not None  # noqa: S101
        deployment_id = self._c.id_gen.new_id()
        token = secrets.token_urlsafe(32)
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
                gpu_id=chosen.id,
                gpu_name=chosen.name,
                vram_gb=chosen.vram_gb,
                cloud=cloud,
                data_center_ids=centers,
                price_per_hr=chosen.price_per_hr,
                api_token_enc=enc,
                pending_parse=parse,
                created_by=principal.user_id,
                now_ms=self._c.clock.now_ms(),
            )
        await ensure_registered(
            self._c, hosted, base_url=None, api_token=None, created_by=principal.user_id
        )
        client = await keystore.client_for(self._c, http=self._http)
        body = pod_body(
            hosted,
            pod_name=deployment_id[:12],
            gpu_id=chosen.id,
            api_token=token,
            cloud=cloud,
            data_center_ids=centers,
        )
        try:
            pod = await client.create_pod(body)
        except RunpodCapacityError as exc:
            await self._fail(deployment_id, exc.message)
            raise unavailable(chosen, gpus, None, None) from exc
        except RunpodError as exc:
            await self._fail(deployment_id, exc.message)
            raise UpstreamError(f"RunPod could not create the pod: {exc.message}") from exc
        async with transaction(self._c.sessionmaker) as session:
            await pods_repo.update_fields(
                session,
                deployment_id,
                now_ms=self._c.clock.now_ms(),
                status="provisioning",
                pod_id=str(pod["id"]),
                price_per_hr=float(pod.get("cost") or chosen.price_per_hr),
            )
        return await self._get(deployment_id)

    async def _fail(self, deployment_id: str, error: str) -> None:
        assert self._c.sessionmaker is not None  # noqa: S101
        async with transaction(self._c.sessionmaker) as session:
            await pods_repo.update_fields(
                session,
                deployment_id,
                now_ms=self._c.clock.now_ms(),
                status="failed",
                error=error[:900],
                end_time=self._c.clock.now_ms(),
            )
