"""Fixture'y testów GPU serwera: te same co RunPod plus adres agenta w ustawieniach."""

from __future__ import annotations

from tests.integration.runpod.conftest import (  # noqa: F401
    admin,
    container,
    fake,
    migrated_db,
    sm,
    user,
)
