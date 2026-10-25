"""Testy wdeval.stack — efemeryczny stos eval (kontrakt C13). Bez Dockera: tylko łatki."""

from pathlib import Path

import pytest

import wdeval.stack as stack_module
from wdeval.stack import (
    REPO_ROOT,
    STACK_ENV_KEYS,
    STACK_UP_SCRIPT,
    StackError,
    ephemeral_stack,
    parse_env,
    stack_down,
    stack_up,
)


class _FakeCompleted:
    """Podstawka subprocess.CompletedProcess (nie chcemy prawdziwego Dockera)."""

    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_repo_root() -> None:
    assert Path(stack_module.__file__).resolve().parents[2] == REPO_ROOT
    assert (REPO_ROOT / "tools" / "dev" / "up.sh").exists()


def test_stack_env_keys_doslowie() -> None:
    assert STACK_ENV_KEYS == (
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


def test_stack_up_script_doslowie() -> None:
    assert STACK_UP_SCRIPT == (
        'eval "$(tools/dev/up.sh test env)"'
        ' && export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME}-eval"'
        ' && tools/dev/up.sh test up "$@" >&2'
        " && tools/dev/up.sh test env"
    )


def test_parse_env_przyklad_z_briefu() -> None:
    assert parse_env("export A=1\nfoo\nexport B='x y'\n") == {"A": "1", "B": "x y"}


def test_parse_env_podwojne_cudzyslowy_i_bez_rowna_sie() -> None:
    assert parse_env('export C="w v"\nexport BEZ\nNIE-EXPORT D=3\n') == {"C": "w v"}


def test_stack_up_wywolanie(monkeypatch: pytest.MonkeyPatch) -> None:
    przechwycone: dict[str, object] = {}
    atrapa_otoczenie = {
        "PATH": "/usr/bin",
        "COMPOSE_PROJECT_NAME": "p-glowny",
        "WD_TEST_DB_PORT": "5544",
    }
    monkeypatch.setattr(stack_module.os, "environ", atrapa_otoczenie)

    def atrapa_run(args: list[str], **kwargs: object) -> _FakeCompleted:
        przechwycone["args"] = args
        przechwycone["kwargs"] = kwargs
        return _FakeCompleted(0, stdout="export COMPOSE_PROJECT_NAME=p-eval\n")

    monkeypatch.setattr(stack_module.subprocess, "run", atrapa_run)
    wynik = stack_up(("mariadb-test",))

    assert wynik == {"COMPOSE_PROJECT_NAME": "p-eval"}
    assert przechwycone["args"] == ["bash", "-c", STACK_UP_SCRIPT, "eval-stack", "mariadb-test"]
    kwargs = przechwycone["kwargs"]
    assert kwargs["cwd"] == REPO_ROOT
    assert kwargs["env"] == {"PATH": "/usr/bin"}
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs["check"] is False


def test_stack_up_niepowodzenie_ostatnie_20_linii(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stack_module.os, "environ", {})
    stderr = "\n".join(f"linia{i}" for i in range(1, 31))
    monkeypatch.setattr(
        stack_module.subprocess, "run", lambda args, **kw: _FakeCompleted(1, stderr=stderr)
    )
    with pytest.raises(StackError) as excinfo:
        stack_up(("mariadb-test",))
    assert excinfo.value.args[0] == "\n".join(f"linia{i}" for i in range(11, 31))


def test_stack_up_brak_nazwy_projektu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stack_module.os, "environ", {})
    monkeypatch.setattr(
        stack_module.subprocess,
        "run",
        lambda args, **kw: _FakeCompleted(0, stdout="export INNE=1\n"),
    )
    with pytest.raises(StackError, match="COMPOSE_PROJECT_NAME"):
        stack_up(())


def test_stack_down(monkeypatch: pytest.MonkeyPatch) -> None:
    przechwycone: dict[str, object] = {}
    atrapa_otoczenie = {"PATH": "/usr/bin"}
    monkeypatch.setattr(stack_module.os, "environ", atrapa_otoczenie)

    def atrapa_run(args: list[str], **kwargs: object) -> _FakeCompleted:
        przechwycone["args"] = args
        przechwycone["kwargs"] = kwargs
        return _FakeCompleted(0)

    monkeypatch.setattr(stack_module.subprocess, "run", atrapa_run)
    stack_down({"COMPOSE_PROJECT_NAME": "p-eval"})

    assert przechwycone["args"] == ["tools/dev/up.sh", "test", "down"]
    kwargs = przechwycone["kwargs"]
    assert kwargs["cwd"] == REPO_ROOT
    assert kwargs["check"] is False
    assert kwargs["env"] == {"PATH": "/usr/bin", "COMPOSE_PROJECT_NAME": "p-eval"}


def test_ephemeral_stack_down_po_wyjatku(monkeypatch: pytest.MonkeyPatch) -> None:
    env_z_up = {"COMPOSE_PROJECT_NAME": "p-eval"}
    wywolania_down: list[dict[str, str]] = []
    monkeypatch.setattr(stack_module, "stack_up", lambda services: env_z_up)
    monkeypatch.setattr(stack_module, "stack_down", wywolania_down.append)

    with pytest.raises(RuntimeError, match="wybuch"), ephemeral_stack(("mariadb-test",)) as env:
        assert env == env_z_up
        raise RuntimeError("wybuch")

    assert wywolania_down == [env_z_up]


def test_ephemeral_stack_sciezka_zwyczajna(monkeypatch: pytest.MonkeyPatch) -> None:
    wywolania_down: list[dict[str, str]] = []
    monkeypatch.setattr(
        stack_module, "stack_up", lambda services: {"COMPOSE_PROJECT_NAME": "p-eval"}
    )
    monkeypatch.setattr(stack_module, "stack_down", wywolania_down.append)

    with ephemeral_stack(("mariadb-test", "fake-llm")) as env:
        assert env == {"COMPOSE_PROJECT_NAME": "p-eval"}

    assert len(wywolania_down) == 1
