"""Test konfiguracji WD_PARSE_PROCESSES (brief T2 poz. 8, kontrakt C4)."""

from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from app.core.config import Settings

ENV_VALUE = 3  # WD_PARSE_PROCESSES nadpisany w teście


def test_parse_processes_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    """SC-E5-H8a-06 krok 2: pula konwersji z konfiguracji (kontrakt C4).

    Domyślnie `min(4, os.cpu_count() or 1)`, env `WD_PARSE_PROCESSES` nadpisuje, `0` odrzucone.
    """
    monkeypatch.delenv("WD_PARSE_PROCESSES", raising=False)
    assert Settings(env="test").parse_processes == min(4, os.cpu_count() or 1)

    monkeypatch.setenv("WD_PARSE_PROCESSES", str(ENV_VALUE))
    assert Settings(env="test").parse_processes == ENV_VALUE

    monkeypatch.setenv("WD_PARSE_PROCESSES", "0")
    with pytest.raises(ValidationError):
        Settings(env="test")


def test_parse_processes_empty_env_uses_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pusty `WD_PARSE_PROCESSES` (`${WD_PARSE_PROCESSES:-}`) → domyślna liczba procesów (C4)."""
    monkeypatch.setenv("WD_PARSE_PROCESSES", "")
    assert Settings(env="test").parse_processes == min(4, os.cpu_count() or 1)


def test_parse_processes_negative_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wartość ujemna nadal odrzucona (kontrakt C4: int ≥ 1)."""
    monkeypatch.setenv("WD_PARSE_PROCESSES", "-1")
    with pytest.raises(ValidationError):
        Settings(env="test")
