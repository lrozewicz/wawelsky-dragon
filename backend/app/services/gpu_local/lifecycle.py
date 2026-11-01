"""Cykl życia modelu na GPU serwera: etapy startu, gotowość, kasowanie po bezczynności.

Te same stany i wiersze co RunPod (``runpod_pods``, ``cloud = LOCAL``), a zamiast API RunPod
``gpu-agent``. Bez bezpiecznika czasu życia: GPU serwera nie nalicza kosztów za godzinę.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.db.repositories import runpod_pods as pods_repo
from app.db.repositories.runpod_pods import PodRow
from app.db.uow import transaction
from app.services.gpu_local.client import GpuAgentClient, local_client
from app.services.runpod.hosted import LOCAL_CLOUD, PORT, PROVIDER_LOCAL, get_model, models_for
from app.services.runpod.lifecycle import (
    HTTP_OK,
    REQUEST_TIMEOUT_S,
    become_ready,
    health_status,
    terminate_row,
    update_row,
    while_ready,
)
from app.services.runpod.registry import ensure_registered

if TYPE_CHECKING:
    from app.core.container import Container

logger = logging.getLogger("app.gpu_local")

_IN_PROGRESS = {"pulling", "creating"}


def container_url(name: str) -> str:
    """Adres vLLM w sieci stosu (nazwa kontenera rozwiązywana przez DNS Dockera)."""
    return f"http://{name}:{PORT}/v1"


async def register_local_models(container: Container) -> None:
    """Przy skonfigurowanym agencie modele są w rejestrze, więc można wybrać je jako parser."""
    if not container.settings.gpu_agent_url:
        return
    for model in models_for(PROVIDER_LOCAL):
        await ensure_registered(container, model, base_url=None, api_token=None, created_by=None)


async def advance(  # noqa: PLR0911 — automat stanów: każdy stan końcowy to osobny return
    container: Container, row: PodRow, client: GpuAgentClient
) -> None:
    """Jeden idempotentny krok automatu dla wdrożenia lokalnego."""
    model = get_model(row.model_name)
    now = container.clock.now_ms()
    age_s = (now - row.create_time) / 1000
    if row.status == "terminating":
        await terminate_row(container, client, row, status="terminated", error=row.error)
        return
    if row.status == "requested":
        if age_s > REQUEST_TIMEOUT_S:
            await update_row(container, row, status="failed", error="deployment request was lost")
        return
    if model is None or row.pod_id is None:
        await terminate_row(container, client, row, status="failed", error="unknown model or pod")
        return
    info = await client.get_pod(row.pod_id)
    state = str(info.get("state", "")) if info else "missing"
    if state not in _IN_PROGRESS and state != "running":
        detail = (info or {}).get("error") or state
        reason = f"container ended unexpectedly ({detail})"
        await terminate_row(container, client, row, status="failed", error=reason[:900])
        return
    if row.status == "ready":
        await while_ready(container, client, row, model, now)
        return
    if age_s > model.startup_timeout_s:
        await terminate_row(
            container, client, row, status="failed", error="model did not start in time"
        )
        return
    if state in _IN_PROGRESS:
        await update_row(container, row, status="starting")
        return
    base_url = container_url(row.pod_id)
    fields: dict[str, Any] = {"base_url": base_url}
    if await health_status(base_url) == HTTP_OK:
        await update_row(container, row, **fields)
        await become_ready(container, _with_url(row, base_url), model)
        return
    await update_row(container, row, status="loading", **fields)


def _with_url(row: PodRow, base_url: str) -> PodRow:
    from dataclasses import replace  # noqa: PLC0415

    return replace(row, base_url=base_url)


async def tick_local(container: Container) -> int:
    """Przebieg dla aktywnych wdrożeń lokalnych; awaria agenta nie zmienia ich stanu."""
    assert container.sessionmaker is not None  # noqa: S101
    async with transaction(container.sessionmaker) as session:
        rows = [r for r in await pods_repo.list_active(session) if r.cloud == LOCAL_CLOUD]
    if not rows:
        return 0
    client = local_client(container)
    for row in rows:
        try:
            await advance(container, row, client)
        except Exception:
            logger.exception("local gpu tick failed", extra={"deployment": row.id})
    return len(rows)
