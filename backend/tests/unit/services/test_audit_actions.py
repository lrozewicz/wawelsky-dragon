"""Zbiór akcji audytu zawiera akcje integracji i paczki KB (E7-1a; kontrakt E4-3a §1)."""

import pytest

from app.services.audit import AUDIT_ACTIONS

INTEGRATION_ACTIONS = [
    "integration_created",
    "integration_updated",
    "integration_deleted",
    "integration_sync_requested",
    "integration_cancelled",
]

# Akcje eksportu/importu bazy wiedzy (E7-1a/E7-1b, K19 §3 Uprawnienia).
KB_PACKAGE_ACTIONS = [
    "dataset_exported",
    "dataset_imported",
]


@pytest.mark.parametrize("action", INTEGRATION_ACTIONS)
def test_integration_action_is_allowed(action: str) -> None:
    assert action in AUDIT_ACTIONS


@pytest.mark.parametrize("action", KB_PACKAGE_ACTIONS)
def test_kb_package_action_is_allowed(action: str) -> None:
    assert action in AUDIT_ACTIONS
