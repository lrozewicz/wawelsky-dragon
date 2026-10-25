"""Próba indeksu VECTOR (mHNSW) na zasianej tabeli wektorów (kontrakt C9, WP E5-1 T6).

Buduje kopię tabeli ``chunk_vec_d<dim>`` jako ``perf_vec_idx`` z ``VECTOR INDEX (embedding)
M=16 DISTANCE=cosine``, mierzy czas budowy i rozmiar, a potem porównuje dokładny top-10
pełnym skanem (``VEC_DISTANCE_COSINE`` bez indeksu) z wynikiem indeksu dla trzech wartości
``mhnsw_ef_search`` (20/100/400). Recall@10 liczony odpornie na remisy jak w spike'u SP-1:
trafienie = zwrócony ``chunk_id`` o dokładnej odległości ``<= d10 + 1e-6``.

Tylko stdlib + pymysql (bez numpy — brak w env backendu). Część czysta (``normalize``,
``perturb``, ``recall_tie_robust``) jest testowana bez bazy; SQL idzie przez pymysql.
CLI: ``python -m wdperf.index_trial --dim 1024 --db-host H --db-port P --n 50 --out ...``.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import struct
import sys
import time
from pathlib import Path
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from wdperf import corpus, stats

# Dokładny top-10 i tolerancja remisów (C9 p. 3/5; metoda SP-1).
TOP_K: int = 10
HIT_EPS: float = 1e-6
# Udział znormalizowanego szumu w zapytaniu „near" (C9 p. 2).
NEAR_NOISE: float = 0.3
# Wartości ``mhnsw_ef_search`` badane po kolei (C9 p. 4).
EF_VALUES: tuple[int, ...] = (20, 100, 400)
# Scratchowa kopia tabeli wektorów z indeksem (C9 p. 1).
INDEX_TABLE: str = "perf_vec_idx"
# Nazwy zmiennych środowiskowych z danymi logowania do bazy (jak w ``wdperf.seed``, C4).
DB_USER_ENV = "WD_DB_USER"
DB_PASSWORD_ENV = "WD_DB_PASSWORD"
DB_NAME_ENV = "WD_DB_NAME"


class IndexTrialError(RuntimeError):
    """Próba indeksu nie może się odbyć (np. pusta tabela źródłowa)."""


def normalize(vector: list[float]) -> list[float]:
    """Wektor jednostkowy; wektor zerowy zwracany bez zmian (brak dzielenia przez 0)."""
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return list(vector)
    return [value / norm for value in vector]


def perturb(
    vector: list[float], unit_noise: list[float], factor: float = NEAR_NOISE
) -> list[float]:
    """``normalize(vector + factor * unit_noise)`` — zapytanie „near" (C9 p. 2)."""
    return normalize(
        [value + factor * noise for value, noise in zip(vector, unit_noise, strict=True)]
    )


def pack_vector(values: list[float]) -> bytes:
    """Wektor jako surowe bajty float32 LE (tak przyjmuje je kolumna VECTOR)."""
    return struct.pack(f"<{len(values)}f", *values)


def unpack_vector(blob: bytes, dim: int) -> list[float]:
    """Surowe bajty float32 LE jako lista ``dim`` floatów (odczyt z bazy)."""
    return list(struct.unpack(f"<{dim}f", blob))


def recall_tie_robust(true_dists: list[float], returned_dists: list[float]) -> float:
    """Recall@k odporny na remisy (SP-1): trafienie gdy ``dist <= d10 + 1e-6``.

    ``true_dists`` to rosnąco posortowane odległości prawdy (top-k z pełnego skanu),
    a ``returned_dists`` to dokładne odległości zwróconych ``chunk_id`` policzone w bazie.
    ``d10`` = największa odległość prawdy; dzielnikiem jest rozmiar prawdy.
    """
    k = len(true_dists)
    if k == 0:
        raise ValueError("recall_tie_robust: empty true_dists")
    d10 = true_dists[k - 1]
    hits = sum(1 for dist in returned_dists if dist <= d10 + HIT_EPS)
    return hits / k


def plan_query_kinds(n: int) -> tuple[int, int]:
    """Podział ``n`` zapytań na (near, random); przy n=50 daje po 25 (C9 p. 2)."""
    near = n // 2
    return near, n - near


def create_index_sql(dim: int) -> str:
    """DDL scratchowej kopii z indeksem wektorowym (C9 p. 1, dosłownie)."""
    return (
        f"CREATE TABLE {INDEX_TABLE} ("
        " chunk_id CHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,"
        " dataset_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,"
        f" embedding VECTOR({dim}) NOT NULL,"
        " PRIMARY KEY (chunk_id),"
        " VECTOR INDEX (embedding) M=16 DISTANCE=cosine"
        ") ENGINE=InnoDB"
    )


def _db_env(name: str) -> str:
    """Wartość zmiennej środowiskowej albo IndexTrialError (brak konfiguracji bazy)."""
    value = os.environ.get(name)
    if not value:
        raise IndexTrialError(f"missing environment variable {name}")
    return value


def connect(db_host: str, db_port: int) -> pymysql.connections.Connection:
    """Połączenie pymysql do bazy stosu; użytkownik/hasło/baza z env (C9 nagłówek)."""
    return pymysql.connect(
        host=db_host,
        port=db_port,
        user=_db_env(DB_USER_ENV),
        password=_db_env(DB_PASSWORD_ENV),
        database=_db_env(DB_NAME_ENV),
        charset="utf8mb4",
        autocommit=False,
    )


def _source_table(dim: int) -> str:
    """Nazwa zasianej tabeli wektorów — z walidowanego ``dim`` (identyfikator, nie wartość)."""
    return f"chunk_vec_d{dim}"


def _set_qv(cursor: pymysql.cursors.Cursor, query: list[float]) -> None:
    """Ustawia ``@qv`` na bajty float32 LE zapytania (C9 p. 2)."""
    cursor.execute("SET @qv = %s", (pack_vector(query),))


def _top_k(cursor: pymysql.cursors.Cursor, table: str) -> tuple[list[str], list[float], float]:
    """Dokładny top-10 z ``table`` dla ``@qv`` i czas zapytania w ms (C9 p. 3/4)."""
    started = time.perf_counter()
    cursor.execute(
        f"SELECT chunk_id, VEC_DISTANCE_COSINE(embedding, @qv) AS dist FROM {table}"
        f" ORDER BY dist LIMIT {TOP_K}"
    )
    rows = cursor.fetchall()
    elapsed_ms = (time.perf_counter() - started) * 1000
    return [row[0] for row in rows], [float(row[1]) for row in rows], elapsed_ms


def _exact_dists(cursor: pymysql.cursors.Cursor, table: str, chunk_ids: list[str]) -> list[float]:
    """Dokładne odległości zwróconych ``chunk_id`` policzone w bazie (C9 p. 5)."""
    if not chunk_ids:
        return []
    placeholders = ", ".join(["%s"] * len(chunk_ids))
    cursor.execute(
        f"SELECT chunk_id, VEC_DISTANCE_COSINE(embedding, @qv) AS dist FROM {table}"
        f" WHERE chunk_id IN ({placeholders})",
        chunk_ids,
    )
    found = {row[0]: float(row[1]) for row in cursor.fetchall()}
    return [found[chunk_id] for chunk_id in chunk_ids if chunk_id in found]


def _mean_min(values: list[float]) -> tuple[float | None, float | None]:
    """(średnia, minimum) z próbek; brak próbek -> (None, None)."""
    if not values:
        return None, None
    return round(sum(values) / len(values), 4), round(min(values), 4)


def _build_queries(
    cursor: pymysql.cursors.Cursor, table: str, dim: int, seed: int, n: int
) -> tuple[list[list[float]], list[str]]:
    """Deterministyczne zapytania: 25 „near" (istniejący wektor + szum) i 25 „random" (C9 p. 2)."""
    near_n, random_n = plan_query_kinds(n)
    cursor.execute(f"SELECT chunk_id FROM {table} ORDER BY chunk_id")
    chunk_ids = [row[0] for row in cursor.fetchall()]
    rng = random.Random(seed)
    near_ids = rng.sample(chunk_ids, near_n)
    queries: list[list[float]] = []
    kinds: list[str] = []
    for chunk_id in near_ids:
        cursor.execute(f"SELECT embedding FROM {table} WHERE chunk_id=%s", (chunk_id,))
        base = unpack_vector(cursor.fetchone()[0], dim)
        noise = normalize([rng.gauss(0.0, 1.0) for _ in range(dim)])
        queries.append(perturb(base, noise))
        kinds.append("near")
    for _ in range(random_n):
        queries.append(normalize([rng.gauss(0.0, 1.0) for _ in range(dim)]))
        kinds.append("random")
    return queries, kinds


def _table_size_mb(cursor: pymysql.cursors.Cursor, db_name: str) -> float:
    """Rozmiar kopii w MB z ``information_schema.tables`` (C9 p. 1)."""
    cursor.execute(
        "SELECT data_length + index_length FROM information_schema.tables"
        " WHERE table_schema=%s AND table_name=%s",
        (db_name, INDEX_TABLE),
    )
    row = cursor.fetchone()
    total_bytes = int(row[0]) if row and row[0] is not None else 0
    return round(total_bytes / 1024 / 1024, 3)


def _explain_key(cursor: pymysql.cursors.Cursor) -> str | None:
    """Kolumna ``key`` planu zapytania na indeksie — czy MariaDB używa indeksu (C9 p. 6)."""
    with cursor.connection.cursor(DictCursor) as dict_cursor:
        dict_cursor.execute(
            f"EXPLAIN SELECT chunk_id FROM {INDEX_TABLE}"
            f" ORDER BY VEC_DISTANCE_COSINE(embedding, @qv) LIMIT {TOP_K}"
        )
        plan = dict_cursor.fetchone()
    return None if plan is None else plan.get("key")


def run(args: argparse.Namespace) -> dict[str, Any]:
    """Sprawdza źródło i uruchamia próbę; na pustej tabeli kończy bez zapisów (C9 wym. 2)."""
    dim = args.dim
    source = _source_table(dim)
    connection = connect(args.db_host, args.db_port)
    cursor = connection.cursor()
    try:
        cursor.execute(f"SELECT COUNT(*) FROM {source}")
        rows = int(cursor.fetchone()[0])
        if rows == 0:
            raise IndexTrialError(f"{source} is empty — uruchom najpierw wdperf.seed (kontrakt C9)")
        return _trial(cursor, connection, dim, source, rows, args)
    finally:
        connection.close()


def _trial(
    cursor: pymysql.cursors.Cursor,
    connection: pymysql.connections.Connection,
    dim: int,
    source: str,
    rows: int,
    args: argparse.Namespace,
) -> dict[str, Any]:
    """Buduje kopię z indeksem, mierzy skan i indeks; ``finally`` sprząta kopię (C9 p. 1)."""
    try:
        # 1. Budowa kopii z indeksem wektorowym + rozmiar.
        cursor.execute(f"DROP TABLE IF EXISTS {INDEX_TABLE}")
        started = time.perf_counter()
        cursor.execute(create_index_sql(dim))
        cursor.execute(
            f"INSERT INTO {INDEX_TABLE} (chunk_id, dataset_id, embedding)"
            f" SELECT chunk_id, dataset_id, embedding FROM {source}"
        )
        connection.commit()
        build_seconds = round(time.perf_counter() - started, 3)
        size_mb = _table_size_mb(cursor, _db_env(DB_NAME_ENV))
        print(
            f"index_trial: zbudowano {INDEX_TABLE} rows={rows} [{build_seconds} s, {size_mb} MB]",
            file=sys.stderr,
        )

        # 2. Zapytania deterministyczne z seeda.
        queries, kinds = _build_queries(cursor, source, dim, args.seed, args.n)
        near_n = kinds.count("near")
        print(f"index_trial: {len(queries)} zapytań ({near_n} near)", file=sys.stderr)

        # 3. Prawda: dokładny top-10 pełnym skanem + czas skanu.
        true_dists: list[list[float]] = []
        scan_ms: list[float] = []
        for query in queries:
            _set_qv(cursor, query)
            _, dists, elapsed_ms = _top_k(cursor, source)
            true_dists.append(dists)
            scan_ms.append(elapsed_ms)
        print(
            f"index_trial: skan n={len(scan_ms)} median={stats.summarize(scan_ms)['median']} ms",
            file=sys.stderr,
        )

        # 4/5. Indeks: pomiar per ef_search i recall@10 odporny na remisy.
        ef_results: dict[str, Any] = {}
        for ef in EF_VALUES:
            cursor.execute("SET SESSION mhnsw_ef_search=%s", (ef,))
            _set_qv(cursor, queries[0])
            _top_k(cursor, INDEX_TABLE)  # rozgrzewka, nieliczona (C9 p. 4)
            idx_ms: list[float] = []
            near_rec: list[float] = []
            random_rec: list[float] = []
            for index, query in enumerate(queries):
                _set_qv(cursor, query)
                returned, _, elapsed_ms = _top_k(cursor, INDEX_TABLE)
                idx_ms.append(elapsed_ms)
                exact = _exact_dists(cursor, source, returned)
                recall = recall_tie_robust(true_dists[index], exact)
                (near_rec if kinds[index] == "near" else random_rec).append(recall)
            near_mean, near_min = _mean_min(near_rec)
            random_mean, random_min = _mean_min(random_rec)
            ef_results[str(ef)] = {
                "idx_ms": stats.summarize(idx_ms),
                "recall_near_mean": near_mean,
                "recall_near_min": near_min,
                "recall_random_mean": random_mean,
                "recall_random_min": random_min,
            }
            print(
                f"index_trial: ef={ef} idx_median={ef_results[str(ef)]['idx_ms']['median']} ms"
                f" recall_near={near_mean} recall_random={random_mean}",
                file=sys.stderr,
            )

        # 6. EXPLAIN: czy plan używa indeksu wektorowego.
        _set_qv(cursor, queries[0])
        explain_key = _explain_key(cursor)
        print(f"index_trial: EXPLAIN key={explain_key!r}", file=sys.stderr)

        return {
            "dim": dim,
            "n": args.n,
            "seed": args.seed,
            "rows": rows,
            "build_seconds": build_seconds,
            "size_mb": size_mb,
            "scan_ms": stats.summarize(scan_ms),
            "ef": ef_results,
            "explain_key": explain_key,
        }
    finally:
        cursor.execute(f"DROP TABLE IF EXISTS {INDEX_TABLE}")
        connection.commit()


def write_result(path: str, result: dict[str, Any]) -> None:
    """Zapisuje wynik JSON (katalog tworzony, gdy brakuje)."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


def build_parser() -> argparse.ArgumentParser:
    """CLI próby indeksu wg C9 (``python -m wdperf.index_trial ...``)."""
    parser = argparse.ArgumentParser(
        prog="wdperf.index_trial", description="Próba indeksu VECTOR na zasianym korpusie (C9)"
    )
    parser.add_argument("--dim", type=int, choices=(1024, 3072), required=True)
    parser.add_argument("--db-host", required=True)
    parser.add_argument("--db-port", type=int, required=True)
    parser.add_argument("--n", type=int, default=50, help="liczba mierzonych zapytań")
    parser.add_argument("--seed", type=int, default=corpus.SEED_DEFAULT)
    parser.add_argument("--out", required=True, help="ścieżka wyniku JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point CLI; rc 1 przy błędzie (m.in. pusta tabela źródłowa) (C9 wymaganie 2)."""
    args = build_parser().parse_args(argv)
    try:
        result = run(args)
    except (IndexTrialError, pymysql.MySQLError, OSError, ValueError) as error:
        print(f"index_trial: {error}", file=sys.stderr)
        return 1
    write_result(args.out, result)
    print(
        f"index_trial: dim={result['dim']} rows={result['rows']}"
        f" explain_key={result['explain_key']!r} -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
