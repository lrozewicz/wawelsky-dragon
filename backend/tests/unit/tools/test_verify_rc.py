"""Testy nadzorcy `rc=` w `tools/dev/verify-lib.sh` (kontrakt WP E5-H7d, DEC-277).

Atrapa `.sh` w `tmp_path` źródłuje bibliotekę (repo przez `WD_TEST_REPO`) i zachowuje się wg
argumentu. Testy sprawdzają ostatnią niepustą linię stdout i kod wyjścia procesu. Sygnały
wysyłamy do procesu nadzorcy przez `Popen` (stdout/stderr do plików, nie pipe'ów — atrapa
`hang` zostawia w tle `sleep`, który nie może blokować odczytu). Test integracyjny dowodzi, że
log wygenerowany przez atrapę spełnia warunek 4 `merge-queue.sh` — na tymczasowym repo.
"""

import importlib.util
import os
import signal
import subprocess
import time
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]

RC_OK = 0
RC_RED = 1
RC_TERM = 143
RC_INT = 130

# Atrapa źródłuje bibliotekę i wybiera zachowanie wg pierwszego argumentu (kontrakt §Atrapa).
MOCK_SOURCE = """#!/usr/bin/env bash
# Atrapa wyroczni do testów nadzorcy rc= (WP E5-H7d).
set -euo pipefail
. "$WD_TEST_REPO/tools/dev/verify-lib.sh"

case "${1:-}" in
  green) wd_green ;;
  red) wd_red x ;;
  setfalse) false ;;
  selfterm) kill -TERM $$ ;;
  trap) trap 'echo EXIT-ACTION' EXIT; wd_green ;;
  hang)
    touch "$WD_TEST_MARKER"
    sleep 30 &
    wait
    ;;
  *)
    echo "atrapa: nieznany tryb '${1:-}'" >&2
    exit 2
    ;;
esac
"""


def write_mock(tmp_path: Path) -> Path:
    script = tmp_path / "atrapa.sh"
    script.write_text(MOCK_SOURCE, encoding="utf-8")
    script.chmod(0o755)
    return script


def mock_env(**extra: str) -> dict[str, str]:
    """Środowisko atrapy: bez znaczników zagnieżdżenia z wyroczni-rodzica, repo w `WD_TEST_REPO`."""
    env = os.environ.copy()
    env.pop("WD_VERIFY_NESTED", None)
    env.pop("WD_VERIFY_WRAPPED", None)
    env["WD_TEST_REPO"] = str(REPO_ROOT)
    env.update(extra)
    return env


def run_mock(tmp_path: Path, mode: str, **extra: str) -> subprocess.CompletedProcess[str]:
    script = write_mock(tmp_path)
    return subprocess.run(  # noqa: S603 - stałe argumenty, bez powłoki
        ["bash", str(script), mode],  # noqa: S607 - bash ze ścieżki systemowej
        cwd=str(REPO_ROOT),
        env=mock_env(**extra),
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def nonempty_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


def last_nonempty_line(text: str) -> str:
    lines = nonempty_lines(text)
    assert lines, f"brak wyjścia na stdout: {text!r}"
    return lines[-1]


def rc_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("rc=")]


def load_merge_queue_module() -> ModuleType:
    """Ładuje helpery `test_merge_queue.py` z tego katalogu (niezależnie od import-mode pytest)."""
    path = Path(__file__).with_name("test_merge_queue.py")
    spec = importlib.util.spec_from_file_location("_mq_helpers", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- Werdykty i kody wyjścia ------------------------------------------------


def test_green_ends_with_verdict_then_rc_zero(tmp_path: Path) -> None:
    result = run_mock(tmp_path, "green")
    lines = nonempty_lines(result.stdout)
    assert result.returncode == RC_OK, result.stderr
    assert lines[-2:] == ["WYROCZNIA ZIELONA", "rc=0"]


def test_red_ends_with_rc_one(tmp_path: Path) -> None:
    result = run_mock(tmp_path, "red")
    lines = nonempty_lines(result.stdout)
    assert result.returncode == RC_RED, result.stderr
    assert lines[-2] == "WYROCZNIA CZERWONA - nie przeszło: x"
    assert lines[-1] == "rc=1"


def test_false_under_set_e_ends_with_rc_one(tmp_path: Path) -> None:
    result = run_mock(tmp_path, "setfalse")
    assert result.returncode == RC_RED, result.stderr
    assert last_nonempty_line(result.stdout) == "rc=1"


def test_self_term_ends_with_rc_143(tmp_path: Path) -> None:
    result = run_mock(tmp_path, "selfterm")
    assert result.returncode == RC_TERM, result.stderr
    assert last_nonempty_line(result.stdout) == "rc=143"


def test_child_exit_trap_runs_and_rc_is_last(tmp_path: Path) -> None:
    result = run_mock(tmp_path, "trap")
    lines = nonempty_lines(result.stdout)
    assert result.returncode == RC_OK, result.stderr
    assert lines[-2:] == ["EXIT-ACTION", "rc=0"]  # pułapka EXIT dziecka działa w całości


@pytest.mark.parametrize(
    ("mode", "expected_rc"),
    [
        ("green", RC_OK),
        ("red", RC_RED),
        ("setfalse", RC_RED),
        ("selfterm", RC_TERM),
        ("trap", RC_OK),
    ],
)
def test_exactly_one_rc_line_per_run(tmp_path: Path, mode: str, expected_rc: int) -> None:
    result = run_mock(tmp_path, mode)
    assert result.returncode == expected_rc, result.stderr
    assert len(rc_lines(result.stdout)) == 1


def test_nested_run_is_silent(tmp_path: Path) -> None:
    result = run_mock(tmp_path, "green", WD_VERIFY_NESTED="1")
    assert result.returncode == RC_OK, result.stderr
    assert "rc=" not in result.stdout
    assert "WYROCZNIA" not in result.stdout


# --- Sygnały do nadzorcy ----------------------------------------------------


def run_hang_with_signal(tmp_path: Path, sig: int) -> tuple[int, str]:
    """Uruchamia atrapę `hang`, czeka na plik-znacznik, wysyła sygnał do nadzorcy.

    `env --default-signal=SIGINT` przywraca w dziecku domyślną obsługę INT przed `exec bash`.
    Nadzorca w realnym użyciu startuje w pierwszym planie (Ctrl-C trafia w jego pułapkę INT),
    a gdy testy jadą pod nadzorcą (`verify-fast` jest dzieckiem w tle, więc ma INT ignorowany
    procesowo — DEC-277), `os.kill(SIGINT)` byłoby bez skutku.
    """
    script = write_mock(tmp_path)
    marker = tmp_path / "started"
    out = tmp_path / "out.txt"
    err = tmp_path / "err.txt"
    env = mock_env(WD_TEST_MARKER=str(marker))
    with out.open("wb") as out_file, err.open("wb") as err_file:
        proc = subprocess.Popen(  # noqa: S603 - stałe argumenty, bez powłoki
            ["env", "--default-signal=SIGINT", "bash", str(script), "hang"],  # noqa: S607
            cwd=str(REPO_ROOT),
            env=env,
            stdout=out_file,
            stderr=err_file,
        )
        deadline = time.monotonic() + 20
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists(), "atrapa 'hang' nie wystartowała (brak pliku-znacznika)"
        os.kill(proc.pid, sig)
        rc = proc.wait(timeout=30)
    return rc, out.read_text(encoding="utf-8")


def test_sigterm_to_supervisor_reports_143(tmp_path: Path) -> None:
    rc, stdout = run_hang_with_signal(tmp_path, signal.SIGTERM)
    assert rc == RC_TERM
    assert last_nonempty_line(stdout) == "rc=143"


def test_sigint_to_supervisor_reports_130(tmp_path: Path) -> None:
    rc, stdout = run_hang_with_signal(tmp_path, signal.SIGINT)
    assert rc == RC_INT
    assert last_nonempty_line(stdout) == "rc=130"


# --- Integracja: log atrapy przechodzi warunek 4 merge-queue.sh --------------


def test_generated_green_log_merges(tmp_path: Path) -> None:
    vlog = run_mock(tmp_path, "green").stdout
    assert last_nonempty_line(vlog) == "rc=0"

    mq = load_merge_queue_module()
    repo = mq.init_repo(tmp_path)
    main_before = mq.git(repo, "rev-parse", "main")
    mq.add_wp(repo, mq.Wp("W1", sha_main=main_before, vlog=vlog))
    stub = mq.make_stub(tmp_path, "ok.sh")

    result = mq.run_queue(repo, "W1", verify_cmd=stub)

    assert result.returncode == mq.RC_MERGED, result.stderr
    assert "MERGED" in mq.log_statuses(repo, "W1")
