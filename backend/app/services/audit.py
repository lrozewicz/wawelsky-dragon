"""Usługa dziennika audytu: jeden wpis na mutację, własna transakcja (kontrakt C3)."""

import json
from collections.abc import Mapping

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.timeutil import Clock
from app.db.repositories import audit_log as audit_repo
from app.db.repositories.audit_log import AuditRow
from app.db.uow import transaction

__all__ = [
    "AUDIT_ACTIONS",
    "AuditRow",  # re-eksport z app.db dla app.api (DEC-075, import-linter api-no-db)
    "AuditService",
]

# Zamknięty zbiór akcji audytu (C3 + WP E4-3a §1 + K13 §2); akcja spoza zbioru → ValueError.
AUDIT_ACTIONS: frozenset[str] = frozenset(
    {
        "dataset_exported",
        "integration_cancelled",
        "integration_created",
        "integration_deleted",
        "integration_sync_requested",
        "integration_updated",
        "user_created",
        "user_updated",
        "user_password_set",
        "user_activated",
        "user_deactivated",
        "user_deleted",
        "api_key_created",
        "api_key_deleted",
        "access_replaced",
        "access_granted",
        "access_revoked",
        "provider_instance_created",
        "provider_instance_updated",
        "provider_instance_deleted",
        "model_added",
        "model_updated",
        "model_deleted",
        "dataset_imported",
    }
)

_TARGET_ID_MAX = 64
_IP_MAX = 45


class AuditService:
    """Zapis wpisów audytu; nigdy nie przyjmuje haseł ani tokenów w `details` (C3)."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
        clock: Clock,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings
        self._clock = clock

    async def record(  # noqa: PLR0913 — sygnatura z kontraktu C3
        self,
        *,
        actor_label: str,
        action: str,
        target_type: str,
        target_id: str,
        details: Mapping[str, object] | None = None,
        actor_id: str | None = None,
        ip: str | None = None,
    ) -> None:
        """Dopisuje wpis audytu; `target_id` obcinany do 64, `ip` do 45 znaków."""
        if action not in AUDIT_ACTIONS:
            raise ValueError(f"Unknown audit action: {action}")
        details_json = json.dumps(details, ensure_ascii=False) if details is not None else None
        async with transaction(self._sessionmaker) as session:
            await audit_repo.insert(
                session,
                ts=self._clock.now_ms(),
                actor_id=actor_id,
                actor_label=actor_label,
                action=action,
                target_type=target_type,
                target_id=target_id[:_TARGET_ID_MAX],
                details_json=details_json,
                ip=ip[:_IP_MAX] if ip is not None else None,
            )

    async def list_page(  # noqa: PLR0913 — sygnatura z kontraktu E3-6a §4
        self,
        *,
        actor: str | None = None,
        action: str | None = None,
        from_ms: int | None = None,
        to_ms: int | None = None,
        limit: int,
        offset: int,
    ) -> tuple[list[AuditRow], int]:
        """Strona wpisów audytu malejąco po `id` i łączna liczba pasujących (E3-6a §4)."""
        async with transaction(self._sessionmaker) as session:
            return await audit_repo.list_page(
                session,
                actor=actor,
                action=action,
                from_ms=from_ms,
                to_ms=to_ms,
                limit=limit,
                offset=offset,
            )
