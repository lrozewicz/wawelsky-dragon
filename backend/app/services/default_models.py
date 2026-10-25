"""Domyślne modele instancji: GET/PATCH /users/me/models (kontrakt C10)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import ValidationFailed
from app.db.repositories import models as models_repo
from app.db.uow import transaction
from app.domain.policy import Action, Principal, ResourceRef, require
from app.llm.registry import ModelRegistry
from app.llm.types import ModelType

if TYPE_CHECKING:
    from app.core.container import Container

# Klucze body → typ modelu (C10); asr_id/tts_id zawsze "", pozostałe klucze ignorowane.
FIELD_TYPES: dict[str, ModelType] = {
    "llm_id": "chat",
    "embd_id": "embedding",
    "img2txt_id": "image2text",
    "rerank_id": "rerank",
}


class DefaultModelsService:
    """Odczyt i ustawianie globalnych modeli domyślnych instancji (C10)."""

    def __init__(self, container: Container) -> None:
        self._container = container

    async def get(self) -> dict[str, str]:
        """Nazwy domyślnych AKTYWNYCH modeli 4 typów; brak/nieaktywny → "" (C10)."""
        sessionmaker = cast(async_sessionmaker[AsyncSession], self._container.sessionmaker)
        result: dict[str, str] = {}
        async with transaction(sessionmaker) as session:
            for key, model_type in FIELD_TYPES.items():
                row = await models_repo.get_default(session, model_type)
                result[key] = row.name if row is not None and row.is_active else ""
        result["asr_id"] = ""
        result["tts_id"] = ""
        return result

    async def set(self, principal: Principal, body: Mapping[str, object]) -> dict[str, str]:
        """Ustawia globalny model domyślny danego typu; tylko superuser (C0 p. 2, C10).

        Najpierw policy, potem walidacja wszystkich obecnych kluczy (typ wartości,
        potem resolve) i dopiero na końcu jedna transakcja z set_default —
        błąd jednego pola nic nie zmienia.
        """
        require(principal, Action.MANAGE, ResourceRef(kind="model", owner_id=None))
        registry = cast(ModelRegistry, self._container.models)
        resolved: list[tuple[str, ModelType]] = []
        for key, model_type in FIELD_TYPES.items():
            if key not in body:
                continue
            value = body[key]
            if not isinstance(value, str) or not value:
                raise ValidationFailed(f"{key} must be a non-empty string")
            # Pre-check: `resolve` dla nieaktywnego modelu rzuca NotFound, a C4 chce 101 (DEC-257).
            row = await registry.find(value, model_type)
            if row is not None and not row.is_active:
                raise ValidationFailed(f"{key}: model '{value}' is inactive")
            ref = await registry.resolve(value, model_type)
            resolved.append((cast(str, ref.id), model_type))
        sessionmaker = cast(async_sessionmaker[AsyncSession], self._container.sessionmaker)
        async with transaction(sessionmaker) as session:
            for model_id, model_type in resolved:
                await models_repo.set_default(
                    session, model_id, model_type, self._container.clock.now_ms()
                )
        return await self.get()
