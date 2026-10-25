"""Masowy seed korpusu wydajnościowego (kontrakt C4, WP E5-1 T2).

Reset stosu testowego, model/datasety/czat przez autoryzowane API WD, a potem masowy
zapis dokumentów, chunków i wektorów. Chunki i wektory idą własnym INSERT-em (identyczny
zestaw kolumn co ``app.db.repositories.chunks``), bo repozytorium ``insert_many`` wymusza
``committed=0`` i ``task_id`` typu int. Wektory wstawiamy surowymi bajtami float32 LE
(bez konwersji tekstowej ``VEC_FromText`` — jak w spike'u SP-1). Manifest JSON jest
wejściem dla ``wdperf.bench``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import xxhash
from app.core.ids import new_chunk_id, new_id
from app.core.timeutil import from_ms
from app.db.repositories import chunk_vectors as chunk_vectors_repo
from app.db.repositories import datasets as datasets_repo
from app.db.repositories import models as models_repo
from app.db.repositories.documents import DocumentRow
from app.db.repositories.documents import insert as insert_document
from app.db.uow import transaction
from app.services.datasets import DEFAULT_PARSER_CONFIG
from app.storage.keys import document_key
from app.text.fulltext import ft_text, stem_text
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from wdperf import corpus

# Postęp na stderr co tyle chunków (C4 p. 2).
PROGRESS_STEP = 10_000
# Wsad commitowany jednorazowo: 10 dokumentów po 100 chunków (C4).
DOCS_PER_BATCH = 10
# Liczba zapytań kontrolnych trafień FULLTEXT w manifeście (C4).
FULLTEXT_QUERIES = 50
# Nazwy zmiennych środowiskowych z danymi logowania do bazy (tools/dev/up.sh test env).
DB_USER_ENV = "WD_DB_USER"
DB_PASSWORD_ENV = "WD_DB_PASSWORD"
DB_NAME_ENV = "WD_DB_NAME"


class SeedError(RuntimeError):
    """Seed nie zakończył się poprawnie (np. brak trafień FULLTEXT)."""


# Nazwy datasetów układu `multi` (C4).
_MULTI_NAMES: tuple[str, ...] = tuple(f"perf-multi-{i:02d}" for i in range(10))


@dataclass(frozen=True)
class Layout:
    """Układ korpusu: nazwy datasetów, ich liczba i globalna liczba dokumentów."""

    names: tuple[str, ...]
    datasets: int
    docs: int


def plan_layout(layout: str, chunks: int) -> Layout:
    """Liczba datasetów i dokumentów dla układu `single`/`multi` (C4).

    ``single``: 1 dataset `perf-single`; ``multi``: 10 datasetów `perf-multi-00..09`.
    Dokument chunka ``i`` to ``i // 100``, a dataset w ``multi`` to ``(i // 100) % 10``
    — ``docs`` to liczba dokumentów CAŁEGO korpusu, nie pojedynczego datasetu.
    """
    if chunks <= 0 or chunks % corpus.CHUNKS_PER_DOC != 0:
        raise ValueError(f"chunks must be a positive multiple of {corpus.CHUNKS_PER_DOC}")
    docs = chunks // corpus.CHUNKS_PER_DOC
    if layout == "single":
        return Layout(("perf-single",), 1, docs)
    if layout == "multi":
        if docs % len(_MULTI_NAMES) != 0:
            raise ValueError(
                f"multi needs chunks divisible by {len(_MULTI_NAMES) * corpus.CHUNKS_PER_DOC}"
            )
        return Layout(_MULTI_NAMES, len(_MULTI_NAMES), docs)
    raise ValueError(f"unknown layout: {layout}")


# Identyczny zestaw kolumn co `_INSERT_MANUAL_SQL` repozytorium chunks:
# task_id NULL i committed=1 (chunki istnieją od razu, bez rozliczania zadania).
_INSERT_CHUNKS_SQL = text(
    "INSERT INTO chunks (id, document_id, dataset_id, ordinal, chunk_type, content,"
    " content_llm, content_ft, content_stem, title_ft, keywords, questions, important_ft,"
    " question_ft, positions, page_from, page_to, task_id, available, committed,"
    " token_count, embed_source, create_time, create_date, update_time, update_date)"
    " VALUES (:id, :document_id, :dataset_id, :ordinal, 'text', :content, NULL, :content_ft,"
    " :content_stem, :title_ft, '[]', '[]', '', '', NULL, NULL, NULL, NULL, 1, 1,"
    " :token_count, 'content', :now, :now_date, :now, :now_date)"
)

_FULLTEXT_COUNT_SQL = text(
    "SELECT COUNT(*) FROM chunks WHERE MATCH(content_ft) AGAINST(:q IN BOOLEAN MODE)"
)


def _vector_insert_sql(dim: int) -> str:
    """INSERT wektora surowymi bajtami — nazwa tabeli wyłącznie z ``table_name(dim)``."""
    # Nazwa tabeli z walidowanego int (C2.4) — identyfikator, nie wartość.
    return (
        f"INSERT INTO {chunk_vectors_repo.table_name(dim)}"
        " (chunk_id, dataset_id, embedding)"
        " VALUES (:chunk_id, :dataset_id, :embedding)"
    )


def _db_env(name: str) -> str:
    """Wartość zmiennej środowiskowej albo SeedError (brak konfiguracji bazy)."""
    value = os.environ.get(name)
    if not value:
        raise SeedError(f"missing environment variable {name}")
    return value


def database_url(db_host: str, db_port: int) -> URL:
    """URL MariaDB: host i port z CLI, użytkownik/hasło/baza z env (C4)."""
    return URL.create(
        drivername="mysql+asyncmy",
        username=_db_env(DB_USER_ENV),
        password=_db_env(DB_PASSWORD_ENV),
        host=db_host,
        port=db_port,
        database=_db_env(DB_NAME_ENV),
        query={"charset": "utf8mb4"},
    )


def make_engine(db_host: str, db_port: int) -> AsyncEngine:
    """Silnik asyncmy do bazy stosu; testy używają go do asercji SQL."""
    return create_async_engine(database_url(db_host, db_port), pool_pre_ping=True)


def build_parser() -> argparse.ArgumentParser:
    """CLI seedu wg C4 (``python -m wdperf.seed ...``)."""
    parser = argparse.ArgumentParser(prog="wdperf.seed", description="Masowy seed korpusu perf")
    parser.add_argument("--layout", choices=("single", "multi"), required=True)
    parser.add_argument("--dim", type=int, choices=(1024, 3072), required=True)
    parser.add_argument("--chunks", type=int, default=100_000)
    parser.add_argument("--seed", type=int, default=corpus.SEED_DEFAULT)
    parser.add_argument("--api", required=True, help="bazowy URL API WD, np. http://host:port")
    parser.add_argument("--db-host", required=True)
    parser.add_argument("--db-port", type=int, required=True)
    parser.add_argument("--out", required=True, help="ścieżka manifestu JSON")
    return parser


async def _api(
    client: httpx.AsyncClient,
    path: str,
    body: dict[str, Any],
    headers: dict[str, str] | None,
) -> dict[str, Any]:
    """POST do API WD; HTTP != 200 albo ``code`` obecne i != 0 → SeedError z odpowiedzią.

    Reset testowy (``/api/wd/v1/test/reset``) zwraca samą kopertę ``{"data": ...}``,
    bez ``code`` — brak klucza traktujemy jak sukces (K9 §4).
    """
    response = await client.post(path, json=body, headers=headers)
    payload = response.json()
    if response.status_code != 200 or payload.get("code", 0) != 0:
        raise SeedError(f"{path}: HTTP {response.status_code}: {payload}")
    return payload


async def ensure_embedding_model(
    sessionmaker: async_sessionmaker[AsyncSession], name: str, dim: int, now_ms: int
) -> None:
    """Model embeddingu `fake-embed-<dim>` o wymiarze `dim` (insert jak TEST_MODELS resetu)."""
    async with transaction(sessionmaker) as session:
        if await models_repo.get_by_name(session, name, "embedding") is not None:
            return
        model_id = new_id()
        await models_repo.insert(
            session,
            id=model_id,
            name=name,
            model_type="embedding",
            is_default=False,
            now_ms=now_ms,
        )
        await models_repo.set_dimension_if_null(session, model_id, dim, now_ms)


def _document(
    index: int, dataset_id: str, created_by: str, content: str, tokens: int, now_ms: int
) -> DocumentRow:
    """Wiersz `documents` w stanie DONE (run='3'), z pełnym licznikiem chunków (C4)."""
    document_id = new_id()
    return DocumentRow(
        id=document_id,
        dataset_id=dataset_id,
        created_by=created_by,
        name=corpus.doc_name(index),
        suffix="txt",
        type="doc",
        size=len(content.encode()),
        location=str(document_key(dataset_id, document_id, "txt")),
        content_hash=xxhash.xxh128_hexdigest(content.encode()),
        source_type="local",
        source_ref=None,
        chunk_method="naive",
        parser_config=dict(DEFAULT_PARSER_CONFIG),
        run="3",
        progress=1.0,
        progress_msg="",
        error=None,
        process_begin_at=now_ms,
        process_duration=0.0,
        chunk_count=corpus.CHUNKS_PER_DOC,
        token_count=tokens,
        enabled=True,
        meta_fields={},
        thumbnail=None,
        create_time=now_ms,
        create_date=from_ms(now_ms),
        update_time=now_ms,
        update_date=from_ms(now_ms),
    )


def _chunk_params(
    chunk_id: str,
    document_id: str,
    dataset_id: str,
    ordinal: int,
    chunk: str,
    title_ft: str,
    now_ms: int,
) -> dict[str, Any]:
    """Parametry INSERT chunka: FULLTEXT i stem z `app.text.fulltext` (C4)."""
    return {
        "id": chunk_id,
        "document_id": document_id,
        "dataset_id": dataset_id,
        "ordinal": ordinal,
        "content": chunk,
        "content_ft": ft_text(chunk),
        "content_stem": stem_text(chunk),
        "title_ft": title_ft,
        "token_count": len(chunk.split()),
        "now": now_ms,
        "now_date": from_ms(now_ms),
    }


async def _seed_chunks(
    sessionmaker: async_sessionmaker[AsyncSession],
    layout: Layout,
    dataset_ids: list[str],
    created_by: str,
    args: argparse.Namespace,
    pool: list[bytes],
    now_ms: int,
) -> None:
    """Dokumenty, chunki i wektory partiami po `DOCS_PER_BATCH` dokumentów na commit (C4)."""
    vector_sql = text(_vector_insert_sql(args.dim))
    for start in range(0, layout.docs, DOCS_PER_BATCH):
        stop = min(start + DOCS_PER_BATCH, layout.docs)
        documents: list[DocumentRow] = []
        chunk_params: list[dict[str, Any]] = []
        vector_params: list[dict[str, Any]] = []
        for index in range(start, stop):
            dataset_id = dataset_ids[index % layout.datasets]
            texts = [
                corpus.chunk_text(args.seed, index * corpus.CHUNKS_PER_DOC + ordinal)
                for ordinal in range(corpus.CHUNKS_PER_DOC)
            ]
            content = "\n".join(texts)
            document = _document(
                index,
                dataset_id,
                created_by,
                content,
                sum(len(chunk.split()) for chunk in texts),
                now_ms,
            )
            title_ft = ft_text(Path(document.name).stem)
            documents.append(document)
            for ordinal, chunk in enumerate(texts):
                chunk_id = new_chunk_id(document.id, ordinal, chunk)
                chunk_params.append(
                    _chunk_params(
                        chunk_id, document.id, dataset_id, ordinal, chunk, title_ft, now_ms
                    )
                )
                vector_params.append(
                    {
                        "chunk_id": chunk_id,
                        "dataset_id": dataset_id,
                        "embedding": corpus.chunk_vector(
                            pool, args.seed, index * corpus.CHUNKS_PER_DOC + ordinal
                        ),
                    }
                )
        async with transaction(sessionmaker) as session:
            for document in documents:
                await insert_document(session, document)
            await session.execute(_INSERT_CHUNKS_SQL, chunk_params)
            await session.execute(vector_sql, vector_params)
        done = stop * corpus.CHUNKS_PER_DOC
        if done % PROGRESS_STEP == 0 or done == args.chunks:
            print(f"seed: {done}/{args.chunks} chunków", file=sys.stderr)


async def _recount_datasets(
    sessionmaker: async_sessionmaker[AsyncSession], dataset_ids: list[str], now_ms: int
) -> None:
    """Przelicza liczniki datasetów z dokumentów (jak ``datasets_repo.recount`` w ingestii).

    Bez tego ``datasets.chunk_count`` zostaje 0 i API czatu odrzuca datasety
    komunikatem „doesn't own parsed file”.
    """
    async with transaction(sessionmaker) as session:
        for dataset_id in dataset_ids:
            await datasets_repo.recount(session, dataset_id, now_ms=now_ms)


async def _analyze(sessionmaker: async_sessionmaker[AsyncSession], dim: int) -> None:
    """``ANALYZE TABLE`` dokumentów, chunków i wektorów po seedzie (C4)."""
    # Nazwy z listy stałych i `table_name(dim)` — identyfikatory, nie wartości użytkownika.
    tables = ("documents", "chunks", chunk_vectors_repo.table_name(dim))
    async with transaction(sessionmaker) as session:
        for table in tables:
            await session.execute(text(f"ANALYZE TABLE {table}"))


async def fulltext_hits_min(sessionmaker: async_sessionmaker[AsyncSession], seed: int) -> int:
    """Min liczba trafień FULLTEXT po `FULLTEXT_QUERIES` zapytaniach ``queries(seed+1, 50)``."""
    queries = corpus.queries(seed + 1, FULLTEXT_QUERIES)
    counts: list[int] = []
    async with transaction(sessionmaker) as session:
        for query in queries:
            result = await session.execute(_FULLTEXT_COUNT_SQL, {"q": ft_text(query)})
            counts.append(int(result.scalar_one()))
    return min(counts)


def _write_manifest(path: str, manifest: dict[str, Any]) -> None:
    """Zapisuje manifest JSON (katalog tworzony, gdy brakuje)."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")


async def seed(args: argparse.Namespace) -> dict[str, Any]:
    """Reset, modele/datasety/czat przez API, masowy zapis danych i manifest (C4).

    Zwraca treść manifestu (zapisanego także w ``args.out``). ``fulltext_hits_min == 0``
    to SeedError — korpus bez trafień FULLTEXT nie nadaje się do benchu.
    """
    layout = plan_layout(args.layout, args.chunks)
    model_name = f"fake-embed-{args.dim}"
    now_ms = int(time.time() * 1000)
    engine = make_engine(args.db_host, args.db_port)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with httpx.AsyncClient(base_url=args.api, timeout=120.0) as client:
            reset = (await _api(client, "/api/wd/v1/test/reset", {}, None))["data"]
            api_key = str(reset["api_key"])
            admin_user_id = str(reset["admin_user_id"])
            await ensure_embedding_model(sessionmaker, model_name, args.dim, now_ms)
            headers = {"Authorization": f"Bearer {api_key}"}
            dataset_ids: list[str] = []
            for name in layout.names:
                payload = await _api(
                    client,
                    "/api/v1/datasets",
                    {"name": name, "embedding_model": f"{model_name}@fake"},
                    headers,
                )
                dataset_ids.append(str(payload["data"]["id"]))

            started = time.perf_counter()
            async with transaction(sessionmaker) as session:  # DDL = niejawny COMMIT
                await chunk_vectors_repo.ensure_table(session, args.dim)
            pool = corpus.vector_pool(args.seed, args.dim)
            await _seed_chunks(sessionmaker, layout, dataset_ids, admin_user_id, args, pool, now_ms)
            await _recount_datasets(sessionmaker, dataset_ids, now_ms)
            await _analyze(sessionmaker, args.dim)
            seed_seconds = round(time.perf_counter() - started, 3)

            # Czat dopiero po seedzie: walidacja datasetów wymaga niezerowego chunk_count
            # (app/services/chat_validation.py — „doesn't own parsed file”).
            chat = await _api(
                client,
                "/api/v1/chats",
                {"name": "perf-chat", "dataset_ids": dataset_ids},
                headers,
            )
            chat_id = str(chat["data"]["id"])
        hits_min = await fulltext_hits_min(sessionmaker, args.seed)
    finally:
        await engine.dispose()

    manifest: dict[str, Any] = {
        "layout": args.layout,
        "dim": args.dim,
        "seed": args.seed,
        "chunks": args.chunks,
        "api_key": api_key,
        "dataset_ids": dataset_ids,
        "chat_id": chat_id,
        "embedding_model": model_name,
        "seed_seconds": seed_seconds,
        "fulltext_hits_min": hits_min,
    }
    _write_manifest(args.out, manifest)
    if hits_min <= 0:
        raise SeedError("fulltext_hits_min == 0: korpus bez trafień FULLTEXT")
    return manifest


def main(argv: list[str] | None = None) -> int:
    """Entry point CLI; rc 1 gdy seed zgłosi błąd (manifest zostaje zapisany)."""
    args = build_parser().parse_args(argv)
    try:
        manifest = asyncio.run(seed(args))
    except (SeedError, ValueError) as error:
        print(f"seed: {error}", file=sys.stderr)
        return 1
    print(f"seed: {manifest['chunks']} chunków, manifest {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
