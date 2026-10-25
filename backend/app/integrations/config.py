"""Parametry integracji (K12 §5, kontrakt C3) — z ``WD_INTEGRATIONS_*`` przez ``from_settings``.

Pola ``Settings`` dodane w E4-1c; wartości stałe (heartbeat, kadencja flushy) zostają
w dataclassie bez odpowiednika w env.
"""

from dataclasses import dataclass

from app.core.config import Settings


@dataclass(frozen=True)
class IntegrationsConfig:
    tick_seconds: int = 30
    stale_lock_minutes: int = 15
    heartbeat_seconds: int = 60
    wait_timeout_seconds: int = 600
    cancel_wait_seconds: int = 10
    events_retention_days: int = 90
    events_flush_every: int = 50
    events_flush_seconds: float = 2.0
    purge_excluded_containers: bool = False
    enabled: bool = True
    delete_docs_on_integration_delete: bool = False
    link_cache_ttl_seconds: int = 3600

    @classmethod
    def from_settings(cls, settings: Settings) -> "IntegrationsConfig":
        """Mapowanie 1:1 z pól ``Settings`` (kontrakt E4-1c); stałe bez zmian."""
        return cls(
            tick_seconds=settings.integrations_tick_seconds,
            stale_lock_minutes=settings.integrations_stale_lock_minutes,
            wait_timeout_seconds=settings.integrations_wait_timeout,
            cancel_wait_seconds=settings.integrations_cancel_wait,
            events_retention_days=settings.integrations_events_retention_days,
            purge_excluded_containers=settings.sp_purge_excluded_containers,
            enabled=settings.integrations_enabled,
            delete_docs_on_integration_delete=settings.sp_delete_docs_on_integration_delete,
            link_cache_ttl_seconds=settings.sp_link_cache_ttl_seconds,
        )
