"""Testy tools/agents/merge-queue.sh (kontrakt WP E5-H7 C2, uszczelnienie WP E5-H7b T1).

Każdy test buduje tymczasowe repo git (`tmp_path`, `git init -b main`) i woła skrypt przez
subprocess z `cwd=<repo>` (skrypt porównuje cwd z głównym checkoutem) oraz — poza jawnymi
wyjątkami — z `WD_MQ_REPO=<tmp>` i `WD_MQ_VERIFY_CMD=<stub>`. Testy nigdy nie dotykają
prawdziwego `main`.
"""

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "tools" / "agents" / "merge-queue.sh"

GREEN_VLOG = "--- przykład kroku\nWYROCZNIA ZIELONA\nrc=0\n"

RC_MERGED = 0
RC_RED = 1
RC_REJECTED = 2
LOG_MIN_FIELDS = 3  # <ts> <WP> <STATUS> ...


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603 - stałe argumenty, bez powłoki
        ["git", "-C", str(repo), *args],  # noqa: S607 - git ze ścieżki systemowej
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def git_ok(repo: Path, *args: str) -> bool:
    """Prawda, gdy komenda git kończy się kodem 0 (bez wyjątku)."""
    return (
        subprocess.run(  # noqa: S603 - stałe argumenty, bez powłoki
            ["git", "-C", str(repo), *args],  # noqa: S607 - git ze ścieżki systemowej
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "mq@example.invalid")
    git(repo, "config", "user.name", "MQ Test")
    (repo / "base.txt").write_text("baza\n", encoding="utf-8")
    git(repo, "add", "base.txt")
    git(repo, "commit", "-qm", "init")
    return repo


def make_stub(
    tmp_path: Path,
    name: str,
    *,
    rc: int = 0,
    counter: Path | None = None,
    body: str = "",
) -> Path:
    """Tworzy wykonywalny stub biegu; `counter` inkrementowany raz na wywołanie."""
    script = "#!/usr/bin/env bash\n"
    if counter is not None:
        script += f'printf x >> "{counter}"\n'
    script += body + f"exit {rc}\n"
    stub = tmp_path / name
    stub.write_text(script, encoding="utf-8")
    stub.chmod(0o755)
    return stub


def run_queue(
    repo: Path,
    wp_id: str,
    *,
    verify_cmd: Path | None = None,
    use_override: bool = True,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Woła skrypt z cwd w repo (lub wskazanym katalogu) i środowiskiem testowym.

    `use_override=False` usuwa `WD_MQ_REPO` — skrypt sam wylicza główny checkout.
    """
    env = os.environ.copy()
    env.pop("WD_MQ_REPO", None)
    if use_override:
        env["WD_MQ_REPO"] = str(repo)
    env["WD_MQ_MAIN"] = "main"
    if verify_cmd is not None:
        env["WD_MQ_VERIFY_CMD"] = str(verify_cmd)
    return subprocess.run(  # noqa: S603 - stałe argumenty, bez powłoki
        ["bash", str(SCRIPT), wp_id],  # noqa: S607 - bash ze ścieżki systemowej
        cwd=str(repo if cwd is None else cwd),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def log_records(repo: Path, wp_id: str) -> list[list[str]]:
    """Wiersze logu kolejki dla danego WP: [ts, WP, STATUS, sha, powód...]."""
    log = repo / "work" / "logs" / "merge-queue.log"
    if not log.exists():
        return []
    records: list[list[str]] = []
    for line in log.read_text(encoding="utf-8").splitlines():
        parts = line.split(" ", 4)
        if len(parts) >= LOG_MIN_FIELDS and parts[1] == wp_id:
            records.append(parts)
    return records


def log_statuses(repo: Path, wp_id: str) -> list[str]:
    return [record[2] for record in log_records(repo, wp_id)]


@dataclass(frozen=True)
class Wp:
    """Parametry gałęzi WP: commit kodu + commity work/** + commit raportu TL.md."""

    wp_id: str
    sha_main: str
    vlog: str = GREEN_VLOG
    sha_head: str | None = None
    short_head: bool = False
    omit: frozenset[str] = field(default_factory=frozenset)
    extra_file: str | None = None
    reviewer: str = "Reviewer: APPROVED"
    work_commits: int = 0


def add_wp(repo: Path, wp: Wp) -> str:
    """Buduje gałąź wp/<id>: commit kodu (zwracany SHA) + commity work/** + raport TL.md."""
    git(repo, "checkout", "-q", "-b", f"wp/{wp.wp_id}", "main")
    (repo / f"wp-{wp.wp_id}.txt").write_text("zawartość WP\n", encoding="utf-8")
    git(repo, "add", f"wp-{wp.wp_id}.txt")
    git(repo, "commit", "-qm", f"kod {wp.wp_id}")
    head = git(repo, "rev-parse", "HEAD")

    # Commity po SHA-HEAD zmieniające wyłącznie work/** (dozwolone wg nowej reguły).
    for index in range(wp.work_commits):
        extra = repo / "work" / f"note-{wp.wp_id}-{index}.txt"
        extra.parent.mkdir(parents=True, exist_ok=True)
        extra.write_text("praca w work/\n", encoding="utf-8")
        git(repo, "add", str(extra.relative_to(repo)))
        git(repo, "commit", "-qm", f"work {wp.wp_id} {index}")

    vlog_rel = f"work/logs/vf-{wp.wp_id}.log"
    logs_dir = repo / "work" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    (repo / vlog_rel).write_text(wp.vlog, encoding="utf-8")  # nieśledzony, poza gałęzią

    lines: list[str] = []
    if "SHA-HEAD" not in wp.omit:
        value = head[:8] if wp.short_head else (wp.sha_head or head)
        lines.append(f"SHA-HEAD: {value}")
    if "SHA-MAIN" not in wp.omit:
        lines.append(f"SHA-MAIN: {wp.sha_main}")
    if "Reviewer" not in wp.omit:
        lines.append(wp.reviewer)
    if "VERIFY-FULL-LOG" not in wp.omit:
        lines.append(f"VERIFY-FULL-LOG: {vlog_rel}")
    report = repo / "work" / "wp" / wp.wp_id / "reports" / "TL.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    git(repo, "add", f"work/wp/{wp.wp_id}/reports/TL.md")
    if wp.extra_file is not None:
        extra = repo / wp.extra_file
        extra.parent.mkdir(parents=True, exist_ok=True)
        extra.write_text("dodatkowa zmiana\n", encoding="utf-8")
        git(repo, "add", wp.extra_file)
    git(repo, "commit", "-qm", f"raport {wp.wp_id}")
    git(repo, "checkout", "-q", "main")
    return head


def advance_main(repo: Path) -> str:
    """Dodaje commit na main w innym pliku (main idzie do przodu)."""
    (repo / "other.txt").write_text("inny\n", encoding="utf-8")
    git(repo, "add", "other.txt")
    git(repo, "commit", "-qm", "inny commit na main")
    return git(repo, "rev-parse", "main")


# --- Testy odrzuceń (warunki wejścia) --------------------------------------


def test_missing_branch_is_rejected(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    result = run_queue(repo, "W1")
    assert result.returncode == RC_REJECTED
    assert "REJECTED" in log_statuses(repo, "W1")
    assert result.stderr.strip() != ""


@pytest.mark.parametrize("omit", [frozenset({"Reviewer"}), frozenset({"SHA-HEAD"})])
def test_report_missing_required_line_is_rejected(tmp_path: Path, omit: frozenset[str]) -> None:
    repo = init_repo(tmp_path)
    add_wp(repo, Wp("W1", sha_main=git(repo, "rev-parse", "main"), omit=omit))
    result = run_queue(repo, "W1")
    assert result.returncode == RC_REJECTED
    assert "REJECTED" in log_statuses(repo, "W1")


def test_sha_head_before_code_commit_is_rejected(tmp_path: Path) -> None:
    # SHA-HEAD wskazuje commit przed kodem WP; diff SHA-HEAD..tip zmienia wp-W1.txt poza work/.
    repo = init_repo(tmp_path)
    unrelated = git(repo, "rev-parse", "main")  # commit przed kodem WP
    add_wp(repo, Wp("W1", sha_main=unrelated, sha_head=unrelated))
    result = run_queue(repo, "W1")
    assert result.returncode == RC_REJECTED
    assert "REJECTED" in log_statuses(repo, "W1")


@pytest.mark.parametrize(
    "vlog",
    [
        "--- krok\nrc=0\n",  # brak WYROCZNIA ZIELONA
        "WYROCZNIA ZIELONA\nWYROCZNIA ZIELONA\nrc=0\n",  # dwie linie
        "WYROCZNIA ZIELONA\nrc=1\n",  # rc != 0
    ],
)
def test_verify_log_not_green_is_rejected(tmp_path: Path, vlog: str) -> None:
    repo = init_repo(tmp_path)
    add_wp(repo, Wp("W1", sha_main=git(repo, "rev-parse", "main"), vlog=vlog))
    result = run_queue(repo, "W1")
    assert result.returncode == RC_REJECTED
    assert "REJECTED" in log_statuses(repo, "W1")


def test_report_commit_touching_extra_file_is_rejected(tmp_path: Path) -> None:
    # commit po SHA-HEAD zmienia plik spoza work/ → nowa reguła SHA-HEAD odrzuca.
    repo = init_repo(tmp_path)
    add_wp(repo, Wp("W1", sha_main=git(repo, "rev-parse", "main"), extra_file="extra.txt"))
    result = run_queue(repo, "W1")
    assert result.returncode == RC_REJECTED
    assert "REJECTED" in log_statuses(repo, "W1")


# --- Testy scaleń -----------------------------------------------------------


def test_main_unchanged_merges_without_verify(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    main_before = git(repo, "rev-parse", "main")
    add_wp(repo, Wp("W1", sha_main=main_before))
    counter = tmp_path / "counter"
    stub = make_stub(tmp_path, "ok.sh", counter=counter)
    result = run_queue(repo, "W1", verify_cmd=stub)

    assert result.returncode == RC_MERGED
    assert not counter.exists()  # SHA-MAIN == main → stub nie wołany
    assert "MERGED" in log_statuses(repo, "W1")
    main_after = git(repo, "rev-parse", "main")
    assert main_after != main_before
    assert git(repo, "rev-list", "--merges", "--count", "main") == "1"  # merge commit
    assert (repo / "wp-W1.txt").exists()  # plik z gałęzi WP na main
    assert not (repo / ".wp" / "mq-W1").exists()  # worktree posprzątany
    assert git(repo, "branch", "--list", "mq/W1") == ""  # gałąź posprzątana


def test_main_moves_by_fast_forward_and_contains_wp_file(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    main_before = git(repo, "rev-parse", "main")
    add_wp(repo, Wp("W1", sha_main=main_before))
    stub = make_stub(tmp_path, "ok.sh")
    assert run_queue(repo, "W1", verify_cmd=stub).returncode == RC_MERGED

    assert git_ok(repo, "merge-base", "--is-ancestor", main_before, "main")
    assert (repo / "wp-W1.txt").read_text(encoding="utf-8") == "zawartość WP\n"


def test_main_advanced_runs_verify_exactly_once(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    add_wp(repo, Wp("W1", sha_main=git(repo, "rev-parse", "main")))
    advance_main(repo)  # main idzie do przodu innym commitem w innym pliku
    counter = tmp_path / "counter"
    stub = make_stub(tmp_path, "ok.sh", counter=counter)
    result = run_queue(repo, "W1", verify_cmd=stub)

    assert result.returncode == RC_MERGED
    assert counter.read_text(encoding="utf-8") == "x"  # dokładnie jedno wywołanie
    assert "MERGED" in log_statuses(repo, "W1")


def test_red_verify_keeps_main_and_worktree(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    add_wp(repo, Wp("W1", sha_main=git(repo, "rev-parse", "main")))
    main_before = advance_main(repo)
    counter = tmp_path / "counter"
    stub = make_stub(tmp_path, "red.sh", rc=RC_RED, counter=counter)
    result = run_queue(repo, "W1", verify_cmd=stub)

    assert result.returncode == RC_RED
    assert "RED" in log_statuses(repo, "W1")
    assert git(repo, "rev-parse", "main") == main_before  # main nietknięty
    assert (repo / ".wp" / "mq-W1").exists()  # worktree zostaje do diagnozy


def test_report_only_commit_is_accepted(tmp_path: Path) -> None:
    # fixture: commit kodu + commit samego TL.md (pełny SHA i prefiks 8 znaków).
    repo = init_repo(tmp_path)
    main_before = git(repo, "rev-parse", "main")
    add_wp(repo, Wp("W1", sha_main=main_before))
    add_wp(repo, Wp("W2", sha_main=main_before, short_head=True))
    stub = make_stub(tmp_path, "ok.sh")
    assert run_queue(repo, "W1", verify_cmd=stub).returncode == RC_MERGED
    assert run_queue(repo, "W2", verify_cmd=stub).returncode == RC_MERGED
    assert "MERGED" in log_statuses(repo, "W1")
    assert "MERGED" in log_statuses(repo, "W2")


def test_parallel_invocations_are_serialized(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    sha_main = git(repo, "rev-parse", "main")
    add_wp(repo, Wp("W1", sha_main=sha_main))
    add_wp(repo, Wp("W2", sha_main=sha_main))
    advance_main(repo)  # oba WP wymagają biegu (SHA-MAIN != main)

    events = tmp_path / "intervals.txt"
    stamp = "$(date +%s%N)"
    body = (
        f'printf "START %s\\n" "{stamp}" >> "{events}"\n'
        "sleep 1\n"
        f'printf "END %s\\n" "{stamp}" >> "{events}"\n'
    )
    stub = make_stub(tmp_path, "slow.sh", body=body)

    env = os.environ.copy()
    env["WD_MQ_REPO"] = str(repo)
    env["WD_MQ_MAIN"] = "main"
    env["WD_MQ_VERIFY_CMD"] = str(stub)
    procs = [
        subprocess.Popen(  # noqa: S603 - stałe argumenty, bez powłoki
            ["bash", str(SCRIPT), wp_id],  # noqa: S607 - bash ze ścieżki systemowej
            cwd=str(repo),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for wp_id in ("W1", "W2")
    ]
    codes = [proc.wait() for proc in procs]
    assert codes == [RC_MERGED, RC_MERGED], [proc.stderr.read() for proc in procs]

    # przedziały START-END nie nakładają się: sekwencja zdarzeń START,END,START,END
    tags = [line.split()[0] for line in events.read_text(encoding="utf-8").splitlines()]
    assert tags == ["START", "END", "START", "END"]


# --- Reguły E5-H7b: cwd, linia Reviewer, SHA-HEAD ---------------------------


def test_run_from_linked_worktree_is_rejected(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    main_before = git(repo, "rev-parse", "main")
    add_wp(repo, Wp("W1", sha_main=main_before))
    wp_before = git(repo, "rev-parse", "wp/W1")
    wt = tmp_path / "wt"
    git(repo, "worktree", "add", "-q", str(wt), "wp/W1")

    result = run_queue(repo, "W1", use_override=False, cwd=wt)

    assert result.returncode == RC_REJECTED
    assert "uruchom z głównego checkoutu" in result.stderr
    assert git(repo, "rev-parse", "main") == main_before
    assert git(repo, "rev-parse", "wp/W1") == wp_before
    assert not (repo / ".wp" / "mq-W1").exists()
    assert "REJECTED" in log_statuses(repo, "W1")


def test_run_from_main_checkout_without_override_merges(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    main_before = git(repo, "rev-parse", "main")
    add_wp(repo, Wp("W1", sha_main=main_before))
    wt = tmp_path / "wt"
    git(repo, "worktree", "add", "-q", str(wt), "wp/W1")
    stub = make_stub(tmp_path, "ok.sh")

    result = run_queue(repo, "W1", verify_cmd=stub, use_override=False, cwd=repo)

    assert result.returncode == RC_MERGED, result.stderr
    merged = [record for record in log_records(repo, "W1") if record[2] == "MERGED"]
    assert len(merged) == 1
    assert merged[0][3] == git(repo, "rev-parse", "main")
    assert merged[0][3] != main_before


@pytest.mark.parametrize(
    ("reviewer", "expected_rc"),
    [
        ("Reviewer: APPROVED. Przegląd 3 plików.", RC_MERGED),
        ("Reviewer: APPROVED_X", RC_REJECTED),
        ("Reviewer: CHANGES_REQUESTED", RC_REJECTED),
    ],
)
def test_reviewer_line_variants(tmp_path: Path, reviewer: str, expected_rc: int) -> None:
    repo = init_repo(tmp_path)
    add_wp(repo, Wp("W1", sha_main=git(repo, "rev-parse", "main"), reviewer=reviewer))
    stub = make_stub(tmp_path, "ok.sh")

    result = run_queue(repo, "W1", verify_cmd=stub)

    assert result.returncode == expected_rc, result.stderr
    expected_status = "MERGED" if expected_rc == RC_MERGED else "REJECTED"
    assert expected_status in log_statuses(repo, "W1")


def test_work_only_commits_after_sha_head_are_accepted(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    add_wp(repo, Wp("W1", sha_main=git(repo, "rev-parse", "main"), work_commits=2))
    stub = make_stub(tmp_path, "ok.sh")

    result = run_queue(repo, "W1", verify_cmd=stub)

    assert result.returncode == RC_MERGED, result.stderr
    assert "MERGED" in log_statuses(repo, "W1")


def test_commit_outside_work_after_sha_head_is_rejected(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    add_wp(repo, Wp("W1", sha_main=git(repo, "rev-parse", "main"), extra_file="src/x.txt"))

    result = run_queue(repo, "W1")

    assert result.returncode == RC_REJECTED
    assert "src/x.txt" in result.stderr
    assert "REJECTED" in log_statuses(repo, "W1")


def test_sha_head_from_other_branch_is_rejected(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    git(repo, "checkout", "-q", "-b", "side", "main")
    (repo / "side.txt").write_text("bok\n", encoding="utf-8")
    git(repo, "add", "side.txt")
    git(repo, "commit", "-qm", "bok")
    side_sha = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "main")
    add_wp(repo, Wp("W1", sha_main=git(repo, "rev-parse", "main"), sha_head=side_sha))

    result = run_queue(repo, "W1")

    assert result.returncode == RC_REJECTED
    assert "REJECTED" in log_statuses(repo, "W1")


# --- Reguła 2026-10-09: lista znanych czerwieni bazy pusta --------------------


def _commit_known_red(repo: Path, wp_id: str, content: str) -> None:
    git(repo, "checkout", "-q", f"wp/{wp_id}")
    path = repo / "work" / "known-red.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    git(repo, "add", "work/known-red.md")
    git(repo, "commit", "-qm", "known-red")
    git(repo, "checkout", "-q", "main")


def test_nonempty_known_red_is_rejected(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    add_wp(repo, Wp("W1", sha_main=git(repo, "rev-parse", "main")))
    _commit_known_red(repo, "W1", "# Znane czerwienie bazy\n- `mypy` — dług bazy\n")
    stub = make_stub(tmp_path, "ok.sh")

    result = run_queue(repo, "W1", verify_cmd=stub)

    assert result.returncode == RC_REJECTED
    assert "known-red" in result.stderr
    assert "mypy" in result.stderr


def test_known_red_with_header_only_is_accepted(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    add_wp(repo, Wp("W1", sha_main=git(repo, "rev-parse", "main")))
    _commit_known_red(repo, "W1", "# Znane czerwienie bazy\n> format: - `<krok>` — powód\n")
    stub = make_stub(tmp_path, "ok.sh")

    result = run_queue(repo, "W1", verify_cmd=stub)

    assert result.returncode == RC_MERGED, result.stderr


# --- Reguły E5-H7c: uruchomienie spoza repo git -----------------------------


def test_run_outside_git_repo_is_rejected(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()

    result = run_queue(repo, "W1", cwd=outside)

    assert result.returncode == RC_REJECTED
    assert "nie jest repozytorium git" in result.stderr
    assert log_records(repo, "W1") == []


# --- Kontrola treści skryptu ------------------------------------------------


def test_script_has_no_forbidden_git_commands() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "reset --hard" not in text
    assert "rm -rf" not in text
    assert not re.search(r"\bpush\b", text)
    for line in text.splitlines():
        if "--force" in line:
            assert "worktree remove" in line, line
