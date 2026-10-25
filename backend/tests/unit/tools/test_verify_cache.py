"""Testy pamięci wyroczni i znanych czerwieni bazy w `tools/dev/verify-lib.sh` (analiza 2026-10-09).

Atrapa wyroczni w tymczasowym repo git źródłuje bibliotekę z prawdziwego repo. Sprawdzamy:
- drugi bieg na tym samym czystym drzewie nie wykonuje kroków (pamięć),
- zmiana drzewa albo brudne drzewo wymusza bieg,
- krok z `work/known-red.md` nie czerwieni wyroczni, a krok spoza listy — tak.
"""

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
TWO_RUNS = 2

MOCK_SOURCE = """#!/usr/bin/env bash
set -euo pipefail
. "$WD_TEST_REPO/tools/dev/verify-lib.sh"
ROOT="$(git rev-parse --show-toplevel)"; cd "$ROOT"
wd_cache_hit fast
wd_step "krok-ok" true
wd_step "krok-czerwony" bash -c 'echo uruchomiony >> .task/runs; [ ! -f .task/fail ]'
wd_cache_store fast
wd_green
"""


def git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603 - stałe argumenty, bez powłoki
        ["git", "-C", str(repo), *args],  # noqa: S607 - git ze ścieżki systemowej
        capture_output=True,
        check=True,
    )


def make_repo(tmp_path: Path, known_red: str = "# Znane czerwienie bazy\n") -> Path:
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True)
    (repo / "work").mkdir()
    (repo / ".task").mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "v@example.invalid")
    git(repo, "config", "user.name", "V")
    script = repo / ".claude" / "v.sh"
    script.write_text(MOCK_SOURCE, encoding="utf-8")
    script.chmod(0o755)
    (repo / "work" / "known-red.md").write_text(known_red, encoding="utf-8")
    (repo / ".gitignore").write_text(".task/\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    return repo


def run(repo: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for key in ("WD_VERIFY_NESTED", "WD_VERIFY_WRAPPED", "WD_VERIFY_NO_CACHE"):
        env.pop(key, None)
    env["WD_TEST_REPO"] = str(REPO_ROOT)
    return subprocess.run(  # noqa: S603 - stałe argumenty, bez powłoki
        ["bash", str(repo / ".claude" / "v.sh")],  # noqa: S607 - bash ze ścieżki systemowej
        cwd=str(repo),
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def runs(repo: Path) -> int:
    path = repo / ".task" / "runs"
    return len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else 0


def test_second_run_on_same_tree_uses_cache(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    first = run(repo)
    second = run(repo)

    assert first.returncode == 0, first.stdout
    assert second.returncode == 0, second.stdout
    assert "pamięć wyroczni" in second.stdout
    assert "WYROCZNIA ZIELONA" in second.stdout
    assert runs(repo) == 1


def test_changed_tree_runs_again(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    run(repo)
    (repo / "x.txt").write_text("zmiana\n", encoding="utf-8")
    git(repo, "add", "x.txt")
    git(repo, "commit", "-qm", "zmiana")

    result = run(repo)

    assert result.returncode == 0
    assert "pamięć wyroczni" not in result.stdout
    assert runs(repo) == TWO_RUNS


def test_dirty_tree_is_not_cached(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / "brudny.txt").write_text("niescommitowany\n", encoding="utf-8")

    run(repo)
    run(repo)

    assert runs(repo) == TWO_RUNS


def test_red_run_is_not_cached(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / ".task" / "fail").touch()

    first = run(repo)
    (repo / ".task" / "fail").unlink()
    second = run(repo)

    assert first.returncode == 1
    assert "WYROCZNIA CZERWONA - nie przeszło: krok-czerwony" in first.stdout
    assert second.returncode == 0
    assert runs(repo) == TWO_RUNS


def test_known_red_step_does_not_fail_oracle(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "# Znane czerwienie bazy\n- `krok-czerwony` — dług bazy; E9-H1\n")
    (repo / ".task" / "fail").touch()

    result = run(repo)

    assert result.returncode == 0, result.stdout
    assert "ZNANA CZERWIEŃ BAZY: krok-czerwony" in result.stdout


def test_step_outside_known_red_still_fails(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "# Znane czerwienie bazy\n- `inny-krok` — dług bazy\n")
    (repo / ".task" / "fail").touch()

    result = run(repo)

    assert result.returncode == 1
    assert "WYROCZNIA CZERWONA - nie przeszło: krok-czerwony" in result.stdout
