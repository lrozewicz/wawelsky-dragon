"""Efemeryczny stos eval przez ``tools/dev/up.sh`` (kontrakt C13).

Tylko stdlib i ``subprocess``. Sufiks ``-eval`` w ``COMPOSE_PROJECT_NAME`` —
stos eval nie koliduje ze stosem ``verify.sh`` tego samego worktree; porty z
puli omijają zajęte bloki. ``up.sh test env`` przy ustawionych 5 zmiennych nie
przelicza, więc drugie ``env`` wypisuje nazwę z sufiksem.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parents[2]


class StackError(RuntimeError):
    """Podniesienie albo zejście stosu eval nie udało się."""


STACK_ENV_KEYS: tuple[str, ...] = (
    "COMPOSE_PROJECT_NAME",
    "WD_TEST_DB_PORT",
    "WD_TEST_LLM_PORT",
    "WD_TEST_API_PORT",
    "WD_TEST_WEB_PORT",
    "WD_DB_HOST",
    "WD_DB_PORT",
    "WD_DB_USER",
    "WD_DB_PASSWORD",
    "WD_DB_NAME",
    "WD_LLM_BASE_URL",
)

STACK_UP_SCRIPT: str = (
    'eval "$(tools/dev/up.sh test env)"'
    ' && export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME}-eval"'
    ' && tools/dev/up.sh test up "$@" >&2'
    " && tools/dev/up.sh test env"
)


def parse_env(text: str) -> dict[str, str]:
    """Linie ``export K=V`` → {K: V}; inne linie ignorowane; cudzysłowy zewnętrzne zdjęte."""
    result: dict[str, str] = {}
    for line in text.splitlines():
        if not line.startswith("export "):
            continue
        key, separator, value = line[len("export ") :].partition("=")
        if not separator:
            continue
        if len(value) > 1 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        result[key] = value
    return result


def stack_up(services: tuple[str, ...]) -> dict[str, str]:
    """Podnosi stos eval; zwraca env wypisany przez ``up.sh test env``.

    Otoczenie procesu bez kluczy ``STACK_ENV_KEYS`` — skrypt musi wynegocjować
    własne porty i nazwę projektu. Nieprawidłowy kod wyjścia → ``StackError`` z
    ostatnimi 20 liniami stderr; brak ``COMPOSE_PROJECT_NAME`` w wyniku → ``StackError``.
    """
    env = {key: value for key, value in os.environ.items() if key not in STACK_ENV_KEYS}
    # lista argumentów, bez shell=True; bash z PATH i up.sh ścieżką względną (audyt S603/S607)
    result = subprocess.run(  # noqa: S603
        ["bash", "-c", STACK_UP_SCRIPT, "eval-stack", *services],  # noqa: S607
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise StackError("\n".join(result.stderr.splitlines()[-20:]))
    parsed = parse_env(result.stdout)
    if "COMPOSE_PROJECT_NAME" not in parsed:
        raise StackError("brak COMPOSE_PROJECT_NAME w wyjściu tools/dev/up.sh test env")
    return parsed


def stack_down(env: dict[str, str]) -> None:
    """Zejście stosu eval; ``env`` ze ``stack_up`` wraca do otoczenia procesu."""
    # up.sh ścieżką względną repo (cwd=REPO_ROOT) — audyt S607
    subprocess.run(
        ["tools/dev/up.sh", "test", "down"],  # noqa: S607
        cwd=REPO_ROOT,
        env={**os.environ, **env},
        check=False,
    )


@contextlib.contextmanager
def ephemeral_stack(services: tuple[str, ...]) -> Iterator[dict[str, str]]:
    """Kontekst: ``stack_up`` → yield env → ``finally: stack_down``."""
    env = stack_up(services)
    try:
        yield env
    finally:
        stack_down(env)
