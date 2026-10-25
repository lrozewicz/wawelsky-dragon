"""Testy seeda korpusu (``wdperf.seed``) — kontrakt C4.

Seed uruchamiamy jako prawdziwe CLI (``python -m wdperf.seed`` z katalogu ``backend/``) —
tak jak w kontrakcie C1 — więc test nie importuje ``app.*`` w procesie pytest.
Testy znacznika ``stack`` wymagają działającego stosu testowego (``WD_PERF_API``,
``WD_DB_HOST``/``WD_DB_PORT``); bez stosu pomijają się, a testy CLI zostają.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from wdperf import corpus

HAS_STACK = bool(os.environ.get("WD_PERF_API") and os.environ.get("WD_DB_HOST"))
# Testy danych wymagają stosu; testy CLI (bez znacznika) działają bez niego.
needs_stack = pytest.mark.skipif(
    not HAS_STACK, reason="brak WD_PERF_API/WD_DB_HOST — seed wymaga stosu testowego"
)

# Katalogi wyliczone z położenia pliku (nie z cwd): CLI zawsze startuje z `backend/`
# z `PYTHONPATH` na pakiet `wdperf` (kontrakt C1).
PERF_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = Path(__file__).resolve().parents[3] / "backend"


async def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    """Uruchamia CLI seedu i zwraca (rc, stdout, stderr)."""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "wdperf.seed",
        *argv,
        cwd=str(BACKEND_DIR),
        env={**os.environ, "PYTHONPATH": str(PERF_DIR)},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    return int(process.returncode), stdout.decode(), stderr.decode()


def _base_args(layout: str, dim: int, chunks: int, out: Path) -> list[str]:
    """Argumenty CLI wspólne dla wszystkich biegów seedu."""
    return [
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
    ]


def _read_manifest(out: Path) -> dict[str, object]:
    """Czyta manifest z dysku (zwykłe I/O plikowe, poza pętlą asyncio)."""
    assert out.is_file(), f"brak manifestu: {out}"
    return json.loads(out.read_text())


async def _seed(layout: str, dim: int, chunks: int, out: Path) -> dict[str, object]:
    """Pełny bieg seedu; rc != 0 → asercja z pełnym stderr."""
    code, _, stderr = await _run_cli(_base_args(layout, dim, chunks, out))
    assert code == 0, stderr
    assert f"{chunks}/{chunks} chunków" in stderr  # postęp na stderr (C4 p. 2)
    return _read_manifest(out)


def _engine() -> AsyncEngine:
    """Silnik asyncmy do bazy stosu (asercje SQL); dane z env stosu testowego."""
    url = URL.create(
        drivername="mysql+asyncmy",
        username=os.environ["WD_DB_USER"],
        password=os.environ["WD_DB_PASSWORD"],
        host=os.environ["WD_DB_HOST"],
        port=int(os.environ["WD_DB_PORT"]),
        database=os.environ["WD_DB_NAME"],
        query={"charset": "utf8mb4"},
    )
    return create_async_engine(url, pool_pre_ping=True)


async def _scalar(engine: AsyncEngine, sql: str) -> int:
    async with engine.connect() as connection:
        return int((await connection.execute(text(sql))).scalar_one())


# ---------------------------------------------------------------------------
# Bez stosu: kontrakt CLI.
# ---------------------------------------------------------------------------


async def test_cli_exposes_contract_options() -> None:
    code, stdout, stderr = await _run_cli(["--help"])
    assert code == 0, stderr
    for option in (
        "--layout",
        "--dim",
        "--chunks",
        "--seed",
        "--api",
        "--db-host",
        "--db-port",
        "--out",
    ):
        assert option in stdout


@pytest.mark.parametrize(
    ("layout", "chunks", "message"),
    [("single", "150", "multiple of 100"), ("multi", "1500", "divisible by 1000")],
)
async def test_cli_rejects_bad_chunk_count(
    layout: str, chunks: str, message: str, tmp_path: Path
) -> None:
    """Zły rozmiar korpusu kończy się przed jakimkolwiek I/O — rc 1 i komunikat."""
    argv = [
        "--layout",
        layout,
        "--dim",
        "1024",
        "--chunks",
        chunks,
        "--api",
        "http://127.0.0.1:1",
        "--db-host",
        "127.0.0.1",
        "--db-port",
        "1",
        "--out",
        str(tmp_path / "manifest.json"),
    ]
    code, _, stderr = await _run_cli(argv)
    assert code == 1
    assert message in stderr
    assert not (tmp_path / "manifest.json").exists()


# ---------------------------------------------------------------------------
# Ze stosem: seed 1k, liczniki SQL i retrieval przez API.
# ---------------------------------------------------------------------------


@pytest.mark.stack
@needs_stack
async def test_seed_single_1000(tmp_path: Path) -> None:
    out = tmp_path / "manifest-single-d1024.json"
    manifest = await _seed("single", 1024, 1000, out)
    assert manifest["layout"] == "single"
    assert manifest["dim"] == 1024
    assert manifest["seed"] == corpus.SEED_DEFAULT
    assert manifest["chunks"] == 1000
    assert len(manifest["dataset_ids"]) == 1
    assert manifest["chat_id"]
    assert manifest["embedding_model"] == "fake-embed-1024"
    assert manifest["fulltext_hits_min"] > 0
    assert manifest["seed_seconds"] > 0

    engine = _engine()
    try:
        assert await _scalar(engine, "SELECT COUNT(*) FROM chunks") == 1000
        assert (
            await _scalar(
                engine,
                "SELECT COUNT(*) FROM chunks WHERE committed = 1 AND available = 1"
                " AND task_id IS NULL",
            )
            == 1000
        )
        assert await _scalar(engine, "SELECT COUNT(*) FROM chunk_vec_d1024") == 1000
        assert await _scalar(engine, "SELECT COUNT(*) FROM documents WHERE run = '3'") == 10
    finally:
        await engine.dispose()

    question = corpus.queries(corpus.SEED_DEFAULT, 1)[0]
    async with httpx.AsyncClient(base_url=os.environ["WD_PERF_API"], timeout=60.0) as client:
        response = await client.post(
            "/api/v1/retrieval",
            headers={"Authorization": f"Bearer {manifest['api_key']}"},
            json={
                "question": question,
                "dataset_ids": manifest["dataset_ids"],
                "page": 1,
                "page_size": 10,
                "top_k": 64,
                "similarity_threshold": 0.0,
                "vector_similarity_weight": 0.3,
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0, body
    assert body["data"]["chunks"]


@pytest.mark.stack
@needs_stack
async def test_seed_multi_1000(tmp_path: Path) -> None:
    out = tmp_path / "manifest-multi-d1024.json"
    manifest = await _seed("multi", 1024, 1000, out)
    assert manifest["layout"] == "multi"
    assert len(manifest["dataset_ids"]) == 10
    assert len(set(manifest["dataset_ids"])) == 10

    engine = _engine()
    try:
        async with engine.connect() as connection:
            rows = (
                await connection.execute(
                    text("SELECT dataset_id, COUNT(*) FROM chunks GROUP BY dataset_id")
                )
            ).all()
        assert len(rows) == 10
        assert {int(row[1]) for row in rows} == {100}
        assert sum(int(row[1]) for row in rows) == 1000
    finally:
        await engine.dispose()


@pytest.mark.stack
@needs_stack
async def test_seed_single_dim3072_registers_model(tmp_path: Path) -> None:
    out = tmp_path / "manifest-single-d3072.json"
    manifest = await _seed("single", 3072, 100, out)
    assert manifest["embedding_model"] == "fake-embed-3072"

    engine = _engine()
    try:
        assert await _scalar(engine, "SELECT COUNT(*) FROM chunk_vec_d3072") == 100
        assert (
            await _scalar(
                engine,
                "SELECT dimension FROM models WHERE name = 'fake-embed-3072'"
                " AND model_type = 'embedding'",
            )
            == 3072
        )
    finally:
        await engine.dispose()
