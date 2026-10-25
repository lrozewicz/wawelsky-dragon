"""Fixture'y harnessu samotestu (K11 §5): wd_server (session), replay i compare_dir."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from tests.contract.ragflow import compare
from tests.contract.ragflow.compare import Diff
from tests.contract.ragflow.harness import (
    SCENARIOS_DIR,
    WdServer,
    load_runner,
    sorted_parse_body,
    start_server,
    v024_auth_headers,
)


@pytest.fixture(scope="session")
def wd_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[WdServer]:
    """Stos WD (api+worker) na świeżej bazie — jeden na sesję pytest."""
    tmp = tmp_path_factory.mktemp("wd_server")
    with start_server(tmp) as server:
        yield server


@pytest.fixture
def replay(
    wd_server: WdServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[..., Path]:
    """Zwraca `replay(scenario, version="v0.27.2", scenarios_dir=SCENARIOS_DIR) -> Path`.

    Reset przed każdym scenariuszem (K9) i sesja z kluczami/JWT admina oraz drugiego
    użytkownika (`auth: jwt|second|second_jwt`), podmiana `runner._parse_body` na sortującą,
    wynik runnera w `<tmp>/actual` — funkcja zwraca `<tmp>/actual/<version>`.
    Dla `version="v0.24.0"` dodatkowo opakowuje `runner.auth_headers` tak, by każde żądanie
    niosło `X-RAGFlow-Compat: 0.24` (K11 §10d p. 15).
    """

    def replay(
        scenario: str, version: str = "v0.27.2", scenarios_dir: Path = SCENARIOS_DIR
    ) -> Path:
        runner = load_runner()
        session = wd_server.reset_session()
        monkeypatch.setattr(runner, "_parse_body", sorted_parse_body)
        if version == "v0.24.0":
            monkeypatch.setattr(runner, "auth_headers", v024_auth_headers(runner.auth_headers))
        out = tmp_path / "actual"
        try:
            runner.run_scenario(
                session,
                runner.load_scenario(scenarios_dir / f"{scenario}.yaml"),
                version,
                out,
            )
        except Exception as err:
            raise AssertionError(f"{err}\n{wd_server.logs()}") from err
        return out / version

    return replay


@pytest.fixture
def compare_dir() -> Callable[..., list[Diff]]:
    """Re-eksport `compare.compare_dir`: actual vs złoto dla scenariusza (K11 §5 p. 4)."""
    return compare.compare_dir
