"""Produkcyjny `docker-compose.yml` w kontekście stosu clean-install (WP E5-H1, kontrakt T1).

Test uruchamia `docker compose config --format json` na tymczasowym pliku env (sekrety z
`scripts/gen-secrets.sh` + dane admina i bramki) i sprawdza, co realnie trafia do kontenerów
`migrate`/`api`/`worker`. Brak `docker compose` to błąd testu (nie skip) — kontrakt T1.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE = REPO_ROOT / "docker-compose.yml"
GEN_SECRETS = REPO_ROOT / "scripts" / "gen-secrets.sh"

ADMIN_EMAIL = "admin@compose-test.test"
ADMIN_PASSWORD = "compose-test-password"  # noqa: S105 — atrapa hasła w pliku env testu
EMBEDDING_MODEL = "fake-embed-1024"

BASE_ENV_LINES = (
    f"WD_ADMIN_EMAIL={ADMIN_EMAIL}",
    f"WD_ADMIN_PASSWORD={ADMIN_PASSWORD}",
    "WD_LLM_BASE_URL=http://x/v1",
    "WD_LLM_API_KEY=x",
    f"WD_LLM_DEFAULT_EMBEDDING={EMBEDDING_MODEL}",
)


def _env_file(tmp_path: Path, *extra: str) -> Path:
    """Świeży `.env` z `scripts/gen-secrets.sh` + dopisane zmienne stosu clean-install."""
    target = tmp_path / ".env"
    subprocess.run(  # noqa: S603 - stałe argumenty, bez shell
        ["bash", str(GEN_SECRETS), str(target)],  # noqa: S607 - bash ze ścieżki systemowej
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    with target.open("a", encoding="utf-8") as handle:
        for line in (*BASE_ENV_LINES, *extra):
            handle.write(line + "\n")
    return target


def _compose_config(env_file: Path) -> dict:
    command = [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "-f",
        str(COMPOSE),
        "config",
        "--format",
        "json",
    ]
    # `tools/dev/up.sh test env` eksportuje WD_* do powłoki, a zmienne powłoki mają pierwszeństwo
    # przed --env-file; usuwamy je, żeby test badał właśnie plik env.
    env = {key: value for key, value in os.environ.items() if not key.startswith("WD_")}
    try:
        completed = subprocess.run(  # noqa: S603 - stałe argumenty, bez shell
            command,
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as error:
        pytest.fail(f"brak `docker compose` (wymagane przez kontrakt T1): {error}")
    if completed.returncode != 0:
        pytest.fail(
            "`docker compose config` zakończyło się kodem "
            f"{completed.returncode}: {completed.stderr}"
        )
    return json.loads(completed.stdout)


def _environment(document: dict, service: str) -> dict:
    return document["services"][service]["environment"]


def _memory_bytes(document: dict) -> int:
    memory = document["services"]["worker"]["deploy"]["resources"]["limits"]["memory"]
    # `config --format json` zwraca limit raz jako liczbę bajtów, raz jako string (wersje compose).
    if isinstance(memory, str) and memory.isdigit():
        return int(memory)
    if isinstance(memory, int) and not isinstance(memory, bool):
        return memory
    raise AssertionError(f"nieoczekiwany format limitu pamięci: {memory!r}")


def test_migrate_gets_admin_credentials(tmp_path: Path) -> None:
    environment = _environment(_compose_config(_env_file(tmp_path)), "migrate")
    assert environment["WD_ADMIN_EMAIL"] == ADMIN_EMAIL
    assert environment["WD_ADMIN_PASSWORD"] == ADMIN_PASSWORD


def test_api_and_worker_do_not_get_admin_credentials(tmp_path: Path) -> None:
    document = _compose_config(_env_file(tmp_path))
    for service in ("api", "worker"):
        environment = _environment(document, service)
        assert "WD_ADMIN_EMAIL" not in environment
        assert "WD_ADMIN_PASSWORD" not in environment


def test_llm_defaults_reach_backend_containers(tmp_path: Path) -> None:
    document = _compose_config(_env_file(tmp_path))
    for service in ("migrate", "api", "worker"):
        assert _environment(document, service)["WD_LLM_DEFAULT_EMBEDDING"] == EMBEDDING_MODEL


def test_worker_memory_limit_defaults_to_4g(tmp_path: Path) -> None:
    document = _compose_config(_env_file(tmp_path))
    assert _memory_bytes(document) == 4 * 1024**3


def test_worker_memory_limit_is_configurable(tmp_path: Path) -> None:
    document = _compose_config(_env_file(tmp_path, "WD_WORKER_MEM_LIMIT=1g"))
    assert _memory_bytes(document) == 1 * 1024**3
