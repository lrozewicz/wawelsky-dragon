"""Testy narzędzia tools/check_file_size.py (kontrakt C2, tabela wejście→wyjście z briefu)."""

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[4] / "tools" / "check_file_size.py"

MAX_LINES = 400
EXIT_VIOLATION = 1
EXIT_USAGE = 2


def run_tool(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - stałe argumenty, bez shell
        [sys.executable, str(SCRIPT), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


def create_file(path: Path, lines: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x = 1\n" * lines, encoding="utf-8")
    return path


def empty_allowlist(tmp_path: Path) -> str:
    allowlist = tmp_path / "empty.txt"
    allowlist.write_text("", encoding="utf-8")
    return str(allowlist)


def test_file_over_limit(tmp_path: Path) -> None:
    big = create_file(tmp_path / "app" / "big.py", 401)
    result = run_tool(
        str(tmp_path / "app"), "--max", str(MAX_LINES), "--allowlist", empty_allowlist(tmp_path)
    )
    assert result.returncode == EXIT_VIOLATION
    assert f"{big}: 401 > {MAX_LINES}" in result.stderr


def test_file_at_limit_is_ok(tmp_path: Path) -> None:
    create_file(tmp_path / "app" / "ok.py", MAX_LINES)
    result = run_tool(
        str(tmp_path / "app"), "--max", str(MAX_LINES), "--allowlist", empty_allowlist(tmp_path)
    )
    assert result.returncode == 0
    assert result.stderr == ""


def test_allowlisted_file_is_exempt(tmp_path: Path) -> None:
    big = create_file(tmp_path / "app" / "big.py", 401)
    allowlist = tmp_path / "allow.txt"
    allowlist.write_text(f"{big}  # test\n", encoding="utf-8")
    result = run_tool(str(tmp_path / "app"), "--max", str(MAX_LINES), "--allowlist", str(allowlist))
    assert result.returncode == 0


def test_allowlist_entry_without_justification(tmp_path: Path) -> None:
    big = create_file(tmp_path / "app" / "big.py", 401)
    allowlist = tmp_path / "allow.txt"
    allowlist.write_text(f"{big}\n", encoding="utf-8")
    result = run_tool(str(tmp_path / "app"), "--max", str(MAX_LINES), "--allowlist", str(allowlist))
    assert result.returncode == EXIT_USAGE
    assert "bez uzasadnienia" in result.stderr


def test_skipped_directories(tmp_path: Path) -> None:
    create_file(tmp_path / "app" / "node_modules" / "x.ts", 500)
    create_file(tmp_path / "app" / ".venv" / "y.py", 500)
    result = run_tool(
        str(tmp_path / "app"), "--max", str(MAX_LINES), "--allowlist", empty_allowlist(tmp_path)
    )
    assert result.returncode == 0


def test_non_source_extension_ignored(tmp_path: Path) -> None:
    create_file(tmp_path / "app" / "notes.txt", 500)
    result = run_tool(
        str(tmp_path / "app"), "--max", str(MAX_LINES), "--allowlist", empty_allowlist(tmp_path)
    )
    assert result.returncode == 0


def test_extension_filter(tmp_path: Path) -> None:
    create_file(tmp_path / "app" / "big.ts", 401)
    result = run_tool(
        str(tmp_path / "app"),
        "--max",
        str(MAX_LINES),
        "--ext",
        ".py",
        "--allowlist",
        empty_allowlist(tmp_path),
    )
    assert result.returncode == 0


def test_missing_directory(tmp_path: Path) -> None:
    result = run_tool(str(tmp_path / "nope"), "--max", str(MAX_LINES))
    assert result.returncode == EXIT_USAGE
