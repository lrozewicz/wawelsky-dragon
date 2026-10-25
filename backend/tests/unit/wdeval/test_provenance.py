"""Testy jednostkowe wdeval.provenance — git_commit/git_dirty i wejścia manifestu (C8a)."""

import subprocess
from pathlib import Path

from wdeval.dataset import file_sha256
from wdeval.provenance import beta_inputs, codex_inputs, git_commit, git_dirty

_COMMIT_HEX_LEN = 40
_POQUAD_SEED = 7


def _git(*args: str, cwd: Path) -> None:
    command = ["git", *args]
    subprocess.run(command, cwd=cwd, check=True, capture_output=True)  # noqa: S603


def test_git_commit_unknown_without_repo(tmp_path: Path) -> None:
    assert git_commit(tmp_path) == "unknown"


def test_git_dirty_true_without_repo(tmp_path: Path) -> None:
    assert git_dirty(tmp_path) is True


def test_git_commit_and_dirty_after_commit(tmp_path: Path) -> None:
    _git("init", "-q", cwd=tmp_path)
    _git(
        "-c",
        "user.email=t@t",
        "-c",
        "user.name=t",
        "commit",
        "--allow-empty",
        "-q",
        "-m",
        "x",
        cwd=tmp_path,
    )
    commit = git_commit(tmp_path)
    assert len(commit) == _COMMIT_HEX_LEN
    assert git_dirty(tmp_path) is False


def test_git_dirty_after_change(tmp_path: Path) -> None:
    _git("init", "-q", cwd=tmp_path)
    (tmp_path / "nowy.txt").write_text("zmiana\n", encoding="utf-8")
    assert git_dirty(tmp_path) is True


def test_beta_inputs(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text('{"id": "q1"}\n', encoding="utf-8")
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    result = beta_inputs(dataset, corpus, 29)
    assert result == {
        "dataset_path": str(dataset),
        "dataset_sha256": file_sha256(dataset),
        "corpus_dir": str(corpus),
        "item_count": 29,
    }


def test_codex_inputs_with_poquad(tmp_path: Path) -> None:
    metadata = tmp_path / "metadata"
    metadata.mkdir()
    checksums = metadata / "checksums.sha256"
    checksums.write_text("abc  x.pdf\n", encoding="utf-8")
    poquad = tmp_path / "poquad-dev.json"
    poquad.write_text("{}", encoding="utf-8")

    result = codex_inputs(
        tmp_path,
        gold_item_count=3,
        poquad_path=poquad,
        poquad_sample=200,
        poquad_seed=1,
    )
    assert result == {
        "corpus_dir": str(tmp_path),
        "commit": "unknown",
        "checksums_sha256": file_sha256(checksums),
        "gold_item_count": 3,
        "poquad_sha256": file_sha256(poquad),
        "poquad_sample": 200,
        "poquad_seed": 1,
    }


def test_codex_inputs_without_poquad(tmp_path: Path) -> None:
    metadata = tmp_path / "metadata"
    metadata.mkdir()
    (metadata / "checksums.sha256").write_text("abc\n", encoding="utf-8")
    result = codex_inputs(
        tmp_path,
        gold_item_count=0,
        poquad_path=None,
        poquad_sample=0,
        poquad_seed=7,
    )
    assert result["poquad_sha256"] is None
    assert result["gold_item_count"] == 0
    assert result["poquad_seed"] == _POQUAD_SEED
