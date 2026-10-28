"""Rejestracja modelu z RunPod w rejestrze WD (instancja ``runpod-<model>`` + model ``<model>``).

Instancja i model powstają przy pierwszym wdrożeniu i zostają po skasowaniu poda: dzięki temu
konfiguracja datasetu (``layout_recognize`` = nazwa modelu) pozostaje poprawna. Przy każdym
wdrożeniu aktualizujemy ``base_url`` (adres proxy zawiera id poda) i klucz vLLM.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import models as models_repo
from app.db.repositories import provider_instances as instances_repo
from app.db.uow import transaction
from app.services.provider_common import PROVIDER_COLUMN, encrypt_key
from app.services.runpod.hosted import HostedModel

if TYPE_CHECKING:
    from app.core.container import Container

# Adres do czasu pierwszego startu poda; nigdy nie jest używany (guard workera sprawdza stan poda).
PLACEHOLDER_URL = "https://runpod.invalid/v1"


async def ensure_registered(
    container: Container,
    model: HostedModel,
    *,
    base_url: str | None,
    api_token: str | None,
    created_by: str | None,
) -> None:
    """Zakłada instancję i model, jeśli ich brak; ustawia ``base_url`` i klucz (gdy podane)."""
    sessionmaker = container.sessionmaker
    assert sessionmaker is not None  # noqa: S101 — kontener po start()
    now_ms = container.clock.now_ms()
    async with transaction(sessionmaker) as session:
        instance = await instances_repo.get_by_name(session, PROVIDER_COLUMN, model.instance_name)
        if instance is None:
            instance_id = container.id_gen.new_id()
            await instances_repo.insert(
                session,
                id=instance_id,
                provider=PROVIDER_COLUMN,
                name=model.instance_name,
                base_url=base_url or PLACEHOLDER_URL,
                api_key_enc=_enc(container, instance_id, api_token),
                created_by=created_by,
                now_ms=now_ms,
            )
        else:
            instance_id = instance.id
            if base_url is not None:
                await instances_repo.update(
                    session,
                    instance_id=instance_id,
                    name=instance.name,
                    base_url=base_url,
                    api_key_enc=_enc(container, instance_id, api_token),
                    set_key=api_token is not None,
                    now_ms=now_ms,
                )
        await _ensure_model(container, session, model, instance_id, created_by, now_ms)


def _enc(container: Container, instance_id: str, token: str | None) -> bytes | None:
    return encrypt_key(container.settings, instance_id, token) if token is not None else None


async def _ensure_model(  # noqa: PLR0913, PLR0917 — kontekst transakcji
    container: Container,
    session: AsyncSession,
    model: HostedModel,
    instance_id: str,
    created_by: str | None,
    now_ms: int,
) -> None:
    existing = await models_repo.get_by_name(session, model.name, model.model_type)
    if existing is not None:
        return
    await models_repo.insert_for_instance(
        session,
        id=container.id_gen.new_id(),
        name=model.name,
        model_type=model.model_type,
        instance_id=instance_id,
        max_tokens=model.max_model_len,
        dimension=None,
        extra=model.registry_extra(),
        created_by=created_by,
        now_ms=now_ms,
    )
