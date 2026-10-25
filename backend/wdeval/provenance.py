"""Proweniencja biegu (kontrakt C8a): git i sumy kontrolne wejść manifestu.

Tylko stdlib + ``git`` przez ``subprocess`` (lista argumentów, bez ``shell=True``).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from wdeval.dataset import file_sha256


def _git(*args: str, repo: Path) -> subprocess.CompletedProcess[str]:
    """Uruchamia ``git <args>`` w katalogu repo (lista argumentów, bez powłoki)."""
    command = ["git", "-C", str(repo), *args]
    return subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603


def git_commit(repo: Path) -> str:
    """Commit HEAD repozytorium; brak gita / błąd → ``"unknown"``."""
    result = _git("rev-parse", "HEAD", repo=repo)
    if result.returncode != 0:
        return "unknown"
    return result.stdout.strip()


def git_dirty(repo: Path) -> bool:
    """Czy drzewo robocze jest brudne (``git status --porcelain`` niepuste); brak gita → True."""
    result = _git("status", "--porcelain", repo=repo)
    if result.returncode != 0:
        return True
    return bool(result.stdout.strip())


def beta_inputs(dataset_path: Path, corpus_dir: Path, item_count: int) -> dict[str, Any]:
    """Pole ``inputs.beta`` manifestu: ścieżki i suma kontrolna datasetu bety."""
    return {
        "dataset_path": str(dataset_path),
        "dataset_sha256": file_sha256(dataset_path),
        "corpus_dir": str(corpus_dir),
        "item_count": item_count,
    }


def codex_inputs(
    codex_dir: Path,
    *,
    gold_item_count: int,
    poquad_path: Path | None,
    poquad_sample: int,
    poquad_seed: int,
) -> dict[str, Any]:
    """Pole ``inputs.codex`` manifestu: korpus, commit i sumy kontrolne wejść."""
    return {
        "corpus_dir": str(codex_dir),
        "commit": git_commit(codex_dir),
        "checksums_sha256": file_sha256(codex_dir / "metadata/checksums.sha256"),
        "gold_item_count": gold_item_count,
        "poquad_sha256": file_sha256(poquad_path) if poquad_path is not None else None,
        "poquad_sample": poquad_sample,
        "poquad_seed": poquad_seed,
    }
