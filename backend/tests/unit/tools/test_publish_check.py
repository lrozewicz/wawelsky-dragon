"""Testy sprawdzianu publikacji `tools/publish/check.sh` (kontrakt WP E5-6 §C1, §C4).

Każdy przypadek buduje tymczasowe repozytorium git (`git init` w `tmp_path`), dodaje pliki do
indeksu i uruchamia realny skrypt. Wzorzec zabroniony wstrzykujemy przez `WD_PUBLISH_PATTERN_FILE`
z neutralnym żetonem — test nie zawiera nazw klienta (DEC-313). Trafienie wzorca w treści lub
w nazwie pliku => kod 1; brak trafień => kod 0; pliki pod `private/` są wyłączone z drzewa
publikacji; brak pliku wzorca => kod 2.
"""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
CHECK_SH = ROOT / "tools" / "publish" / "check.sh"
MARKER = "forbiddentoken"

EXIT_CLEAN = 0
EXIT_HIT = 1
EXIT_NO_PATTERN = 2


def _git(repo: Path, *arguments: str) -> None:
    subprocess.run(  # noqa: S603 - stałe argumenty, bez shell
        ["git", *arguments],  # noqa: S607 - git ze ścieżki systemowej
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )


def _repo_with(tmp_path: Path, files: dict[str, str]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    for rel, content in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    return repo


def _pattern_file(tmp_path: Path) -> Path:
    path = tmp_path / "pattern.txt"
    path.write_text(f"# komentarz\n{MARKER}\n", encoding="utf-8")
    return path


def _run_check(repo: Path, pattern_file: Path | None) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    if pattern_file is None:
        environment.pop("WD_PUBLISH_PATTERN_FILE", None)
    else:
        environment["WD_PUBLISH_PATTERN_FILE"] = str(pattern_file)
    return subprocess.run(  # noqa: S603 - uruchamiamy realny skrypt przez bash
        ["bash", str(CHECK_SH)],  # noqa: S607 - bash ze ścieżki systemowej
        cwd=repo,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_hit_in_content_exits_one(tmp_path: Path) -> None:
    repo = _repo_with(tmp_path, {"app/module.py": f"CLIENT = '{MARKER}'\n"})
    result = _run_check(repo, _pattern_file(tmp_path))
    assert result.returncode == EXIT_HIT
    assert "app/module.py:1" in result.stdout


def test_clean_tree_exits_zero(tmp_path: Path) -> None:
    repo = _repo_with(tmp_path, {"app/module.py": "VALUE = 'hello'\n"})
    result = _run_check(repo, _pattern_file(tmp_path))
    assert result.returncode == EXIT_CLEAN
    assert result.stdout == ""


def test_hit_in_filename_exits_one(tmp_path: Path) -> None:
    repo = _repo_with(tmp_path, {f"app/{MARKER}_client.py": "VALUE = 'hello'\n"})
    result = _run_check(repo, _pattern_file(tmp_path))
    assert result.returncode == EXIT_HIT
    assert f"app/{MARKER}_client.py" in result.stdout


def test_private_path_ignored(tmp_path: Path) -> None:
    repo = _repo_with(
        tmp_path,
        {
            f"private/stack/{MARKER}.env": f"CLIENT = '{MARKER}'\n",
            "app/module.py": "VALUE = 'ok'\n",
        },
    )
    result = _run_check(repo, _pattern_file(tmp_path))
    assert result.returncode == EXIT_CLEAN
    assert result.stdout == ""


def test_missing_pattern_file_exits_two(tmp_path: Path) -> None:
    repo = _repo_with(tmp_path, {"app/module.py": f"CLIENT = '{MARKER}'\n"})
    result = _run_check(repo, None)
    assert result.returncode == EXIT_NO_PATTERN
    assert result.stdout == ""
