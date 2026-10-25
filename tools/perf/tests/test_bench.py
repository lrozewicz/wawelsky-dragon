"""Testy czystej części benchu (``wdperf.bench``) — kontrakt C5.

Testy jednostkowe nie potrzebują niczego poza stdlib. Test ze znacznikiem ``stack``
sprawdza na żywym stosie, że ciało z ``retrieval_body`` przechodzi przez API i że
``build_result`` da się zapisać jako JSON; bez ``WD_PERF_API``/``WD_DB_HOST`` pomija się.
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx
import pytest

from wdperf import bench, corpus

HAS_STACK = bool(os.environ.get("WD_PERF_API") and os.environ.get("WD_DB_HOST"))
needs_stack = pytest.mark.skipif(
    not HAS_STACK, reason="brak WD_PERF_API/WD_DB_HOST — test wymaga stosu testowego"
)

# Ścieżki liczone z położenia pliku: seed startuje z `backend/` z PYTHONPATH na pakiet (C1).
PERF_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = Path(__file__).resolve().parents[3] / "backend"

# Dokładny zestaw kluczy wyniku z przykładu JSON kontraktu C5.
RESULT_KEYS = {
    "tool",
    "version",
    "scenario",
    "layout",
    "dim",
    "chunks",
    "datasets",
    "seed",
    "n_queries",
    "concurrency",
    "api",
    "params",
    "latency_ms",
    "ttfb_ms",
    "empty_results",
    "errors",
    "wall_s",
    "rps",
    "started_at",
    "load_avg_before",
    "load_avg_after",
}


def _result(**overrides: object) -> dict:
    """Wynik dla scenariusza S1; nadpisania podmieniają pojedyncze argumenty."""
    arguments: dict[str, object] = {
        "scenario": "S1",
        "layout": "single",
        "dim": 1024,
        "chunks": 1000,
        "datasets": 1,
        "seed": 20261001,
        "n_queries": 3,
        "concurrency": 1,
        "api": "http://127.0.0.1:9380",
        "latency_ms": [10.0, 20.0, 30.0],
        "ttfb_ms": None,
        "empty_results": 0,
        "errors": 0,
        "wall_s": 1.0,
        "started_at": "2026-10-01T12:00:00+00:00",
        "load_before": [1.0, 1.0, 1.0],
        "load_after": [2.0, 2.0, 2.0],
    }
    arguments.update(overrides)
    return bench.build_result(**arguments)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# retrieval_body
# ---------------------------------------------------------------------------


def test_retrieval_body_carries_params_question_and_datasets() -> None:
    body = bench.retrieval_body("stolica Polski", ["ds-1"])
    assert body["question"] == "stolica Polski"
    assert body["dataset_ids"] == ["ds-1"]
    for key, value in bench.RETRIEVAL_PARAMS.items():
        assert body[key] == value
    assert set(body) == set(bench.RETRIEVAL_PARAMS) | {"question", "dataset_ids"}


def test_retrieval_body_does_not_mutate_constant_params() -> None:
    body = bench.retrieval_body("q", ["ds-1"])
    body["top_k"] = 1
    assert bench.RETRIEVAL_PARAMS["top_k"] == 1024


def test_retrieval_params_match_contract_c5() -> None:
    assert bench.RETRIEVAL_PARAMS == {
        "page": 1,
        "page_size": 30,
        "top_k": 1024,
        "similarity_threshold": 0.0,
        "vector_similarity_weight": 0.3,
    }


# ---------------------------------------------------------------------------
# build_result
# ---------------------------------------------------------------------------


def test_build_result_has_exactly_contract_keys() -> None:
    assert set(_result()) == RESULT_KEYS


def test_build_result_rps_is_samples_over_wall() -> None:
    result = _result(latency_ms=[10.0, 20.0, 30.0], wall_s=2.0)
    assert result["rps"] == 1.5


def test_build_result_rps_zero_for_zero_wall() -> None:
    # wall_s == 0.0 nie może wywrócić dzielenia (C5).
    assert _result(latency_ms=[10.0, 20.0], wall_s=0.0)["rps"] == 0.0


def test_build_result_summarizes_latency_and_keeps_ttfb_null() -> None:
    result = _result(latency_ms=[40.0, 10.0, 30.0, 20.0], ttfb_ms=None)
    assert result["latency_ms"] == {"n": 4, "min": 10.0, "median": 25.0, "p95": 40.0, "max": 40.0}
    assert result["ttfb_ms"] is None


def test_build_result_summarizes_ttfb_for_stream_scenario() -> None:
    result = _result(scenario="S5", concurrency=1, ttfb_ms=[5.0, 15.0, 25.0])
    assert result["ttfb_ms"] == {"n": 3, "min": 5.0, "median": 15.0, "p95": 25.0, "max": 25.0}
    assert result["latency_ms"]["n"] == 3


def test_build_result_params_is_a_copy() -> None:
    result = _result()
    assert result["params"] == bench.RETRIEVAL_PARAMS
    result["params"]["page"] = 7
    assert bench.RETRIEVAL_PARAMS["page"] == 1


# ---------------------------------------------------------------------------
# parse_sse_line
# ---------------------------------------------------------------------------


def test_parse_sse_frame_returns_dict() -> None:
    frame = bench.parse_sse_line(bench.PREFIX + '{"code":0,"data":{"answer":"a"}}')
    assert frame == {"code": 0, "data": {"answer": "a"}}
    assert frame["data"]["answer"] == "a"


def test_parse_sse_done_marker_returns_done() -> None:
    assert bench.parse_sse_line(bench.PREFIX + bench.DONE_MARK) == "DONE"


@pytest.mark.parametrize("line", ["", "   ", ": keep-alive", "event: message", "id: 1"])
def test_parse_sse_other_lines_are_none(line: str) -> None:
    assert bench.parse_sse_line(line) is None


def test_parse_sse_tolerates_line_endings() -> None:
    assert bench.parse_sse_line(bench.PREFIX + '{"code":0,"data":true}\r\n') == {
        "code": 0,
        "data": True,
    }
    assert bench.parse_sse_line(bench.PREFIX + bench.DONE_MARK + "\n") == "DONE"


# ---------------------------------------------------------------------------
# is_final_frame
# ---------------------------------------------------------------------------


def test_is_final_frame_for_data_true() -> None:
    assert bench.is_final_frame({"code": 0, "message": "", "data": True}) is True


def test_is_final_frame_for_done_marker() -> None:
    assert bench.is_final_frame("DONE") is True


@pytest.mark.parametrize(
    "frame",
    [
        {"code": 0, "data": {"answer": "a"}},
        {"code": 0, "data": False},
        {"code": 0},
        None,
    ],
)
def test_is_final_frame_false_for_running_frames(frame: object) -> None:
    assert bench.is_final_frame(frame) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Ze stosem: retrieval_body i build_result na prawdziwym API.
# ---------------------------------------------------------------------------


async def _seed_cli(layout: str, dim: int, chunks: int, out: Path) -> tuple[int, str]:
    """Odpala seed korpusu (T2) jako CLI i zwraca (rc, stderr)."""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "wdperf.seed",
        "--layout",
        layout,
        "--dim",
        str(dim),
        "--chunks",
        str(chunks),
        "--api",
        os.environ["WD_PERF_API"],
        "--db-host",
        os.environ["WD_DB_HOST"],
        "--db-port",
        os.environ["WD_DB_PORT"],
        "--out",
        str(out),
        cwd=str(BACKEND_DIR),
        env={**os.environ, "PYTHONPATH": str(PERF_DIR)},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    return int(process.returncode), stderr.decode()


@pytest.mark.stack
@needs_stack
async def test_retrieval_body_and_result_on_stack(tmp_path: Path) -> None:
    """C5 na żywym API: nazwy pól ciała się zgadzają, a wynik da się zapisać jako JSON."""
    manifest_path = tmp_path / "manifest-single-d1024.json"
    code, stderr = await _seed_cli("single", 1024, 1000, manifest_path)
    assert code == 0, stderr
    manifest = json.loads(manifest_path.read_text())
    question = corpus.queries(corpus.SEED_DEFAULT, 1)[0]

    started = time.perf_counter()
    async with httpx.AsyncClient(base_url=os.environ["WD_PERF_API"], timeout=120.0) as client:
        response = await client.post(
            "/api/v1/retrieval",
            headers={"Authorization": f"Bearer {manifest['api_key']}"},
            json=bench.retrieval_body(question, manifest["dataset_ids"]),
        )
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0, body
    chunks = body["data"]["chunks"]
    assert chunks
    assert len(chunks) <= bench.RETRIEVAL_PARAMS["page_size"]

    result = bench.build_result(
        scenario="S1",
        layout="single",
        dim=1024,
        chunks=1000,
        datasets=1,
        seed=corpus.SEED_DEFAULT,
        n_queries=1,
        concurrency=1,
        api=os.environ["WD_PERF_API"],
        latency_ms=[elapsed_ms],
        ttfb_ms=None,
        empty_results=0,
        errors=0,
        wall_s=elapsed_ms / 1000,
        started_at="2026-10-01T12:00:00+00:00",
        load_before=list(os.getloadavg()),
        load_after=list(os.getloadavg()),
    )
    assert set(result) == RESULT_KEYS
    assert json.loads(json.dumps(result))["latency_ms"]["n"] == 1


# ---------------------------------------------------------------------------
# Ze stosem: scenariusze C5 przez CLI (S1/S3/S4/S5 na korpusie 1k).
# ---------------------------------------------------------------------------

# Liczba równoległych klientów S4 (C5) — tyle próbek daje jedno pytanie.
S4_CLIENTS = 10


async def _bench_cli(manifest: Path, scenario: str, n: int, out: Path) -> tuple[int, str]:
    """Odpala scenariusz benchu jako CLI i zwraca (rc, stderr)."""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "wdperf.bench",
        "--manifest",
        str(manifest),
        "--api",
        os.environ["WD_PERF_API"],
        "--scenario",
        scenario,
        "--n",
        str(n),
        "--out",
        str(out),
        cwd=str(BACKEND_DIR),
        env={**os.environ, "PYTHONPATH": str(PERF_DIR)},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    return int(process.returncode), stderr.decode()


def _load_result(out: Path) -> dict:
    """Wczytuje wynik scenariusza: klucze C5 i zerowe liczniki błędów (C5)."""
    result = json.loads(out.read_text())
    assert set(result) == RESULT_KEYS
    assert result["errors"] == 0
    assert result["empty_results"] == 0
    return result


async def _bench_run(manifest: Path, scenario: str, n: int, out: Path) -> dict:
    """Scenariusz przez CLI: rc 0 i wynik bez błędów (C5); zwraca wczytany wynik."""
    code, stderr = await _bench_cli(manifest, scenario, n, out)
    assert code == 0, stderr
    return _load_result(out)


@pytest.mark.stack
@needs_stack
async def test_bench_scenarios_on_stack(tmp_path: Path) -> None:
    """S1/S4/S5 na `single` i S3 na `multi` (C5) — korpus 1k, bez błędów i pustych wyników.

    Seed resetuje stos, więc scenariusze `single` idą przed seedem układu `multi`.
    """
    single = tmp_path / "manifest-single-d1024.json"
    code, stderr = await _seed_cli("single", 1024, 1000, single)
    assert code == 0, stderr

    result = await _bench_run(single, "S1", 5, tmp_path / "S1-d1024.json")
    assert result["latency_ms"]["n"] == 5
    assert result["concurrency"] == 1
    assert result["datasets"] == 1

    result = await _bench_run(single, "S4", 3, tmp_path / "S4-d1024.json")
    assert result["latency_ms"]["n"] == S4_CLIENTS * 3
    assert result["concurrency"] == S4_CLIENTS

    result = await _bench_run(single, "S5", 3, tmp_path / "S5-d1024.json")
    assert result["latency_ms"]["n"] == 3
    assert result["ttfb_ms"]["n"] == 3

    multi = tmp_path / "manifest-multi-d1024.json"
    code, stderr = await _seed_cli("multi", 1024, 1000, multi)
    assert code == 0, stderr

    result = await _bench_run(multi, "S3", 3, tmp_path / "S3-d1024.json")
    assert result["latency_ms"]["n"] == 3
    assert result["datasets"] == 10
