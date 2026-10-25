"""Test narzędzia migrate bez bazy (brief T2 p. 8)."""

import pytest

from app.tools import migrate


def test_alembic_ini_exists() -> None:
    assert migrate.ALEMBIC_INI.is_file()


def test_main_runs_upgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WD_ENV", "test")
    calls: list[tuple[object, object]] = []
    seeds: list[object] = []
    boots: list[object] = []

    def fake_upgrade(config: object, revision: object) -> None:
        calls.append((config, revision))

    async def fake_seed(settings: object) -> int:
        seeds.append(settings)
        return 0

    async def fake_bootstrap(settings: object) -> bool:
        boots.append(settings)
        return False

    monkeypatch.setattr(migrate.command, "upgrade", fake_upgrade)
    monkeypatch.setattr(migrate, "seed_models", fake_seed)
    monkeypatch.setattr(migrate, "bootstrap_admin", fake_bootstrap)
    assert migrate.main() == 0
    assert len(calls) == 1
    assert isinstance(calls[0][0], migrate.Config)
    assert calls[0][1] == "head"
    assert len(seeds) == 1
    assert len(boots) == 1
