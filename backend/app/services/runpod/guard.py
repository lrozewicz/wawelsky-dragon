"""Straż parsowania: model hostowany na RunPod wymaga działającego poda w chwili konwersji."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.db.repositories import runpod_pods as pods_repo
from app.db.uow import transaction
from app.services.runpod.hosted import get_model
from app.worker.errors import PermanentError

if TYPE_CHECKING:
    from app.core.container import Container


async def ensure_pod_ready(container: Container, model_name: object) -> None:
    """Nic dla modeli spoza RunPod; dla hostowanych wymaga poda ``ready``, inaczej błąd zadania.

    Zadania z interfejsu przechodzą wcześniej przez preflight (pytanie „włączyć pod?”); ta straż
    łapie ścieżki w tle (upload z automatycznym parsowaniem, integracje) i wyścig z wyłączeniem.
    """
    model = get_model(model_name) if isinstance(model_name, str) else None
    if model is None:
        return
    assert container.sessionmaker is not None  # noqa: S101 — kontener po start()
    async with transaction(container.sessionmaker) as session:
        active = await pods_repo.list_active(session)
    if not any(row.model_name == model.name and row.status == "ready" for row in active):
        raise PermanentError(
            f"{model.title} is not running on RunPod. Start it (Settings → RunPod, or parse the "
            "document again and confirm) and retry."
        )
