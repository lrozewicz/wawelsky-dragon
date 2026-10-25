"""Test T9 (WP E5-6): `tools/dev/security-audit.sh gitleaks` skanuje tylko historię z HEAD.

Repozytorium tymczasowe w `tmp_path`: kopiujemy do niego skrypt, jego zależności (są źródłowane)
oraz konfigurację gitleaksa, robimy `git init` + commit bazowy. Przypadek (1): token commitowany
TYLKO na innej gałęzi, HEAD na `main` → rc 0. Przypadek (2, negatywny): token w historii HEAD →
rc 1. Token syntetyczny w formacie reguły `github-pat` budujemy z fragmentów, żeby sam plik testu
nie zawierał całego tokenu.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]

# Skrypt + źródłowane zależności + konfiguracja gitleaksa — dość, by uruchomić podkomendę.
_TEMPLATE_FILES = (
    "tools/dev/security-audit.sh",
    "tools/dev/ensure-tools.sh",
    "tools/dev/wd-version.sh",
    "security/gitleaks.toml",
)

# `ghp_` + 36 znaków alfanumerycznych (format reguły `github-pat`), złożony z fragmentów.
_FAKE_GHP = "ghp_" + "aB3dE6gH9jK2mN5" + "pQ8sT1vW4yZ7cF0hJ" + "3kL6"


def _run(args, cwd):
    # Stałe argumenty bez powłoki; kod wyjścia czytamy sami, więc check=False.
    return subprocess.run(  # noqa: S603 - stałe argumenty, bez powłoki
        args, cwd=cwd, capture_output=True, text=True, check=False
    )


def _git(repo, *args):
    ident = ["-c", "user.name=test", "-c", "user.email=test@example.invalid"]
    res = _run(["git", *ident, *args], repo)
    assert res.returncode == 0, f"git {' '.join(args)} padł: {res.stderr}"
    return res


def _ensure_gitleaks():
    # `ensure-tools.sh` dokłada $HOME/.local/bin do PATH; brak binarki i brak sieci → skip.
    res = _run(["bash", "-c", ". tools/dev/ensure-tools.sh && ensure_gitleaks"], REPO_ROOT)
    if res.returncode != 0:
        pytest.skip(f"gitleaks niedostępny ({res.stderr.strip() or 'brak binarki i sieci'})")


def _prepare_repo(tmp_path):
    for rel in _TEMPLATE_FILES:
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, dst)
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "readme.txt").write_text("hello world\n")
    _git(tmp_path, "add", "readme.txt")
    _git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def _commit_secret(repo):
    (repo / "leak.txt").write_text(f'token = "{_FAKE_GHP}"\n')
    _git(repo, "add", "leak.txt")
    _git(repo, "commit", "-q", "-m", "leak")


def _audit(repo):
    return _run(["bash", "tools/dev/security-audit.sh", "gitleaks"], repo)


def test_secret_on_other_branch_is_not_scanned(tmp_path):
    repo = _prepare_repo(tmp_path)
    _ensure_gitleaks()
    # Token trafia tylko na gałąź oboczną; HEAD wraca na `main`, więc commit nieosiągalny z HEAD.
    _git(repo, "switch", "-c", "feature")
    _commit_secret(repo)
    _git(repo, "switch", "main")

    res = _audit(repo)

    assert res.returncode == 0, (
        f"rc={res.returncode} — sekret na innej gałęzi nie powinien czerwienić skanu HEAD\n"
        f"stdout={res.stdout}\nstderr={res.stderr}"
    )


def test_secret_in_head_history_is_detected(tmp_path):
    repo = _prepare_repo(tmp_path)
    _ensure_gitleaks()
    _commit_secret(repo)  # na `main`, więc osiągalny z HEAD

    res = _audit(repo)

    assert res.returncode == 1, (
        f"rc={res.returncode} — sekret w historii HEAD musi zostać wykryty (oczekiwano rc=1)\n"
        f"stdout={res.stdout}\nstderr={res.stderr}"
    )
