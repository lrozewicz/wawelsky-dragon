"""Testy kompletności `docs/decisions/INDEX.md` i scalania bez konfliktów (`merge=union`).

Brief: `work/wp/E5-H7b/tasks/T3-decisions-index.md` (kontrakt WP E5-H7b §„INDEX (T3)”).

Sprawdzamy:
- każdy plik `docs/decisions/DEC-*.md` ma dokładnie jeden wiersz tabeli INDEX,
- brak duplikatów numerów i wierszy wskazujących nieistniejący plik,
- `.gitattributes` deklaruje `docs/decisions/INDEX.md merge=union`, dzięki czemu równoległe
  dopisanie wiersza na końcu pliku w dwóch gałęziach nie daje konfliktu scalania (dowód: dwa
  tymczasowe repo `tmp_path`, z atrybutem i bez).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
DECISIONS_DIR = REPO_ROOT / "docs" / "decisions"
INDEX_PATH = DECISIONS_DIR / "INDEX.md"
GITATTRIBUTES_PATH = REPO_ROOT / ".gitattributes"

# Kontrakt: wiersz INDEX zawiera link `[DEC-nnn](DEC-nnn.md)` z tym samym numerem.
ROW_LINK_RE = re.compile(r"\[DEC-(\d+)\]\(DEC-\1\.md\)")
UNION_LINE = "docs/decisions/INDEX.md merge=union"

# Wiersze tymczasowego repo dowodowego (numery spoza prawdziwego INDEX).
ROW_A = "| [DEC-901](DEC-901.md) | 2026-10-05 | wiersz gałęzi add-a | tmp | test |"
ROW_B = "| [DEC-902](DEC-902.md) | 2026-10-05 | wiersz gałęzi add-b | tmp | test |"
BASE_INDEX = (
    "# Dziennik decyzji Doradcy\n"
    "\n"
    "| Nr | Data | Temat | Zakres | Pytał |\n"
    "|---|---|---|---|---|\n"
    "| [DEC-001](DEC-001.md) | 2026-09-27 | wiersz bazowy | wszystkie WP | Programista |\n"
)


def index_row_numbers() -> list[str]:
    """Numery DEC (`DEC-nnn`) z wierszy tabeli INDEX, tj. linii zaczynających się od `|`."""
    numbers: list[str] = []
    for line in INDEX_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("|"):
            numbers.extend(f"DEC-{digits}" for digits in ROW_LINK_RE.findall(line))
    return numbers


def decision_files() -> set[str]:
    """Nazwy plików decyzji bez rozszerzenia, np. `DEC-039`."""
    return {path.stem for path in DECISIONS_DIR.glob("DEC-*.md")}


def test_every_decision_file_has_exactly_one_index_row() -> None:
    rows = index_row_numbers()
    counts: dict[str, int] = {}
    for number in rows:
        counts[number] = counts.get(number, 0) + 1

    duplicates = sorted(number for number, count in counts.items() if count > 1)
    assert duplicates == [], f"numery z więcej niż jednym wierszem INDEX: {duplicates}"

    missing = sorted(decision_files() - set(rows))
    assert missing == [], f"pliki DEC-*.md bez wiersza w INDEX: {missing}"

    dangling = sorted(set(rows) - decision_files())
    assert dangling == [], f"wiersze INDEX bez pliku DEC-*.md: {dangling}"


def test_gitattributes_marks_index_as_union_merge() -> None:
    assert GITATTRIBUTES_PATH.is_file(), f"brak pliku {GITATTRIBUTES_PATH}"
    lines = [line.strip() for line in GITATTRIBUTES_PATH.read_text(encoding="utf-8").splitlines()]
    assert UNION_LINE in lines, f"brak linii `{UNION_LINE}` w .gitattributes"


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - stałe argumenty, bez powłoki
        ["git", "-C", str(repo), *args],  # noqa: S607 - git ze ścieżki systemowej
        capture_output=True,
        text=True,
        check=False,
    )


def git_ok(repo: Path, *args: str) -> None:
    result = git(repo, *args)
    assert result.returncode == 0, f"git {' '.join(args)} rc={result.returncode}: {result.stderr}"


def init_repo(tmp_path: Path, *, with_union: bool) -> Path:
    """Repo dowodowe z INDEX w `docs/decisions/`; opcjonalnie z atrybutem `merge=union`."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git_ok(repo, "init", "-q", "-b", "main")
    git_ok(repo, "config", "user.email", "index@example.invalid")
    git_ok(repo, "config", "user.name", "Index Test")
    git_ok(repo, "config", "commit.gpgsign", "false")
    if with_union:
        (repo / ".gitattributes").write_text(UNION_LINE + "\n", encoding="utf-8")
    index = repo / "docs" / "decisions" / "INDEX.md"
    index.parent.mkdir(parents=True)
    index.write_text(BASE_INDEX, encoding="utf-8")
    git_ok(repo, "add", "-A")
    git_ok(repo, "commit", "-qm", "init")
    return repo


def append_row_on_branch(repo: Path, branch: str, row: str) -> None:
    """Gałąź `branch` od `main` dopisuje `row` na końcu INDEX (jak nowa decyzja)."""
    git_ok(repo, "checkout", "-q", "-b", branch, "main")
    index = repo / "docs" / "decisions" / "INDEX.md"
    with index.open("a", encoding="utf-8") as handle:
        handle.write(row + "\n")
    git_ok(repo, "add", "docs/decisions/INDEX.md")
    git_ok(repo, "commit", "-qm", f"wiersz {branch}")


def merge_two_appended_rows(tmp_path: Path, *, with_union: bool) -> tuple[int, str]:
    """Dwie gałęzie dopisują różne wiersze na końcu INDEX; zwraca (rc merge, treść INDEX)."""
    repo = init_repo(tmp_path, with_union=with_union)
    append_row_on_branch(repo, "add-a", ROW_A)
    append_row_on_branch(repo, "add-b", ROW_B)
    git_ok(repo, "checkout", "-q", "add-a")
    result = git(repo, "merge", "--no-edit", "add-b")
    content = (repo / "docs" / "decisions" / "INDEX.md").read_text(encoding="utf-8")
    return result.returncode, content


def test_union_merge_keeps_both_appended_rows(tmp_path: Path) -> None:
    rc, content = merge_two_appended_rows(tmp_path, with_union=True)
    assert rc == 0, f"scalanie z merge=union dało konflikt (rc={rc})"
    assert "<<<<<<<" not in content
    assert ROW_A in content and ROW_B in content


def test_merge_conflicts_without_union_attribute(tmp_path: Path) -> None:
    """Kontrola: bez `merge=union` to samo scalanie daje konflikt — atrybut jest nośny."""
    rc, _content = merge_two_appended_rows(tmp_path, with_union=False)
    assert rc != 0, "bez merge=union oczekiwano konfliktu scalania"
