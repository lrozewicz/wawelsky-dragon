"""Testy `tools/check_compose.py` (H11/H12) — bieg przez verify-fast.

Test leży w backend/tests/unit (a nie w tools/tests), bo tylko ten katalog uruchamia
`./.claude/verify-fast.sh`; skrypt z tools/ ładujemy przez importlib.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "tools" / "check_compose.py"
COMPOSE = REPO_ROOT / "docker-compose.yml"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("tools_check_compose", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _LazyScript:
    """Skrypt z tools/ ładowany przy pierwszym użyciu atrybutu — obraz test-ocr nie ma /tools."""

    def __init__(self) -> None:
        self._module: ModuleType | None = None

    def __getattr__(self, attribute: str) -> object:
        if self._module is None:
            self._module = _load_script()
        return getattr(self._module, attribute)


check_compose = _LazyScript()


def _repo_document() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def _write_copy(tmp_path: Path, document: dict) -> Path:
    target = tmp_path / "docker-compose.yml"
    target.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return target


def test_repo_compose_has_no_violations() -> None:
    """Po naprawach (fake-llm z user) repozytoryjny docker-compose.yml jest czysty."""
    assert check_compose.collect_violations(COMPOSE) == []


def test_docker_sock_mount_is_h11(tmp_path: Path) -> None:
    document = _repo_document()
    document["services"]["api"]["volumes"].append("/var/run/docker.sock:/var/run/docker.sock")
    violations = check_compose.collect_violations(_write_copy(tmp_path, document))
    assert any(v.startswith("H11:") for v in violations)


def test_privileged_is_h11(tmp_path: Path) -> None:
    document = _repo_document()
    document["services"]["api"]["privileged"] = True
    violations = check_compose.collect_violations(_write_copy(tmp_path, document))
    assert any("privileged" in v for v in violations)


def test_web_without_read_only_is_h11(tmp_path: Path) -> None:
    document = _repo_document()
    del document["services"]["web"]["read_only"]
    violations = check_compose.collect_violations(_write_copy(tmp_path, document))
    assert any("read_only" in v for v in violations)


def test_service_without_user_is_h11(tmp_path: Path) -> None:
    document = _repo_document()
    del document["services"]["fake-llm"]["user"]
    violations = check_compose.collect_violations(_write_copy(tmp_path, document))
    assert any("non-root" in v for v in violations)


def test_secret_with_nonempty_default_is_h12(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    document = _repo_document()
    env = document["services"]["api"]["environment"]
    env["WD_DB_PASSWORD"] = "${WD_X_PASSWORD:-haslo}"  # noqa: S105 — atrapa hasła
    path = _write_copy(tmp_path, document)
    assert check_compose.main([str(path)]) == 1
    assert "H12:" in capsys.readouterr().err


def test_secret_literal_is_h12(tmp_path: Path) -> None:
    document = _repo_document()
    env = document["services"]["mariadb"]["environment"]
    env["MARIADB_ROOT_PASSWORD"] = "tajne"  # noqa: S105 — atrapa hasła
    violations = check_compose.collect_violations(_write_copy(tmp_path, document))
    assert any(v.startswith("H12:") for v in violations)
