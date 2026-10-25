"""Test live (marker ``live``) — prawdziwe embeddingi na próbce 10k (kontrakt C8, WP E5-1 T5).

Uruchamiany WYŁĄCZNIE przez pośrednika z kluczami i działającym stosem testowym —
dokładna komenda i wymagane zmienne: ``work/wp/E5-1/reports/live-command.md``.
Bez ``WD_LLM_BASE_URL``/``WD_LLM_API_KEY`` pomija się, a bez ``WD_PERF_USD_PER_M_TOKENS``
pomija się z komunikatem (szacunek kosztu jest obowiązkowy przed pierwszym wywołaniem sieci).
"""

import asyncio
import json
import os
import statistics
import struct
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pymysql
import pytest
import tiktoken

from wdperf import bench, corpus, real, stats

pytestmark = pytest.mark.live

PERF_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = Path(__file__).resolve().parents[3] / "backend"
OUT_DIR = PERF_DIR / "out"
CACHE_DIR = OUT_DIR / "embed-cache"

SEED = corpus.SEED_DEFAULT
SAMPLE_CHUNKS = 10_000
RECALL_QUERIES = 50
EMBED_LATENCY_REQUESTS = 10
DIM = 3072
MODEL = "openai/text-embedding-3-large"
ESTIMATE_CHUNKS = 200
EF_VALUES = (20, 100, 400)
TOP_K = 10
HIT_EPS = 1e-6
VEC_BATCH = 200


def _require(name: str) -> str:
    """Wartość zmiennej środowiskowej albo skip (test live nie zgaduje konfiguracji)."""
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"brak {name} — test live wymaga konfiguracji pośrednika")
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Zapisuje wynik do ``tools/perf/out`` (katalog z manifestem/pochodnymi)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _read_json(path: Path) -> dict[str, Any]:
    """Czyta JSON z dysku (poza ciałem funkcji async — ASYNC240)."""
    return json.loads(path.read_text())


def _average_tokens() -> float:
    """Średnia liczba tokenów chunka (tiktoken ``cl100k_base``) po 200 próbkach (C8)."""
    encoding = tiktoken.get_encoding("cl100k_base")
    lengths = [
        len(encoding.encode(corpus.chunk_text(SEED, index))) for index in range(ESTIMATE_CHUNKS)
    ]
    return statistics.fmean(lengths)


def _connect() -> pymysql.Connection:
    """Połączenie z MariaDB stosu (dane logowania z env, jak ``wdperf.seed``)."""
    return pymysql.connect(
        host=_require("WD_DB_HOST"),
        port=int(_require("WD_DB_PORT")),
        user=_require("WD_DB_USER"),
        password=_require("WD_DB_PASSWORD"),
        database=_require("WD_DB_NAME"),
        charset="utf8mb4",
        autocommit=False,
    )


async def _seed_single_10k(out: Path) -> dict[str, Any]:
    """Seeduje układ single/10k/d3072 przez CLI ``wdperf.seed`` i zwraca manifest."""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "wdperf.seed",
        "--layout",
        "single",
        "--dim",
        str(DIM),
        "--chunks",
        str(SAMPLE_CHUNKS),
        "--seed",
        str(SEED),
        "--api",
        _require("WD_PERF_API"),
        "--db-host",
        _require("WD_DB_HOST"),
        "--db-port",
        _require("WD_DB_PORT"),
        "--out",
        str(out),
        cwd=str(BACKEND_DIR),
        env={**os.environ, "PYTHONPATH": str(PERF_DIR)},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    assert process.returncode == 0, stderr.decode()
    return _read_json(out)


def _f32_le(vector: list[float]) -> bytes:
    """Wektor jako surowe bajty float32 LE (format przyjmowany przez VECTOR)."""
    return struct.pack(f"<{DIM}f", *vector)


def _chunk_rows(conn: pymysql.Connection) -> list[tuple[str, str, str]]:
    """Wiersze ``(chunk_id, dataset_id, content)`` korpusu (kolejność nie ma znaczenia)."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT id, dataset_id, content FROM chunks")
        return [(str(cid), str(did), str(content)) for cid, did, content in cursor.fetchall()]


def _replace_vectors(conn: pymysql.Connection, rows: list[tuple[str, str, list[float]]]) -> None:
    """Podmienia syntetyczne wektory na prawdziwe w ``chunk_vec_d3072`` (C8)."""
    with conn.cursor() as cursor:
        for start in range(0, len(rows), VEC_BATCH):
            batch = rows[start : start + VEC_BATCH]
            cursor.executemany(
                "UPDATE chunk_vec_d3072 SET embedding=%s WHERE chunk_id=%s",
                [(_f32_le(vector), chunk_id) for chunk_id, _, vector in batch],
            )
        conn.commit()


def _create_recall_tables(conn: pymysql.Connection) -> None:
    """Tabele recall: ``vec_idx`` z indeksem VECTOR, ``vec_scan`` bez (jak SP-1)."""
    base = (
        " chunk_id CHAR(16) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,"
        " dataset_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,"
        f" embedding VECTOR({DIM}) NOT NULL,"
        " KEY ix_dataset (dataset_id)"
    )
    index = ", VECTOR INDEX (embedding) M=16 DISTANCE=cosine"
    with conn.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS vec_idx")
        cursor.execute("DROP TABLE IF EXISTS vec_scan")
        cursor.execute(f"CREATE TABLE vec_idx ({base}{index}) ENGINE=InnoDB")
        cursor.execute(f"CREATE TABLE vec_scan ({base}) ENGINE=InnoDB")
        conn.commit()


def _fill_recall_tables(conn: pymysql.Connection, rows: list[tuple[str, str, list[float]]]) -> None:
    """Wsad wektorów do obu tabel recall (te same wiersze co w indeksie aplikacji)."""
    for table in ("vec_idx", "vec_scan"):
        with conn.cursor() as cursor:
            for start in range(0, len(rows), VEC_BATCH):
                batch = rows[start : start + VEC_BATCH]
                cursor.executemany(
                    f"INSERT INTO {table} (chunk_id, dataset_id, embedding) VALUES (%s, %s, %s)",
                    [
                        (chunk_id, dataset_id, _f32_le(vector))
                        for chunk_id, dataset_id, vector in batch
                    ],
                )
            conn.commit()


def _vec_text(vector: list[float]) -> str:
    """Wektor jako tekst dla ``VEC_FromText`` (jak ``vec_text`` w SP-1)."""
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"


def _top_k(conn: pymysql.Connection, table: str, qv: list[float]) -> list[tuple[str, float]]:
    """Top-10 ``(chunk_id, dystans)`` dla zapytania — po indeksie albo pełnym skanie."""
    statement = (
        f"SELECT chunk_id, VEC_DISTANCE_COSINE(embedding, @qv) FROM {table} "
        "ORDER BY VEC_DISTANCE_COSINE(embedding, @qv) LIMIT %s"
    )
    with conn.cursor() as cursor:
        cursor.execute("SET @qv = VEC_FromText(%s)", (_vec_text(qv),))
        cursor.execute(statement, (TOP_K,))
        return [(str(chunk_id), float(distance)) for chunk_id, distance in cursor.fetchall()]


def _recall(returned: list[tuple[str, float]], exact: list[tuple[str, float]]) -> float:
    """Recall@10 odporny na remisy: trafienie = w top-10 skanu albo dystans <= d10 + eps."""
    exact_ids = {chunk_id for chunk_id, _ in exact}
    d10 = exact[TOP_K - 1][1]
    hits = sum(
        1 for chunk_id, distance in returned if chunk_id in exact_ids or distance <= d10 + HIT_EPS
    )
    return hits / TOP_K


def _recall_by_ef(conn: pymysql.Connection, query_vectors: list[list[float]]) -> dict[str, Any]:
    """Recall@10 indeksu VECTOR dla ``EF_VALUES`` + recall pełnego skanu (kontrola)."""
    exact = [_top_k(conn, "vec_scan", qv) for qv in query_vectors]
    scan_recall = [_recall(rows, rows) for rows in exact]
    entries: list[dict[str, Any]] = []
    with conn.cursor() as cursor:
        for ef in EF_VALUES:
            cursor.execute("SET SESSION mhnsw_ef_search=%s", (ef,))
            recalls = [
                _recall(_top_k(conn, "vec_idx", qv), exact[i]) for i, qv in enumerate(query_vectors)
            ]
            entries.append(
                {
                    "ef_search": ef,
                    "recall_mean": statistics.fmean(recalls),
                    "recall_min": min(recalls),
                }
            )
    return {
        "sample": SAMPLE_CHUNKS,
        "dim": DIM,
        "seed": SEED,
        "top_k": TOP_K,
        "queries": len(query_vectors),
        "scan_recall_mean": statistics.fmean(scan_recall),
        "ef_search": entries,
    }


async def _s1(api: str, api_key: str, dataset_ids: list[str], queries: list[str]) -> dict[str, Any]:
    """Scenariusz S1 (C5) na próbce: 1 rozgrzewka + pomiar ``len(queries)`` zapytań."""
    headers = {"Authorization": f"Bearer {api_key}"}
    latency: list[float] = []
    empty_results = 0
    errors = 0
    async with httpx.AsyncClient(base_url=api, timeout=120.0) as http_client:
        await http_client.post(
            "/api/v1/retrieval",
            headers=headers,
            json=bench.retrieval_body(queries[0], dataset_ids),
        )
        started = time.perf_counter()
        for question in queries[1:]:
            request_started = time.perf_counter()
            response = await http_client.post(
                "/api/v1/retrieval",
                headers=headers,
                json=bench.retrieval_body(question, dataset_ids),
            )
            latency.append((time.perf_counter() - request_started) * 1000)
            payload = response.json()
            if response.status_code != 200 or payload.get("code", 0) != 0:
                errors += 1
            elif not payload["data"]["chunks"]:
                empty_results += 1
        wall_s = time.perf_counter() - started
    return bench.build_result(
        scenario="S1",
        layout="single",
        dim=DIM,
        chunks=SAMPLE_CHUNKS,
        datasets=1,
        seed=SEED,
        n_queries=len(latency),
        concurrency=1,
        api=api,
        latency_ms=latency,
        ttfb_ms=None,
        empty_results=empty_results,
        errors=errors,
        wall_s=wall_s,
        started_at=datetime.now(UTC).isoformat(),
        load_before=list(os.getloadavg()),
        load_after=list(os.getloadavg()),
    )


async def _embed_latency(client: real.EmbeddingClient) -> dict[str, Any]:
    """Pomiar opóźnienia pojedynczego embeddingu zapytania (ms, C8)."""
    samples: list[float] = []
    fresh = corpus.queries(SEED + 2, EMBED_LATENCY_REQUESTS)
    for text in fresh:
        started = time.perf_counter()
        await client.embed([text])
        samples.append((time.perf_counter() - started) * 1000)
    return stats.summarize(samples)


async def test_real_embeddings_recall_and_s1() -> None:
    """Pełny bieg C8: koszt -> seed 10k -> wektory -> recall -> S1 -> opóźnienie."""
    base_url = _require("WD_LLM_BASE_URL")
    api_key = _require("WD_LLM_API_KEY")
    api = _require("WD_PERF_API")
    price_raw = os.environ.get("WD_PERF_USD_PER_M_TOKENS")
    if not price_raw:
        pytest.skip("brak WD_PERF_USD_PER_M_TOKENS — bez ceny nie liczymy szacunku kosztu (C8)")
    usd_per_million = float(price_raw)

    average_tokens = _average_tokens()
    usd_estimated = real.estimate_cost(SAMPLE_CHUNKS, average_tokens, usd_per_million)
    print(
        f"live: ~{average_tokens:.1f} tokenów/chunk, szacunek {SAMPLE_CHUNKS} chunków: "
        f"{usd_estimated:.4f} USD ({usd_per_million} USD/1M)"
    )

    manifest = await _seed_single_10k(OUT_DIR / "manifest-single-d3072.json")
    dataset_ids = [str(dataset_id) for dataset_id in manifest["dataset_ids"]]
    conn = _connect()
    client = real.EmbeddingClient(base_url, api_key, MODEL, CACHE_DIR)
    try:
        chunks = _chunk_rows(conn)
        assert len(chunks) == SAMPLE_CHUNKS, f"korpus ma {len(chunks)} chunków"
        vectors = await client.embed([content for _, _, content in chunks])
        real_rows = [
            (chunk_id, dataset_id, vector)
            for (chunk_id, dataset_id, _), vector in zip(chunks, vectors, strict=True)
        ]
        _replace_vectors(conn, real_rows)

        recall_queries = corpus.queries(SEED + 1, RECALL_QUERIES)
        query_vectors = await client.embed(recall_queries)
        _create_recall_tables(conn)
        _fill_recall_tables(conn, real_rows)
        recall = _recall_by_ef(conn, query_vectors)
        assert recall["scan_recall_mean"] == 1.0, "pełny skan musi odtwarzać własne top-10 (SP-1)"

        bench_queries = corpus.queries(SEED, RECALL_QUERIES + 1)
        s1 = await _s1(api, str(manifest["api_key"]), dataset_ids, bench_queries)
        latency = await _embed_latency(client)
    finally:
        conn.close()
        await client.aclose()

    usd_actual = round(client.tokens_used / 1_000_000 * usd_per_million, 6)
    cost = {
        "tokens_used": client.tokens_used,
        "usd_estimated_before": usd_estimated,
        "usd_actual": usd_actual,
        "usd_per_million": usd_per_million,
    }
    _write_json(OUT_DIR / "real-recall.json", {**recall, **cost})
    _write_json(OUT_DIR / "real-s1.json", {**s1, **cost})
    _write_json(OUT_DIR / "real-embed-latency.json", {**latency, **cost})
    print(
        f"live: tokeny {client.tokens_used}, koszt {usd_actual:.4f} USD, "
        f"recall ef={EF_VALUES}: {[entry['recall_mean'] for entry in recall['ef_search']]}"
    )
