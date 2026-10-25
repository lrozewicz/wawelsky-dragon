"""Testy IntegrationsConfig i jego przepięcia na Settings (brief T1, kontrakt E4-1c)."""

import os

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.integrations.config import IntegrationsConfig

DEFAULT_TICK_SECONDS = 30
DEFAULT_STALE_LOCK_MINUTES = 15
DEFAULT_HEARTBEAT_SECONDS = 60
DEFAULT_WAIT_TIMEOUT_SECONDS = 600
DEFAULT_CANCEL_WAIT_SECONDS = 10
DEFAULT_EVENTS_RETENTION_DAYS = 90
DEFAULT_EVENTS_FLUSH_EVERY = 50
DEFAULT_EVENTS_FLUSH_SECONDS = 2.0
DEFAULT_LINK_CACHE_TTL_SECONDS = 3600

# Wartości nadpisane — każde pole inne niż domyślne, żeby złapać zamianę mapowań.
OVERRIDDEN_TICK_SECONDS = 7
OVERRIDDEN_STALE_LOCK_MINUTES = 3
OVERRIDDEN_WAIT_TIMEOUT = 44
OVERRIDDEN_CANCEL_WAIT = 1
OVERRIDDEN_EVENTS_RETENTION_DAYS = 11
OVERRIDDEN_LINK_CACHE_TTL_SECONDS = 61

# Wartości wstrzykiwane przez env w teście (2) — trzymane w stałych wobec PLR2004.
ENV_TICK_SECONDS = 5
ENV_STALE_LOCK_MINUTES = 4
ENV_WAIT_TIMEOUT = 42
ENV_CANCEL_WAIT = 2
ENV_EVENTS_RETENTION_DAYS = 7
ENV_LINK_CACHE_TTL_SECONDS = 60


@pytest.fixture(autouse=True)
def _clean_wd_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Izolacja od env procesu (verify.sh eksportuje WD_DB_* itd.)."""
    for name in [key for key in os.environ if key.startswith("WD_")]:
        monkeypatch.delenv(name, raising=False)


def test_settings_dev_defaults() -> None:
    """(1) Domyślne Settings(env="dev") = wartości z kontraktu."""
    settings = Settings(env="dev")
    assert settings.integrations_enabled is True
    assert settings.integrations_tick_seconds == DEFAULT_TICK_SECONDS
    assert settings.integrations_stale_lock_minutes == DEFAULT_STALE_LOCK_MINUTES
    assert settings.integrations_wait_timeout == DEFAULT_WAIT_TIMEOUT_SECONDS
    assert settings.integrations_cancel_wait == DEFAULT_CANCEL_WAIT_SECONDS
    assert settings.integrations_events_retention_days == DEFAULT_EVENTS_RETENTION_DAYS
    assert settings.sp_delete_docs_on_integration_delete is False
    assert settings.sp_purge_excluded_containers is False
    assert settings.sp_link_cache_ttl_seconds == DEFAULT_LINK_CACHE_TTL_SECONDS


def test_settings_reads_all_nine_fields_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """(2) Każde z 9 pól czytane z `WD_<POLE>`."""
    monkeypatch.setenv("WD_INTEGRATIONS_ENABLED", "false")
    monkeypatch.setenv("WD_INTEGRATIONS_TICK_SECONDS", str(ENV_TICK_SECONDS))
    monkeypatch.setenv("WD_INTEGRATIONS_STALE_LOCK_MINUTES", str(ENV_STALE_LOCK_MINUTES))
    monkeypatch.setenv("WD_INTEGRATIONS_WAIT_TIMEOUT", str(ENV_WAIT_TIMEOUT))
    monkeypatch.setenv("WD_INTEGRATIONS_CANCEL_WAIT", str(ENV_CANCEL_WAIT))
    monkeypatch.setenv("WD_INTEGRATIONS_EVENTS_RETENTION_DAYS", str(ENV_EVENTS_RETENTION_DAYS))
    monkeypatch.setenv("WD_SP_DELETE_DOCS_ON_INTEGRATION_DELETE", "true")
    monkeypatch.setenv("WD_SP_PURGE_EXCLUDED_CONTAINERS", "true")
    monkeypatch.setenv("WD_SP_LINK_CACHE_TTL_SECONDS", str(ENV_LINK_CACHE_TTL_SECONDS))
    settings = Settings(env="dev")
    assert settings.integrations_enabled is False
    assert settings.integrations_tick_seconds == ENV_TICK_SECONDS
    assert settings.integrations_stale_lock_minutes == ENV_STALE_LOCK_MINUTES
    assert settings.integrations_wait_timeout == ENV_WAIT_TIMEOUT
    assert settings.integrations_cancel_wait == ENV_CANCEL_WAIT
    assert settings.integrations_events_retention_days == ENV_EVENTS_RETENTION_DAYS
    assert settings.sp_delete_docs_on_integration_delete is True
    assert settings.sp_purge_excluded_containers is True
    assert settings.sp_link_cache_ttl_seconds == ENV_LINK_CACHE_TTL_SECONDS


def test_settings_tick_seconds_zero_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """(3) `WD_INTEGRATIONS_TICK_SECONDS=0` → ValidationError (ge=1)."""
    monkeypatch.setenv("WD_INTEGRATIONS_TICK_SECONDS", "0")
    with pytest.raises(ValidationError, match="integrations_tick_seconds"):
        Settings(env="dev")


def test_settings_cancel_wait_zero_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """(3) `WD_INTEGRATIONS_CANCEL_WAIT=0` przechodzi (ge=0)."""
    monkeypatch.setenv("WD_INTEGRATIONS_CANCEL_WAIT", "0")
    assert Settings(env="dev").integrations_cancel_wait == 0


def test_from_settings_maps_nine_fields() -> None:
    """(4) `from_settings` mapuje wszystkie 9 pól na pola IntegrationsConfig."""
    settings = Settings(
        env="dev",
        integrations_enabled=False,
        integrations_tick_seconds=OVERRIDDEN_TICK_SECONDS,
        integrations_stale_lock_minutes=OVERRIDDEN_STALE_LOCK_MINUTES,
        integrations_wait_timeout=OVERRIDDEN_WAIT_TIMEOUT,
        integrations_cancel_wait=OVERRIDDEN_CANCEL_WAIT,
        integrations_events_retention_days=OVERRIDDEN_EVENTS_RETENTION_DAYS,
        sp_delete_docs_on_integration_delete=True,
        sp_purge_excluded_containers=True,
        sp_link_cache_ttl_seconds=OVERRIDDEN_LINK_CACHE_TTL_SECONDS,
    )
    config = IntegrationsConfig.from_settings(settings)
    assert config.enabled is False
    assert config.tick_seconds == OVERRIDDEN_TICK_SECONDS
    assert config.stale_lock_minutes == OVERRIDDEN_STALE_LOCK_MINUTES
    assert config.wait_timeout_seconds == OVERRIDDEN_WAIT_TIMEOUT
    assert config.cancel_wait_seconds == OVERRIDDEN_CANCEL_WAIT
    assert config.events_retention_days == OVERRIDDEN_EVENTS_RETENTION_DAYS
    assert config.delete_docs_on_integration_delete is True
    assert config.purge_excluded_containers is True
    assert config.link_cache_ttl_seconds == OVERRIDDEN_LINK_CACHE_TTL_SECONDS
    # Stałe bez zmian — nie pochodzą z Settings (kontrakt E4-1c).
    assert config.heartbeat_seconds == DEFAULT_HEARTBEAT_SECONDS
    assert config.events_flush_every == DEFAULT_EVENTS_FLUSH_EVERY
    assert config.events_flush_seconds == DEFAULT_EVENTS_FLUSH_SECONDS


def test_integrations_config_defaults_unchanged() -> None:
    """(5) `IntegrationsConfig()` = dzisiejsze domyślne + 3 nowe pola z kontraktu."""
    config = IntegrationsConfig()
    assert config.tick_seconds == DEFAULT_TICK_SECONDS
    assert config.stale_lock_minutes == DEFAULT_STALE_LOCK_MINUTES
    assert config.heartbeat_seconds == DEFAULT_HEARTBEAT_SECONDS
    assert config.wait_timeout_seconds == DEFAULT_WAIT_TIMEOUT_SECONDS
    assert config.cancel_wait_seconds == DEFAULT_CANCEL_WAIT_SECONDS
    assert config.events_retention_days == DEFAULT_EVENTS_RETENTION_DAYS
    assert config.events_flush_every == DEFAULT_EVENTS_FLUSH_EVERY
    assert config.events_flush_seconds == DEFAULT_EVENTS_FLUSH_SECONDS
    assert config.purge_excluded_containers is False
    assert config.enabled is True
    assert config.delete_docs_on_integration_delete is False
    assert config.link_cache_ttl_seconds == DEFAULT_LINK_CACHE_TTL_SECONDS
