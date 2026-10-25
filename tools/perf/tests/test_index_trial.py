"""Testy próby indeksu wektorowego (``wdperf.index_trial``) — kontrakt C9.

Testy czystej części (``normalize``, ``perturb``, ``recall_tie_robust``, ``pack``/``unpack``)
nie potrzebują niczego poza stdlib. Test CLI ``--help`` działa bez stosu. Test znacznika
``stack`` seeduje korpus 1k (``wdperf.seed``), odpala ``wdperf.index_trial`` jako CLI i
sprawdza klucze wyniku; bez ``WD_PERF_API``/``WD_DB_HOST`` pomija się.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from wdperf import corpus, index_trial

HAS_STACK = bool(os.environ.get("WD_PERF_API") and os.environ.get("WD_DB_HOST"))
needs_stack = pytest.mark.skipif(
    not HAS_STACK, reason="brak WD_PERF_API/WD_DB_HOST — próba indeksu wymaga stosu testowego"
)

# Ścieżki liczone z położenia pliku: CLI startuje z `backend/` z PYTHONPATH na pakiet (C1).
PERF_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = Path(__file__).resolve().parents[3] / "backend"


async def _run_cli(module: str, argv: list[str]) -> tuple[int, str, str]:
    """Uruchamia CLI modułu ``wdperf`` i zwraca (rc, stdout, stderr)."""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        module,
        *argv,
        cwd=str(BACKEND_DIR),
        env={**os.environ, "PYTHONPATH": str(PERF_DIR)},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    return int(process.returncode), stdout.decode(), stderr.decode()


# ---------------------------------------------------------------------------
# Bez stosu: funkcje czyste i kontrakt CLI.
# ---------------------------------------------------------------------------


def test_normalize_scales_to_unit_length() -> None:
    result = index_trial.normalize([3.0, 4.0])
    assert result[0] == pytest.approx(0.6)
    assert result[1] == pytest.approx(0.8)
    assert sum(value * value for value in result) == pytest.approx(1.0)


def test_normalize_keeps_zero_vector() -> None:
    assert index_trial.normalize([0.0, 0.0, 0.0]) == [0.0, 0.0, 0.0]


def test_perturb_is_unit_and_moves_toward_noise() -> None:
    result = index_trial.perturb([1.0, 0.0], [0.0, 1.0], factor=0.3)
    assert sum(value * value for value in result) == pytest.approx(1.0)
    assert result[1] > 0.0  # składowa szumu weszła do wyniku


def test_perturb_default_factor_uses_contract_noise() -> None:
    assert index_trial.perturb([1.0, 0.0], [0.0, 1.0]) == index_trial.perturb(
        [1.0, 0.0], [0.0, 1.0], factor=index_trial.NEAR_NOISE
    )


def test_pack_unpack_roundtrip() -> None:
    values = [0.1, -0.25, 0.5]
    blob = index_trial.pack_vector(values)
    assert len(blob) == 4 * len(values)
    assert index_trial.unpack_vector(blob, len(values)) == pytest.approx(values)


def test_recall_all_hits_including_ties() -> None:
    true_dists = [0.01 * index for index in range(1, index_trial.TOP_K + 1)]
    returned = [true_dists[-1] + 1e-7 for _ in range(index_trial.TOP_K)]
    assert index_trial.recall_tie_robust(true_dists, returned) == 1.0


def test_recall_counts_only_distances_within_epsilon() -> None:
    true_dists = [0.1 * index for index in range(1, index_trial.TOP_K + 1)]
    d10 = true_dists[-1]
    returned = [d10, d10, d10 + 1e-5, d10 + 0.5, d10 + 0.5]
    assert index_trial.recall_tie_robust(true_dists, returned) == pytest.approx(0.2)


def test_recall_empty_truth_raises() -> None:
    with pytest.raises(ValueError):
        index_trial.recall_tie_robust([], [0.1])


@pytest.mark.parametrize(("n", "expected"), [(50, (25, 25)), (4, (2, 2)), (1, (0, 1))])
def test_plan_query_kinds(n: int, expected: tuple[int, int]) -> None:
    assert index_trial.plan_query_kinds(n) == expected


def test_create_index_sql_has_vector_index() -> None:
    ddl = index_trial.create_index_sql(1024)
    assert "VECTOR(1024)" in ddl
    assert "VECTOR INDEX (embedding) M=16 DISTANCE=cosine" in ddl
    assert "PRIMARY KEY (chunk_id)" in ddl


async def test_cli_exposes_contract_options() -> None:
    code, stdout, stderr = await _run_cli("wdperf.index_trial", ["--help"])
    assert code == 0, stderr
    for option in ("--dim", "--db-host", "--db-port", "--n", "--seed", "--out"):
        assert option in stdout


# ---------------------------------------------------------------------------
# Ze stosem: seed 1k i próba indeksu przez CLI (C9 wymaganie 3).
# ---------------------------------------------------------------------------


def _stack_args(out: Path) -> list[str]:
    """Argumenty CLI próby indeksu wskazujące na stos testowy."""
    return [
        "--dim",
        "1024",
        "--db-host",
        os.environ["WD_DB_HOST"],
        "--db-port",
        os.environ["WD_DB_PORT"],
        "--n",
        "4",
        "--out",
        str(out),
    ]


@pytest.mark.stack
@needs_stack
async def test_index_trial_on_stack(tmp_path: Path) -> None:
    """C9 na korpusie 1k: seed, próba indeksu, komplet kluczy wyniku i użyty indeks."""
    manifest = tmp_path / "manifest-single-d1024.json"
    code, _, stderr = await _run_cli(
        "wdperf.seed",
        [
            "--layout",
            "single",
            "--dim",
            "1024",
            "--chunks",
            "1000",
            "--api",
            os.environ["WD_PERF_API"],
            "--db-host",
            os.environ["WD_DB_HOST"],
            "--db-port",
            os.environ["WD_DB_PORT"],
            "--out",
            str(manifest),
        ],
    )
    assert code == 0, stderr

    out = tmp_path / "index-trial-d1024.json"
    code, _, stderr = await _run_cli("wdperf.index_trial", _stack_args(out))
    assert code == 0, stderr
    result = json.loads(out.read_text())

    assert result["dim"] == 1024
    assert result["n"] == 4
    assert result["seed"] == corpus.SEED_DEFAULT
    assert result["rows"] == 1000
    assert result["build_seconds"] > 0
    assert result["size_mb"] > 0
    assert set(result["scan_ms"]) == {"n", "min", "median", "p95", "max"}
    assert result["scan_ms"]["n"] == 4
    assert result["explain_key"] == "embedding"

    assert set(result["ef"]) == {"20", "100", "400"}
    for entry in result["ef"].values():
        assert set(entry["idx_ms"]) == {"n", "min", "median", "p95", "max"}
        assert entry["idx_ms"]["n"] == 4
        for key in (
            "recall_near_mean",
            "recall_near_min",
            "recall_random_mean",
            "recall_random_min",
        ):
            assert set(entry) >= {"idx_ms", key}
