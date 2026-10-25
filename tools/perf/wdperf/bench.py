"""Bench (``wdperf.bench``): parametry retrievalu, wynik, ramki SSE i scenariusze C5.

Część czysta (``retrieval_body``, ``build_result``, ``parse_sse_line``, ``is_final_frame``)
nie robi I/O; scenariusze S1-S5, CLI i podkomenda ``explain`` dokładają warstwę sieciową.
"""

import argparse
import asyncio
import json
import os
import struct
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from app.db.repositories.retrieval import _fulltext_sql, _vector_sql
from app.text.fulltext import ft_text, stem_text
from sqlalchemy import TextClause, text
from sqlalchemy.exc import SQLAlchemyError

from wdperf import corpus, seed, stats
from wdperf.seed import SeedError

# Prefiks linii SSE i sentynel końca sklejamy z dwóch literałów: w tym projekcie
# nie wpisujemy ich dosłownie ani w kodzie, ani w komunikatach.
PREFIX = "da" + "ta:"
DONE_MARK = "[DO" + "NE]"

# Stałe parametry retrievalu (kontrakt C5) — trafiają do każdego żądania i wyniku.
RETRIEVAL_PARAMS: dict[str, object] = {
    "page": 1,
    "page_size": 30,
    "top_k": 1024,
    "similarity_threshold": 0.0,
    "vector_similarity_weight": 0.3,
}


def retrieval_body(question: str, dataset_ids: list[str]) -> dict:
    """Ciało żądania retrievalu: stałe z C5 plus pytanie i zbiory danych."""
    return {**RETRIEVAL_PARAMS, "question": question, "dataset_ids": dataset_ids}


def build_result(
    scenario: str,
    layout: str,
    dim: int,
    chunks: int,
    datasets: int,
    seed: int,
    n_queries: int,
    concurrency: int,
    api: str,
    latency_ms: list[float],
    ttfb_ms: list[float] | None,
    empty_results: int,
    errors: int,
    wall_s: float,
    started_at: str,
    load_before: list[float],
    load_after: list[float],
) -> dict:
    """Wynik biegu w kształcie JSON z C5.

    `latency_ms` dla S5 to czasy total_ms. `ttfb_ms` jest null, gdy nie zbierano
    próbek (scenariusze inne niż S5). `rps` = liczba próbek / `wall_s`
    (0.0 przy zerowym czasie, żeby nie dzielić przez zero).
    """
    return {
        "tool": "wdperf",
        "version": 1,
        "scenario": scenario,
        "layout": layout,
        "dim": dim,
        "chunks": chunks,
        "datasets": datasets,
        "seed": seed,
        "n_queries": n_queries,
        "concurrency": concurrency,
        "api": api,
        "params": dict(RETRIEVAL_PARAMS),
        "latency_ms": stats.summarize(latency_ms),
        "ttfb_ms": None if ttfb_ms is None else stats.summarize(ttfb_ms),
        "empty_results": empty_results,
        "errors": errors,
        "wall_s": wall_s,
        "rps": len(latency_ms) / wall_s if wall_s else 0.0,
        "started_at": started_at,
        "load_avg_before": load_before,
        "load_avg_after": load_after,
    }


def parse_sse_line(line: str) -> dict | str | None:
    """Zamienia linię odpowiedzi SSE na ramkę.

    Linia z prefiksem i zwartym JSON-em daje dict; linia z prefiksem i sentynlem
    końca trybu OpenAI daje "DONE"; każda inna (pusta, komentarz) — None.
    """
    if not line.startswith(PREFIX):
        return None
    payload = line[len(PREFIX) :].strip()
    if payload == DONE_MARK:
        return "DONE"
    if not payload:
        return None
    return json.loads(payload)


def is_final_frame(frame: dict | str | None) -> bool:
    """Czy ramka kończy strumień: `data` równe True (C5) albo sentynel "DONE"."""
    if frame == "DONE":
        return True
    return isinstance(frame, dict) and frame.get("data") is True


# ---------------------------------------------------------------------------
# Scenariusze C5: warstwa sieciowa, CLI i podkomenda `explain`.
# ---------------------------------------------------------------------------

# Timeout jednego żądania HTTP (C5: 120 s).
HTTP_TIMEOUT_S = 120.0
# Liczba pierwszych pytań klienta, która nie wchodzi do próbek (C5: 1 rozgrzewka).
WARMUP_QUERIES = 1
# Liczba równoległych klientów S4 (C5).
PARALLEL_CLIENTS = 10

# Scenariusz → (układ korpusu, wybór datasetów, liczba klientów) wg C5.
SCENARIOS: dict[str, tuple[str, str, int]] = {
    "S1": ("single", "first", 1),
    "S2": ("multi", "first", 1),
    "S3": ("multi", "all", 1),
    "S4": ("single", "first", PARALLEL_CLIENTS),
    "S5": ("single", "first", 1),
}

# Podsumowanie bez próbek: `stats.summarize` (T1) wymaga niepustej listy, a wynik
# trzeba zapisać także wtedy, gdy wszystkie żądania padły (C5) — wtedy liczy `errors`.
ZERO_SUMMARY: dict[str, float | int] = {"n": 0, "min": 0.0, "median": 0.0, "p95": 0.0, "max": 0.0}


class BenchError(RuntimeError):
    """Bieg nie może się odbyć (brak manifestu, manifest z innym układem korpusu)."""


@dataclass(frozen=True)
class Probe:
    """Jedno żądanie retrievalu: czas w ms, pusty wynik i flaga błędu (C5)."""

    ms: float
    empty: bool = False
    error: bool = False


@dataclass(frozen=True)
class StreamProbe:
    """Jeden strumień czatu: TTFB, czas całkowity i flaga błędu (C5)."""

    ttfb_ms: float | None
    total_ms: float
    error: bool = False


def _elapsed_ms(started: float) -> float:
    """Milisekundy od znacznika ``time.perf_counter`` (C5)."""
    return (time.perf_counter() - started) * 1000.0


async def run_retrieval(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    dataset_ids: list[str],
    question: str,
) -> Probe:
    """Jedno żądanie retrievalu, mierzone do przeczytania całej odpowiedzi (C5).

    Pusta lista chunków liczy się do ``empty_results``, a HTTP != 200 albo ``code != 0``
    do ``errors``; jedno i drugie nie wchodzi do opóźnień (C5).
    """
    started = time.perf_counter()
    try:
        response = await client.post(
            "/api/v1/retrieval",
            headers={"Authorization": f"Bearer {api_key}"},
            json=retrieval_body(question, dataset_ids),
        )
        body = response.json()
    except (httpx.HTTPError, ValueError):
        return Probe(ms=_elapsed_ms(started), error=True)
    elapsed = _elapsed_ms(started)
    if response.status_code != 200 or not isinstance(body, dict):
        return Probe(ms=elapsed, error=True)
    if body.get("code", 0) != 0:
        return Probe(ms=elapsed, error=True)
    data = body.get("data")
    chunks = data.get("chunks") if isinstance(data, dict) else None
    if not isinstance(chunks, list):
        return Probe(ms=elapsed, error=True)
    return Probe(ms=elapsed, empty=not chunks)


async def run_stream(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    chat_id: str,
    question: str,
) -> StreamProbe:
    """Jedno pytanie czatu strumieniem SSE (C5): TTFB i czas do końca strumienia.

    TTFB to chwila pierwszej ramki z niepustym ``answer``, a gdy takiej nie ma —
    pierwszej ramki ``data:`` (C5). Koniec strumienia to ramka finalna (``data``
    równe true) albo sentynel końca trybu OpenAI; brak obu kończy się z końcem
    odpowiedzi. HTTP != 200 albo ``code != 0`` w ramce to błąd (poza opóźnieniami).
    """
    started = time.perf_counter()
    first_ms: float | None = None
    answer_ms: float | None = None
    try:
        async with client.stream(
            "POST",
            f"/api/v1/chats/{chat_id}/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"question": question, "stream": True},
        ) as response:
            if response.status_code != 200:
                await response.aread()
                return StreamProbe(ttfb_ms=None, total_ms=_elapsed_ms(started), error=True)
            async for line in response.aiter_lines():
                frame = parse_sse_line(line)
                if frame is None:
                    continue
                if isinstance(frame, dict) and frame.get("code", 0) != 0:
                    return StreamProbe(ttfb_ms=None, total_ms=_elapsed_ms(started), error=True)
                if first_ms is None:
                    first_ms = _elapsed_ms(started)
                data = frame.get("data") if isinstance(frame, dict) else None
                if answer_ms is None and isinstance(data, dict) and data.get("answer"):
                    answer_ms = _elapsed_ms(started)
                if is_final_frame(frame):
                    break
    except httpx.HTTPError:
        return StreamProbe(ttfb_ms=None, total_ms=_elapsed_ms(started), error=True)
    return StreamProbe(
        ttfb_ms=answer_ms if answer_ms is not None else first_ms,
        total_ms=_elapsed_ms(started),
    )


async def _retrieval_series(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    dataset_ids: list[str],
    questions: list[str],
) -> list[Probe]:
    """Seria jednego klienta: rozgrzewka (nieliczona) i próbki (C5)."""
    for question in questions[:WARMUP_QUERIES]:
        await run_retrieval(client, api_key=api_key, dataset_ids=dataset_ids, question=question)
    probes: list[Probe] = []
    for question in questions[WARMUP_QUERIES:]:
        probes.append(
            await run_retrieval(client, api_key=api_key, dataset_ids=dataset_ids, question=question)
        )
    return probes


async def _retrieval_parallel(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    dataset_ids: list[str],
    questions: list[str],
    clients: int,
) -> list[Probe]:
    """``clients`` równoległych klientów, każdy z własną rozgrzewką i próbkami (S4)."""
    batches = await asyncio.gather(
        *(
            _retrieval_series(client, api_key=api_key, dataset_ids=dataset_ids, questions=questions)
            for _ in range(clients)
        )
    )
    return [probe for batch in batches for probe in batch]


async def _stream_series(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    chat_id: str,
    questions: list[str],
) -> list[StreamProbe]:
    """Seria jednego klienta czatu: rozgrzewka (nieliczona) i próbki (S5)."""
    for question in questions[:WARMUP_QUERIES]:
        await run_stream(client, api_key=api_key, chat_id=chat_id, question=question)
    probes: list[StreamProbe] = []
    for question in questions[WARMUP_QUERIES:]:
        probes.append(await run_stream(client, api_key=api_key, chat_id=chat_id, question=question))
    return probes


def _retrieval_totals(probes: list[Probe]) -> tuple[list[float], int, int]:
    """Z prób retrievalu: (opóźnienia udanych, puste wyniki, błędy) — C5."""
    latency = [probe.ms for probe in probes if not probe.error and not probe.empty]
    empty = sum(1 for probe in probes if probe.empty and not probe.error)
    errors = sum(1 for probe in probes if probe.error)
    return latency, empty, errors


async def run_scenario(
    scenario: str,
    manifest: dict[str, Any],
    *,
    api: str,
    n: int,
    seed: int,
) -> dict[str, Any]:
    """Uruchamia scenariusz C5 na stosie i zwraca wynik w kształcie JSON kontraktu.

    ``wall_s`` obejmuje rozgrzewki (mierzy realne obciążenie), a ``rps`` to liczba
    próbek przez ten czas. Puste i błędne odpowiedzi nie wchodzą do opóźnień (C5).
    """
    layout, selection, clients = SCENARIOS[scenario]
    manifest_layout = str(manifest["layout"])
    if manifest_layout != layout:
        raise BenchError(f"{scenario} wymaga układu {layout}, manifest ma {manifest_layout}")
    available = [str(dataset_id) for dataset_id in manifest["dataset_ids"]]
    dataset_ids = available if selection == "all" else available[:1]
    api_key = str(manifest["api_key"])
    questions = corpus.queries(seed, n + WARMUP_QUERIES)
    load_before = list(os.getloadavg())
    started_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    started = time.perf_counter()
    ttfb: list[float] | None = None
    async with httpx.AsyncClient(base_url=api, timeout=HTTP_TIMEOUT_S) as client:
        if scenario == "S5":
            streams = await _stream_series(
                client, api_key=api_key, chat_id=str(manifest["chat_id"]), questions=questions
            )
            latency = [probe.total_ms for probe in streams if not probe.error]
            ttfb = [
                probe.ttfb_ms for probe in streams if not probe.error and probe.ttfb_ms is not None
            ]
            empty = 0
            errors = sum(1 for probe in streams if probe.error)
        elif clients > 1:
            parallel = await _retrieval_parallel(
                client,
                api_key=api_key,
                dataset_ids=dataset_ids,
                questions=questions,
                clients=clients,
            )
            latency, empty, errors = _retrieval_totals(parallel)
        else:
            series = await _retrieval_series(
                client, api_key=api_key, dataset_ids=dataset_ids, questions=questions
            )
            latency, empty, errors = _retrieval_totals(series)
    wall_s = round(time.perf_counter() - started, 3)
    result = build_result(
        scenario=scenario,
        layout=layout,
        dim=int(manifest["dim"]),
        chunks=int(manifest["chunks"]),
        datasets=len(dataset_ids),
        seed=seed,
        n_queries=n,
        concurrency=clients,
        api=api,
        latency_ms=latency or [0.0],
        ttfb_ms=ttfb if ttfb else None,
        empty_results=empty,
        errors=errors,
        wall_s=wall_s,
        started_at=started_at,
        load_before=load_before,
        load_after=list(os.getloadavg()),
    )
    if not latency:
        result["latency_ms"] = dict(ZERO_SUMMARY)
        result["rps"] = 0.0
    if ttfb is not None and not ttfb:
        result["ttfb_ms"] = dict(ZERO_SUMMARY)
    return result


def write_result(path: str, result: dict[str, Any]) -> None:
    """Zapisuje wynik JSON (katalog tworzony, gdy brakuje)."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


def read_manifest(path: str) -> dict[str, Any]:
    """Wczytuje manifest seedu (T2); brak pliku to BenchError."""
    try:
        return json.loads(Path(path).read_text())  # type: ignore[no-any-return]
    except OSError as error:
        raise BenchError(f"nie mogę wczytać manifestu {path}: {error}") from error


def _sql_string(value: str) -> str:
    """Wartość jako literał SQL — wyłącznie dla ``EXPLAIN``, który nie wiąże parametrów."""
    return "'" + value.replace("'", "''") + "'"


def _render_sql(statement: TextClause, values: dict[str, str]) -> str:
    """Wstawia wartości w tekst zapytania z repozytorium (tylko do ``EXPLAIN``)."""
    sql = statement.text
    for name, value in values.items():
        sql = sql.replace(f":{name}", value)
    return sql


async def explain(manifest: dict[str, Any], db_host: str, db_port: int) -> None:
    """Wypisuje ``ANALYZE FORMAT=JSON`` zapytań wektorowego i pełnotekstowego (C5).

    Kształt zapytań bierzemy z repozytorium retrievalu (``_vector_sql``/``_fulltext_sql``
    w wariancie bez filtra dokumentów), a wartości wstawiamy w tekst, bo ``ANALYZE``
    nie przyjmuje parametrów wiązanych. ``@qv`` ustawiamy w tej samej sesji co ``SELECT``.
    """
    dim = int(manifest["dim"])
    manifest_seed = int(manifest["seed"])
    question = corpus.queries(manifest_seed, 1)[0]
    dataset_ids = [str(dataset_id) for dataset_id in manifest["dataset_ids"]]
    in_datasets = "(" + ", ".join(_sql_string(dataset_id) for dataset_id in dataset_ids) + ")"
    scope = {"ds": in_datasets, "limit": str(int(RETRIEVAL_PARAMS["top_k"]))}
    vector_sql = _render_sql(_vector_sql(dim, with_docs=False), scope)
    fulltext_scope = scope | {
        "q_raw": _sql_string(ft_text(question)),
        "q_stem": _sql_string(stem_text(question)),
    }
    fulltext_sql = _render_sql(_fulltext_sql(with_docs=False), fulltext_scope)
    vector = struct.unpack(f"<{dim}f", corpus.vector_pool(manifest_seed, dim)[0])
    engine = seed.make_engine(db_host, db_port)
    try:
        async with engine.connect() as connection:
            await connection.execute(
                text("SET @qv = VEC_FromText(:qv)"), {"qv": json.dumps(list(vector))}
            )
            for name, sql in (("vector", vector_sql), ("fulltext", fulltext_sql)):
                plan = (await connection.exec_driver_sql(f"ANALYZE FORMAT=JSON {sql}")).scalar()
                print(f"--- {name} ---")
                print(json.dumps(json.loads(plan), indent=2))
    finally:
        await engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    """CLI benchu wg C5: scenariusze (domyślnie) oraz podkomenda ``explain``."""
    parser = argparse.ArgumentParser(
        prog="wdperf.bench", description="Scenariusze wydajnościowe WD (C5)"
    )
    parser.add_argument("--manifest", help="manifest seedu z T2")
    parser.add_argument("--api", help="bazowy URL API WD, np. http://host:port")
    parser.add_argument("--scenario", choices=tuple(SCENARIOS))
    parser.add_argument("--n", type=int, default=50, help="liczba mierzonych zapytań")
    parser.add_argument(
        "--seed", type=int, default=None, help="ziarno pytań (domyślnie z manifestu)"
    )
    parser.add_argument("--out", help="ścieżka wyniku JSON")
    subparsers = parser.add_subparsers(dest="command")
    explain_parser = subparsers.add_parser("explain", help="ANALYZE FORMAT=JSON zapytań (C5)")
    explain_parser.add_argument("--manifest", required=True, help="manifest seedu z T2")
    explain_parser.add_argument("--db-host", required=True)
    explain_parser.add_argument("--db-port", type=int, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point CLI; rc 0 gdy bieg się powiódł, 1 gdy wynik ma błędy (C5)."""
    args = build_parser().parse_args(argv)
    if args.command == "explain":
        try:
            asyncio.run(explain(read_manifest(args.manifest), args.db_host, args.db_port))
        except (BenchError, SeedError, SQLAlchemyError, httpx.HTTPError, OSError, ValueError) as e:
            print(f"bench: {e}", file=sys.stderr)
            return 1
        return 0
    missing = [name for name in ("manifest", "api", "scenario", "out") if not getattr(args, name)]
    if missing:
        print(f"bench: brakuje argumentów: {', '.join(missing)}", file=sys.stderr)
        return 1
    try:
        manifest = read_manifest(args.manifest)
        seed_value = int(manifest["seed"]) if args.seed is None else args.seed
        result = asyncio.run(
            run_scenario(args.scenario, manifest, api=args.api, n=args.n, seed=seed_value)
        )
    except (BenchError, httpx.HTTPError, OSError, ValueError) as error:
        print(f"bench: {error}", file=sys.stderr)
        return 1
    write_result(args.out, result)
    print(
        f"bench: {result['scenario']} n={result['latency_ms']['n']}"
        f" errors={result['errors']} empty={result['empty_results']} -> {args.out}"
    )
    return 1 if (result["errors"] or result["empty_results"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
