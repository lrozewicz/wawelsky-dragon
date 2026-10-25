"""Usługa resetu stanu testowego (K9 §3): baza, storage, limiter, modele, admin, klucz API.

``Container`` importowany wyłącznie pod ``TYPE_CHECKING`` — unika cyklu importów
(wzór: ``app/core/container.py``, ``app/services/ingest.py``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import maintenance as maintenance_repo
from app.db.repositories import models as models_repo
from app.db.uow import transaction
from app.domain.policy import Principal
from app.integrations.sharepoint.auth import clear_token_cache
from app.services.api_keys import ApiKeyService
from app.services.users import UserRow, UserService
from app.storage.keys import StorageKey

if TYPE_CHECKING:
    from app.core.container import Container

# (name, model_type, is_default, dimension) — K9 §3 p. 4; base_url/api_key_enc zostają NULL.
# `fake-chat-strict` po `fake-chat-think` (poprawka K9 2026-10-04).
TEST_MODELS: tuple[tuple[str, str, bool, int | None], ...] = (
    ("fake-chat", "chat", True, None),
    ("fake-chat-think", "chat", False, None),
    ("fake-chat-strict", "chat", False, None),
    ("fake-embed-1024", "embedding", True, 1024),
    ("fake-rerank", "rerank", True, None),
    ("fake-vision", "image2text", True, None),
)

# Prefiksy storage czyszczone resetem (K5 §1.2); tmp/ bez zmian.
_STORAGE_PREFIXES = ("files", "images", "filemanager")


class ResetService:
    """Jedno wywołanie ``reset`` = jeden pełny reset stanu testowego (K9 §3)."""

    def __init__(self, container: Container) -> None:
        self._container = container

    async def reset(self, *, admin_email: str, admin_password: str) -> dict[str, object]:
        """Czyści bazę, storage i limiter, zasiewa modele, admina i jego klucz (K9 §4)."""
        container = self._container
        sessionmaker = cast(async_sessionmaker[AsyncSession], container.sessionmaker)
        storage = container.storage
        # (1) Baza: DELETE FROM każdej tabeli poza alembic_version w jednej transakcji.
        async with transaction(sessionmaker) as session:
            await maintenance_repo.wipe_all(session)
        # (2) Storage: prefiksy files/images/filemanager.
        for prefix in _STORAGE_PREFIXES:
            await storage.delete_prefix(StorageKey(prefix))
        # (3) Cache w pamięci procesu: tokeny Graph (limiter logowania żyje w tabeli
        # `login_attempts`, czyszczonej przez wipe_all w kroku (1)).
        clear_token_cache()
        # (4) Modele: 6 wierszy z K9 §3 p. 4; dimension tylko gdy niepusty.
        now_ms = container.clock.now_ms()
        id_gen = container.id_gen
        async with transaction(sessionmaker) as session:
            for name, model_type, is_default, dimension in TEST_MODELS:
                model_id = id_gen.new_id()
                await models_repo.insert(
                    session,
                    id=model_id,
                    name=name,
                    model_type=model_type,
                    is_default=is_default,
                    now_ms=now_ms,
                )
                if dimension is not None:
                    await models_repo.set_dimension_if_null(session, model_id, dimension, now_ms)
        # (5) Admin: konto aktywne, is_superuser=1.
        users = cast(UserService, container.users)
        await users.ensure_admin(admin_email, admin_password)
        # Konto istnieje — ensure_admin je utworzył albo znajdował się już w bazie.
        user = cast(UserRow, await users.get_by_email(admin_email))
        # (6) Klucz API admina — ta sama ścieżka co POST /api/v1/system/tokens (K9 §3 p. 6).
        view = await cast(ApiKeyService, container.api_keys).create(
            Principal(
                user_id=user.id,
                email=user.email,
                is_superuser=True,
                is_service=False,
                auth_kind="jwt",
            )
        )
        return {
            "admin_email": admin_email,
            "admin_user_id": user.id,
            "api_key": view.token,
            # Domyślne modele per typ — pierwsze is_default w TEST_MODELS (K9 §4).
            "models": {t: n for n, t, is_default, _ in TEST_MODELS if is_default},
        }
