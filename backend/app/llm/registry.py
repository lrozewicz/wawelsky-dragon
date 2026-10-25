"""Rejestr modeli LLM — resolve / seed_defaults / set_dimension (kontrakt C11, K5 §3.5)."""

import logging
import re
from typing import cast

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.crypto import decrypt
from app.core.errors import NotFound, OperationNotAllowed
from app.core.ids import IdGenerator
from app.core.timeutil import Clock
from app.db.repositories import models, provider_instances
from app.db.repositories.models import ModelRow
from app.db.repositories.provider_instances import InstanceRow
from app.db.uow import transaction
from app.llm.types import ModelRef, ModelType
from app.services.provider_common import decrypt_key

logger = logging.getLogger("app.llm")

_ID_32HEX = re.compile(r"[0-9a-f]{32}")

# (pole Settings, typ modelu) w kolejności zasiewu wg C11.
_SEEDS: tuple[tuple[str, ModelType], ...] = (
    ("llm_default_chat", "chat"),
    ("llm_default_embedding", "embedding"),
    ("llm_default_rerank", "rerank"),
    ("llm_default_vlm", "image2text"),
)


class ModelRegistry:
    """Rozwiązuje referencje RAGFlow na ModelRef i zasiewa domyślne modele."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
        clock: Clock,
        id_gen: IdGenerator,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings
        self._clock = clock
        self._id_gen = id_gen

    async def resolve(self, ref: str | None, model_type: ModelType) -> ModelRef:
        """Referencja (None/""/nazwa/id, sufiks `@fabryka` odcinany) → ModelRef (C11).

        K13 §0 p. 4: `base_url` i klucz z wiersza modelu, gdy nie-NULL (stan sprzed K13),
        inaczej z instancji wskazanej przez `row.instance_id`, inaczej `None`.
        """
        async with transaction(self._sessionmaker) as session:
            row = await self._find(session, ref, model_type)
            if row is None or not row.is_active:
                label = ref if ref else f"default {model_type}"
                raise NotFound(f"model not found: {label}")
            instance = await self._instance(session, row)
            base_url = row.base_url or (instance.base_url if instance is not None else None)
            api_key = self._row_key(row)
            if api_key is None and instance is not None and instance.api_key_enc is not None:
                api_key = SecretStr(decrypt_key(self._settings, instance.id, instance.api_key_enc))
            return ModelRef(
                id=row.id,
                name=row.name,
                model_type=cast(ModelType, row.model_type),  # ENUM w DDL = warianty ModelType
                base_url=base_url,
                api_key=api_key,
                dimension=row.dimension,
                max_tokens=row.max_tokens,
                extra=row.extra or {},
            )

    async def find(self, ref: str, model_type: ModelType) -> ModelRow | None:
        """Wiersz po referencji (semantyka `_find`, także nieaktywny); None gdy brak (C4/DEC-257).

        `resolve` dla nieaktywnego wiersza rzuca `NotFound`, więc do wykrycia nieaktywnego
        modelu (np. w `DefaultModelsService.set`) potrzebny jest odczyt bez tej bramki.
        """
        async with transaction(self._sessionmaker) as session:
            return await self._find(session, ref, model_type)

    async def _instance(self, session: AsyncSession, row: ModelRow) -> InstanceRow | None:
        """Instancja wiersza; ładowana tylko gdy wiersz nie ma własnego `base_url`/klucza."""
        if row.instance_id is None or (row.base_url is not None and row.api_key_enc is not None):
            return None
        return await provider_instances.get_by_id(session, row.instance_id)

    def _row_key(self, row: ModelRow) -> SecretStr | None:
        """Klucz z wiersza modelu (aad z C7 — bez AAD, stan sprzed K13)."""
        if row.api_key_enc is None:
            return None
        plain = decrypt(self._settings.crypto_key.get_secret_value(), row.api_key_enc)
        return SecretStr(plain.decode())

    async def _find(
        self, session: AsyncSession, ref: str | None, model_type: ModelType
    ) -> ModelRow | None:
        """None/"" → domyślny; id (32 hex) → po id z wymaganym typem; inaczej po nazwie."""
        if not ref:
            return await models.get_default(session, model_type)
        name = ref.split("@", 1)[0]
        if _ID_32HEX.fullmatch(name):
            row = await models.get_by_id(session, name)
            if row is not None and row.model_type != model_type:
                return None
            return row
        return await models.get_by_name(session, name, model_type)

    async def seed_defaults(self) -> int:
        """Idempotentny zasiew z WD_LLM_DEFAULT_*; zwraca liczbę wstawionych (C11)."""
        inserted = 0
        async with transaction(self._sessionmaker) as session:
            for attr, model_type in _SEEDS:
                name: str = getattr(self._settings, attr)
                if not name:
                    continue
                if await models.get_by_name(session, name, model_type) is not None:
                    # `model_name`, nie `name` — `name` jest atrybutem LogRecord (DEC-257).
                    logger.info(
                        "seed default model exists",
                        extra={
                            "event": "seed_default_model_exists",
                            "model_name": name,
                            "model_type": model_type,
                        },
                    )
                    continue
                await models.insert(
                    session,
                    id=self._id_gen.new_id(),
                    name=name,
                    model_type=model_type,
                    is_default=await models.get_default(session, model_type) is None,
                    now_ms=self._clock.now_ms(),
                )
                inserted += 1
        return inserted

    async def set_dimension(self, model_id: str, dim: int) -> None:
        """Ustawia dimension gdy NULL; niezgodny z zapisanym → OperationNotAllowed (C11)."""
        async with transaction(self._sessionmaker) as session:
            updated = await models.set_dimension_if_null(
                session, model_id, dim, self._clock.now_ms()
            )
            if updated == 1:
                return
            row = await models.get_by_id(session, model_id)
            if row is None:
                raise NotFound(f"model not found: {model_id}")
            if row.dimension == dim:
                return
            raise OperationNotAllowed(f"model dimension mismatch: {row.dimension} != {dim}")
