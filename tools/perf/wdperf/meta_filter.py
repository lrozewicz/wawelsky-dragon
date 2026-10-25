"""Pomiar filtra ``metadata_condition`` na 10 000 dokumentów (kontrakt C10, WP E6-1a T6).

Scenariusz SC-E6-1a-06: lista dokumentów z filtrem metadanych na dużym zbiorze nie jest
zauważalnie wolniejsza. Bieg zasiewa 10 000 dokumentów z ``meta_fields`` w JEDNYM
datasecie (bez parsowania — wiersze ``documents`` jak ``wdperf.seed._document``, bez
chunków i wektorów), a potem mierzy po HTTP ``GET /api/v1/datasets/{id}/documents``
z filtrem ``author = A`` AND ``year = "2020"`` (≈ 1-2% trafień): 3 próby rozgrzewki
(odrzucone) + 20 prób. Raportuje min/p50/p95/max w ms, liczbę trafień i wersję HEAD.

Część czysta (``AUTHORS``/``YEARS``/``TOPICS``, ``meta_fields_for``, ``expected_matches``,
``build_condition``, ``condition_json``, ``within_budget``) jest bez I/O i testowana bez
stosu; CLI (``python -m wdperf.meta_filter``) i pomiar HTTP dokładają warstwę sieciową.
Kod wyjścia != 0, gdy p95 > ``--budget-ms`` (domyślnie 200).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
from app.db.repositories.documents import insert as insert_document
from app.db.uow import transaction
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from wdperf import seed as seedmod
from wdperf import stats

# Parametry biegu (kontrakt C10 / brief T6).
DOCUMENTS_DEFAULT = 10_000
SAMPLES_DEFAULT = 20
WARMUP_DEFAULT = 3
BUDGET_MS_DEFAULT = 200.0
PAGE_SIZE_DEFAULT = 30
# Liczba dokumentów commitowanych jedną transakcją INSERT (jak ``seed.DOCS_PER_BATCH``).
DOCS_PER_BATCH = 500
# Nazwa datasetu i model embeddingu (bez wektorów — dobrany jak w ``wdperf.seed``).
DATASET_NAME = "perf-meta-10k"
EMBEDDING_MODEL = "fake-embed-1024"

# Rozkład ``meta_fields``: 12 autorów x 5 lat daje udział filtra ≈ (1/12)·(1/5) ≈ 1,67%.
AUTHORS: tuple[str, ...] = (
    "Adam Kowalski",
    "Ewa Nowak",
    "Jan Wiśniewski",
    "Anna Wójcik",
    "Piotr Kamiński",
    "Maria Lewandowska",
    "Tomasz Zieliński",
    "Katarzyna Szymańska",
    "Marek Woźniak",
    "Agnieszka Dąbrowska",
    "Paweł Kozłowski",
    "Zofia Jankowska",
)
YEARS: tuple[str, ...] = ("2018", "2019", "2020", "2021", "2022")
TOPICS: tuple[str, ...] = (
    "budżet",
    "energia",
    "transport",
    "edukacja",
    "zdrowie",
    "rolnictwo",
    "klimat",
    "rynek",
    "kultura",
    "bezpieczeństwo",
    "innowacje",
    "społeczeństwo",
    "gospodarka",
    "administracja",
    "nauka",
    "obronność",
    "infrastruktura",
    "sport",
    "turystyka",
    "środowisko",
)
# Wartości filtra: pierwszy autor i rok „2020" — pary (A, 2020) trafiają w ≈ 1,67% dokumentów.
FILTER_AUTHOR: str = AUTHORS[0]
FILTER_YEAR: str = "2020"

# Kształt zwracany przez ``stats.summarize`` (klucz p50 == ``median``).
SUMMARIZE_KEYS: tuple[str, ...] = ("n", "min", "median", "p95", "max")


class MetaFilterError(RuntimeError):
    """Bieg nie może się odbyć (zły klient/odpowiedź API, brak stosu)."""


def meta_fields_for(index: int) -> dict[str, str]:
    """Deterministyczne ``meta_fields`` dokumentu ``index``: ``{author, year, topic, note}``.

    ``author`` = ``AUTHORS[index % 12]``, ``year`` = ``YEARS[(index // 12) % 5]`` (dekorelacja
    od autora), ``topic`` wg ``TOPICS``, ``note`` z numerem dokumentu.
    """
    return {
        "author": AUTHORS[index % len(AUTHORS)],
        "year": YEARS[(index // len(AUTHORS)) % len(YEARS)],
        "topic": TOPICS[index % len(TOPICS)],
        "note": f"notatka {index:05d}",
    }


def matches_filter(meta: dict[str, str], author: str, year: str) -> bool:
    """Czy ``meta`` przechodzi filtr ``author = author`` AND ``year = year`` (semantyka jak API)."""
    return meta.get("author") == author and meta.get("year") == year


def expected_matches(documents: int, author: str = FILTER_AUTHOR, year: str = FILTER_YEAR) -> int:
    """Liczba dokumentów ``[0, documents)`` trafiających w filtr.

    Liczona z rozkładu ``meta_fields_for`` (autor = ``index % 12``, rok = ``(index // 12) % 5``).
    """
    return sum(
        1 for index in range(documents) if matches_filter(meta_fields_for(index), author, year)
    )


def build_condition(author: str = FILTER_AUTHOR, year: str = FILTER_YEAR) -> dict[str, Any]:
    """Warunek ``metadata_condition`` (filtr manual, 2 warunki, logika "and")."""
    return {
        "logic": "and",
        "conditions": [
            {"name": "author", "comparison_operator": "=", "value": author},
            {"name": "year", "comparison_operator": "=", "value": year},
        ],
    }


def condition_json(condition: dict[str, Any]) -> str:
    """Warunek jako zwarty JSON do parametru query ``metadata_condition`` (bez spacji)."""
    return json.dumps(condition, ensure_ascii=False, separators=(",", ":"))


def within_budget(summary: dict[str, Any], budget_ms: float) -> bool:
    """Czy p95 z podsumowania mieści się w budżecie (``<= budget_ms``)."""
    return float(summary["p95"]) <= budget_ms


def assert_total_matches(total: int, expected: int) -> None:
    """Filtr musi trafić dokładnie w ``expected`` dokumentów; inaczej bieg jest nieważny (rc 1)."""
    if total != expected:
        raise MetaFilterError(f"total {total} != expected_matches {expected}")


def verdict_text(within: bool) -> str:
    """Werdykt w brzmieniu briefu: „TAK"/„NIE"."""
    return "TAK" if within else "NIE"


def git_head() -> str:
    """Wersja HEAD biegu (``git rev-parse HEAD``); brak gita → "unknown"."""
    try:
        done = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover — brak gita w PATH
        return "unknown"
    return done.stdout.strip()


# ---------------------------------------------------------------------------
# Warstwa sieciowa: reset, seed dokumentów, pomiar HTTP.
# ---------------------------------------------------------------------------


async def _seed_documents(  # pragma: no cover — wymaga stosu (DB)
    sessionmaker: Any, dataset_id: str, created_by: str, documents: int, now_ms: int
) -> None:
    """Wstawia ``documents`` wierszy ``documents`` partiami (bez chunków i wektorów).

    Wiersz buduje ``seed._document`` (stan DONE), a ``meta_fields`` nadpisuje rozkładem
    ``meta_fields_for``; ``chunk_count`` zerujemy, bo dokumentów nie parsujemy.
    """
    for start in range(0, documents, DOCS_PER_BATCH):
        stop = min(start + DOCS_PER_BATCH, documents)
        async with transaction(sessionmaker) as session:
            for index in range(start, stop):
                row = seedmod._document(
                    index, dataset_id, created_by, f"perf meta doc {index}", 0, now_ms
                )
                row = replace(row, meta_fields=meta_fields_for(index), chunk_count=0)
                await insert_document(session, row)


async def _analyze(sessionmaker: Any) -> None:  # pragma: no cover — wymaga stosu (DB)
    """``ANALYZE TABLE documents`` po seedzie (statystyki optymalizatora, jak ``seed._analyze``)."""
    async with transaction(sessionmaker) as session:
        await session.execute(text("ANALYZE TABLE documents"))


async def _one(  # pragma: no cover — wymaga stosu (HTTP)
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    params: dict[str, Any],
) -> tuple[float, int]:
    """Jedno żądanie listy z filtrem: czas w ms do przeczytania odpowiedzi i ``total``.

    HTTP != 200 albo ``code != 0`` → ``MetaFilterError`` (pomiar bez stosu nie ma sensu).
    """
    started = time.perf_counter()
    response = await client.get(url, headers=headers, params=params)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    body = response.json()
    if response.status_code != 200 or body.get("code", 0) != 0:
        raise MetaFilterError(f"{url}: HTTP {response.status_code}: {body}")
    data = body["data"]
    return elapsed_ms, int(data["total"])


async def _measure(  # pragma: no cover — wymaga stosu (HTTP)
    client: Any,
    dataset_id: str,
    api_key: str,
    cond_json: str,
    *,
    warmup: int,
    samples: int,
    page_size: int,
) -> tuple[list[float], int]:
    """3 rozgrzewki (odrzucone) + ``samples`` mierzonych prób; zwraca (opóźnienia, total)."""
    url = f"/api/v1/datasets/{dataset_id}/documents"
    headers = {"Authorization": f"Bearer {api_key}"}
    params = {"metadata_condition": cond_json, "page": 1, "page_size": page_size}
    for _ in range(warmup):
        await _one(client, url, headers, params)
    latencies: list[float] = []
    total = 0
    for _ in range(samples):
        elapsed_ms, total = await _one(client, url, headers, params)
        latencies.append(elapsed_ms)
    return latencies, total


async def run(args: argparse.Namespace) -> dict[str, Any]:  # pragma: no cover — wymaga stosu
    """Reset stosu, seed 10k dokumentów, pomiar filtra HTTP; zwraca wynik w kształcie JSON."""
    now_ms = int(time.time() * 1000)
    condition = build_condition()
    cond_json = condition_json(condition)
    engine = seedmod.make_engine(args.db_host, args.db_port)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with httpx.AsyncClient(base_url=args.api, timeout=120.0) as client:
            reset = (await seedmod._api(client, "/api/wd/v1/test/reset", {}, None))["data"]
            api_key = str(reset["api_key"])
            admin_user_id = str(reset["admin_user_id"])
            await seedmod.ensure_embedding_model(sessionmaker, EMBEDDING_MODEL, 1024, now_ms)
            headers = {"Authorization": f"Bearer {api_key}"}
            created = await seedmod._api(
                client,
                "/api/v1/datasets",
                {"name": DATASET_NAME, "embedding_model": f"{EMBEDDING_MODEL}@fake"},
                headers,
            )
            dataset_id = str(created["data"]["id"])
            started = time.perf_counter()
            await _seed_documents(sessionmaker, dataset_id, admin_user_id, args.documents, now_ms)
            await _analyze(sessionmaker)
            seed_seconds = round(time.perf_counter() - started, 3)
            latencies, total = await _measure(
                client,
                dataset_id,
                api_key,
                cond_json,
                warmup=args.warmup,
                samples=args.samples,
                page_size=args.page_size,
            )
            expected = expected_matches(args.documents)
            assert_total_matches(total, expected)
    finally:
        await engine.dispose()
    summary = stats.summarize(latencies)
    within = within_budget(summary, args.budget_ms)
    return {
        "tool": "wdperf.meta_filter",
        "version": 1,
        "api": args.api,
        "documents": args.documents,
        "page_size": args.page_size,
        "warmup": args.warmup,
        "samples": args.samples,
        "condition": condition,
        "latency_ms": summary,
        "total_hits": total,
        "expected_matches": expected,
        "budget_ms": args.budget_ms,
        "within_budget": within,
        "verdict": verdict_text(within),
        "seed_seconds": seed_seconds,
        "head": git_head(),
    }


def write_result(path: str, result: dict[str, Any]) -> None:
    """Zapisuje wynik JSON (katalog tworzony, gdy brakuje)."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


def build_parser() -> argparse.ArgumentParser:
    """CLI pomiaru filtra (``python -m wdperf.meta_filter ...``)."""
    parser = argparse.ArgumentParser(
        prog="wdperf.meta_filter", description="Pomiar filtra metadata_condition na 10k (C10)"
    )
    parser.add_argument("--api", required=True, help="bazowy URL API WD, np. http://host:port")
    parser.add_argument("--db-host", required=True)
    parser.add_argument("--db-port", type=int, required=True)
    parser.add_argument("--documents", type=int, default=DOCUMENTS_DEFAULT)
    parser.add_argument("--samples", type=int, default=SAMPLES_DEFAULT)
    parser.add_argument("--warmup", type=int, default=WARMUP_DEFAULT)
    parser.add_argument("--page-size", type=int, default=PAGE_SIZE_DEFAULT)
    parser.add_argument("--budget-ms", type=float, default=BUDGET_MS_DEFAULT)
    parser.add_argument("--out", required=True, help="ścieżka wyniku JSON")
    return parser


def main(argv: list[str] | None = None) -> int:  # pragma: no cover — wymaga stosu
    """Entry point CLI; rc 1, gdy p95 > budżet albo bieg padnie (brief T6 wymaganie 2)."""
    args = build_parser().parse_args(argv)
    try:
        result = asyncio.run(run(args))
    except Exception as error:  # noqa: BLE001 — CLI: każdy błąd stosu/sieci → rc 1 z komunikatem
        print(f"meta_filter: {error}", file=sys.stderr)
        return 1
    write_result(args.out, result)
    summary = result["latency_ms"]
    print(
        f"meta_filter: n={summary['n']} min={summary['min']} p50={summary['median']}"
        f" p95={summary['p95']} max={summary['max']} ms total={result['total_hits']}"
        f" ({result['budget_ms']} ms: {result['verdict']}) -> {args.out}"
    )
    return 0 if result["within_budget"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
