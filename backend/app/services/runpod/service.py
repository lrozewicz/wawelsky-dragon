"""Usługa RunPod dla API: klucz, katalog GPU, preflight parsowania, wdrożenia i ich kasowanie.

Wszystkie operacje kosztowe (zapis klucza, wdrożenie, kasowanie) wymagają superusera. Sam odczyt
stanu (preflight, lista wdrożeń) jest dostępny dla każdego, kto ma prawo do datasetu.
"""

from __future__ import annotations

import secrets
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

import httpx

from app.core.crypto import encrypt
from app.core.errors import Conflict, NotFound, UpstreamError, ValidationFailed, WDError
from app.db.repositories import documents as documents_repo
from app.db.repositories import runpod_pods as pods_repo
from app.db.repositories.runpod_pods import ACTIVE_STATUSES, PodRow
from app.db.uow import transaction
from app.domain.policy import Action, Principal
from app.services.datasets import DatasetService
from app.services.provider_common import require_superuser
from app.services.runpod import catalog as gpu_catalog
from app.services.runpod import keystore
from app.services.runpod.client import (
    RunpodAuthError,
    RunpodCapacityError,
    RunpodClient,
    RunpodError,
)
from app.services.runpod.hosted import HOSTED_MODELS, HostedModel, get_model, pod_body
from app.services.runpod.lifecycle import IDLE_GRACE_S, start_parse
from app.services.runpod.registry import ensure_registered

if TYPE_CHECKING:
    from app.core.container import Container

_ENDED = ("terminated", "failed")


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


class RunpodService:
    """Operacje panelu RunPod (stan w ``runpod_pods`` i ``wd_settings``)."""

    def __init__(self, container: Container, *, http: httpx.AsyncClient | None = None) -> None:
        self._c = container
        # ``container.runpod_http``: klient wstrzykiwany w testach (``httpx.MockTransport``).
        self._http = http or getattr(container, "runpod_http", None)

    # --- klucz API ---------------------------------------------------------------------------

    async def key_status(self) -> dict[str, Any]:
        """Czy klucz jest zapisany i jego końcówka (nigdy cały klucz)."""
        key = await keystore.load_key(self._c)
        return {"configured": key is not None, "hint": f"…{key[-4:]}" if key else None}

    async def set_key(self, principal: Principal, api_key: str) -> dict[str, Any]:
        """Sprawdza klucz w RunPod i zapisuje go zaszyfrowanego."""
        require_superuser(principal)
        api_key = api_key.strip()
        if not api_key:
            raise ValidationFailed("api_key is required")
        try:
            await RunpodClient(api_key, client=self._http).verify()
        except RunpodAuthError as exc:
            raise ValidationFailed("RunPod rejected this API key") from exc
        except RunpodError as exc:
            raise UpstreamError(f"RunPod check failed: {exc.message}") from exc
        await keystore.save_key(self._c, api_key)
        # Model od razu trafia do rejestru, żeby dało się go wybrać jako parser jeszcze przed
        # pierwszym wdrożeniem (pod włączy dopiero pytanie przy starcie parsowania).
        for hosted in HOSTED_MODELS.values():
            await ensure_registered(
                self._c, hosted, base_url=None, api_token=None, created_by=principal.user_id
            )
        return await self.key_status()

    async def remove_key(self, principal: Principal) -> None:
        """Usuwa klucz; przy działających podach odmowa (nie dałoby się ich skasować)."""
        require_superuser(principal)
        if await self._active():
            raise Conflict("Terminate running RunPod pods before removing the API key")
        await keystore.delete_key(self._c)

    # --- katalog -----------------------------------------------------------------------------

    def hosted_models(self) -> list[dict[str, Any]]:
        """Modele, które można uruchomić na RunPod."""
        return [
            {
                "name": m.name,
                "title": m.title,
                "hf_model": m.hf_model,
                "min_vram_gb": m.min_vram_gb,
                "recommended_vram_gb": m.recommended_vram_gb,
            }
            for m in HOSTED_MODELS.values()
        ]

    async def catalog(  # noqa: PLR0913 — filtry panelu
        self,
        principal: Principal,
        *,
        model: str,
        cloud: str = "SECURE",
        min_vram: int | None = None,
        max_vram: int | None = None,
        region: str | None = None,
        country: str | None = None,
        only_available: bool = False,
    ) -> dict[str, Any]:
        """Lista GPU z cenami i dostępnością (filtry: VRAM, region, kraj) oraz regiony i kraje."""
        require_superuser(principal)
        hosted = self._hosted(model)
        gpus, centers = await self._gpus(cloud)
        floor = max(min_vram or 0, 1)
        shown = gpu_catalog.filter_gpus(
            gpus,
            min_vram=floor,
            max_vram=max_vram,
            region=region,
            country=country,
            only_available=only_available,
        )
        return {
            "model": hosted.name,
            "min_vram_gb": hosted.min_vram_gb,
            "gpus": [{**gpu_view(g), "fits": g.vram_gb >= hosted.min_vram_gb} for g in shown],
            "regions": sorted({dc.region for dc in centers.values() if dc.region != "UNKNOWN"}),
            "countries": sorted({dc.country for dc in centers.values() if dc.country}),
        }

    async def _gpus(
        self, cloud: str
    ) -> tuple[list[gpu_catalog.Gpu], dict[str, gpu_catalog.DataCenter]]:
        client = await keystore.client_for(self._c, http=self._http)
        try:
            raw_centers = await client.list_data_centers()
            centers = gpu_catalog.parse_data_centers(raw_centers)
            raw = await client.list_gpus(cloud=cloud)
        except RunpodAuthError as exc:
            raise ValidationFailed("RunPod rejected the stored API key") from exc
        except RunpodError as exc:
            raise UpstreamError(f"RunPod catalog failed: {exc.message}") from exc
        return gpu_catalog.parse_gpus(raw, centers, cloud=cloud), centers

    # --- preflight parsowania ----------------------------------------------------------------

    async def preflight(
        self, principal: Principal, dataset_id: str, document_ids: list[str]
    ) -> dict[str, Any]:
        """Czy parsowanie tych dokumentów wymaga poda RunPod, który jest teraz wyłączony."""
        await DatasetService(self._c).load(principal, dataset_id, Action.UPDATE)
        assert self._c.sessionmaker is not None  # noqa: S101
        async with transaction(self._c.sessionmaker) as session:
            docs = await documents_repo.get_many(session, document_ids)
        names = {str(d.parser_config.get("layout_recognize", "")) for d in docs}
        model = next((get_model(n) for n in sorted(names) if get_model(n)), None)
        if model is None:
            return {"needs_pod": False}
        async with transaction(self._c.sessionmaker) as session:
            active = [r for r in await pods_repo.list_active(session) if r.model_name == model.name]
            recent = await pods_repo.list_recent(session, 20)
        ready = next((r for r in active if r.status == "ready"), None)
        last = next((r for r in recent if r.model_name == model.name), None)
        return {
            "needs_pod": ready is None,
            "model": model.name,
            "title": model.title,
            "state": "ready" if ready else (active[0].status if active else "off"),
            "deployment_id": (ready or (active[0] if active else None)) and (ready or active[0]).id,
            "last_gpu": (
                {"id": last.gpu_id, "name": last.gpu_name, "vram_gb": last.vram_gb}
                if last
                else None
            ),
            "min_vram_gb": model.min_vram_gb,
        }

    # --- wdrożenia ---------------------------------------------------------------------------

    async def deploy(  # noqa: PLR0913 — parametry wdrożenia z panelu
        self,
        principal: Principal,
        *,
        model: str,
        gpu_id: str,
        cloud: str = "SECURE",
        region: str | None = None,
        country: str | None = None,
        parse: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Tworzy poda z modelem na wskazanym GPU; po gotowości WD samo uruchamia ``parse``."""
        require_superuser(principal)
        hosted = self._hosted(model)
        active = [r for r in await self._active() if r.model_name == hosted.name]
        if active:
            raise Conflict(
                f"{hosted.title} is already being deployed or running",
                details={"deployment_id": active[0].id},
            )
        gpus, _ = await self._gpus(cloud)
        chosen = next((g for g in gpus if g.id == gpu_id), None)
        if chosen is None:
            raise ValidationFailed(f"unknown GPU: {gpu_id}")
        if chosen.vram_gb < hosted.min_vram_gb:
            raise ValidationFailed(f"{hosted.title} needs at least {hosted.min_vram_gb} GB VRAM")
        centers = gpu_catalog.placement(chosen, region=region, country=country)
        if (region or country) and not centers:
            raise self._unavailable(chosen, gpus, region, country)
        if not chosen.available:
            raise self._unavailable(chosen, gpus, region, country)
        return await self._create(principal, hosted, chosen, gpus, cloud, centers, parse or [])

    async def _create(  # noqa: PLR0913, PLR0917
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
            raise self._unavailable(chosen, gpus, None, None) from exc
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
        return await self.get(deployment_id)

    def _unavailable(
        self,
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

    async def get(self, deployment_id: str) -> dict[str, Any]:
        """Widok wdrożenia (bez klucza vLLM)."""
        assert self._c.sessionmaker is not None  # noqa: S101
        async with transaction(self._c.sessionmaker) as session:
            row = await pods_repo.get(session, deployment_id)
        if row is None:
            raise NotFound(f"deployment not found: {deployment_id}")
        return self._view(row)

    async def list_deployments(self, limit: int = 20) -> list[dict[str, Any]]:
        """Ostatnie wdrożenia, najnowsze pierwsze."""
        assert self._c.sessionmaker is not None  # noqa: S101
        async with transaction(self._c.sessionmaker) as session:
            rows = await pods_repo.list_recent(session, limit)
        return [self._view(r) for r in rows]

    async def queue_parse(
        self, principal: Principal, deployment_id: str, dataset_id: str, document_ids: list[str]
    ) -> dict[str, Any]:
        """Dokłada dokumenty do parsowania: od razu (pod gotowy) albo po jego uruchomieniu."""
        require_superuser(principal)
        await DatasetService(self._c).load(principal, dataset_id, Action.UPDATE)
        assert self._c.sessionmaker is not None  # noqa: S101
        async with transaction(self._c.sessionmaker) as session:
            row = await pods_repo.get(session, deployment_id)
        if row is None:
            raise NotFound(f"deployment not found: {deployment_id}")
        item = {"dataset_id": dataset_id, "document_ids": document_ids}
        if row.status == "ready":
            await start_parse(self._c, [item])
        elif row.status in ACTIVE_STATUSES:
            async with transaction(self._c.sessionmaker) as session:
                await pods_repo.update_fields(
                    session,
                    deployment_id,
                    now_ms=self._c.clock.now_ms(),
                    pending_parse=[*row.pending_parse, item],
                )
        else:
            raise Conflict("The pod is no longer running; start it again")
        return await self.get(deployment_id)

    async def terminate(self, principal: Principal, deployment_id: str) -> dict[str, Any]:
        """Ręczne kasowanie poda (natychmiast; pozostałe zadania parsowania zakończą się błędem)."""
        require_superuser(principal)
        assert self._c.sessionmaker is not None  # noqa: S101
        async with transaction(self._c.sessionmaker) as session:
            row = await pods_repo.get(session, deployment_id)
        if row is None:
            raise NotFound(f"deployment not found: {deployment_id}")
        if row.status in _ENDED:
            return self._view(row)
        if row.pod_id:
            client = await keystore.client_for(self._c, http=self._http)
            try:
                await client.delete_pod(row.pod_id)
            except RunpodError as exc:
                raise UpstreamError(f"RunPod could not delete the pod: {exc.message}") from exc
        async with transaction(self._c.sessionmaker) as session:
            await pods_repo.update_fields(
                session,
                deployment_id,
                now_ms=self._c.clock.now_ms(),
                status="terminated",
                end_time=self._c.clock.now_ms(),
            )
        return await self.get(deployment_id)

    # --- pomocnicze --------------------------------------------------------------------------

    def _hosted(self, name: str) -> HostedModel:
        hosted = get_model(name)
        if hosted is None:
            raise ValidationFailed(f"model cannot be hosted on RunPod: {name}")
        return hosted

    async def _active(self) -> list[PodRow]:
        assert self._c.sessionmaker is not None  # noqa: S101
        async with transaction(self._c.sessionmaker) as session:
            return await pods_repo.list_active(session)

    def _view(self, row: PodRow) -> dict[str, Any]:
        now = self._c.clock.now_ms()
        end = row.end_time or now
        hours = max(end - row.create_time, 0) / 3_600_000
        return {
            "id": row.id,
            "model": row.model_name,
            "title": (get_model(row.model_name) or _UNKNOWN).title,
            "status": row.status,
            "active": row.status in ACTIVE_STATUSES,
            "gpu": {"id": row.gpu_id, "name": row.gpu_name, "vram_gb": row.vram_gb},
            "cloud": row.cloud,
            "data_center_id": row.data_center_id,
            "price_per_hr": row.price_per_hr,
            "cost_so_far": round(hours * row.price_per_hr, 3),
            "error": row.error,
            "pending_documents": sum(len(i.get("document_ids", [])) for i in row.pending_parse),
            "created_at": row.create_time,
            "ready_at": row.ready_time,
            "ended_at": row.end_time,
            "idle_shutdown_s": IDLE_GRACE_S,
        }


class _Unknown:
    title = "?"


_UNKNOWN = _Unknown()
__all__ = ["GpuUnavailable", "RunpodService", "WDError"]
