"""Pomiar eksportu datasetu do paczki ``.wdkb.zip`` (brief E7-1a-T3b p. 1) — skrypt ręczny.

NIE jest zbierany przez pytest (brak prefiksu ``test_``). Uruchamia się na stosie testowym
(``eval "$(tools/dev/up.sh test env)"`` po ``tools/dev/up.sh test up mariadb-test fake-llm``):

    cd backend && uv run python tests/integration/kb_export_measure.py \\
        --chunks 7251 --dim 1024 --docs 3 --out /tmp/export.json

``--no-vectors`` mierzy wariant ``include_vectors=false`` (pomiar szacunku rozmiaru, E7-H1/T5).

Wzorem pomiaru E7-1b (``kb_import_measure.py``): świeża baza + migracje Alembic, syntetyczny
dataset „rocznika GUS" (domyślnie 7251 chunków po ~800 znaków losowych słów PL, 3 dokumenty —
jeden plik ~23 MB losowych bajtów — oraz wektory losowe znormalizowane o wymiarze ``--dim``).
Eksport zleca TRASA (``GET …/export/preview`` + ``POST …/export`` przez ASGI/HTTP w tym samym
procesie), a wykonuje HANDLER ``export_dataset`` pobrany z kolejki jak slot workera. Mierzymy:
czas zadania (``start`` → ``done``), rozmiar paczki oraz **przyrost RSS** (RSS po - RSS przed,
z ``/proc/self/statm``) i szczyt ``ru_maxrss``. Kryterium K19/brief: czas ≤ 3 min i przyrost
RSS ≤ 300 MB. Wynik zapisuje jako JSON (``--out``) i wypisuje czytelnie na stdout.

Uwaga: to NIE jest test regresyjny — to pomiar jednorazowy na stosie testowym. Generator danych
i seed nie trzymają całego datasetu w pamięci dłużej niż to konieczne (wektory wstawiane partiami).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import resource
import sys
import tempfile
import time
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

# Skrypt uruchamiany wprost — katalog skryptu nie jest katalogiem ``backend``, więc dokładamy go
# do ``sys.path`` jak robi to pytest.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx
import pymysql
from fastapi import FastAPI
from sqlalchemy import text

from alembic import command
from app.api.auth.principal import get_principal
from app.core.config import Settings
from app.core.container import Container
from app.core.timeutil import from_ms
from app.db.repositories import chunk_vectors as vectors_repo
from app.db.repositories import datasets as datasets_repo
from app.db.repositories import users as users_repo
from app.db.uow import transaction
from app.domain.policy import Principal
from app.main import create_app
from app.services.kb_export_link import export_package_path
from app.storage.keys import StorageKey, document_key
from app.worker.context import TaskContext
from app.worker.handlers.export_dataset import export_dataset
from app.worker.queue import DbTaskQueue
from tests.integration.db.helpers import alembic_cfg, worker_db_name

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

MODEL = "fake-embed-1024"  # nazwa modelu embeddingów w wierszu datasetu
CONTENT_CHARS = 800  # docelowa długość treści chunka (znaki)
BIG_BLOB_BYTES = 23 * 1024 * 1024  # ~23 MB losowych bajtów (brief p. 1)
SMALL_BLOB_BYTES = 20 * 1024  # rozmiar pliku pozostałych dokumentów (~20 KB)
VEC_BATCH = 500  # partia wstawiania wektorów w seedzie (bounded pamięć)
CHUNK_INSERT_BATCH = 1000  # partia wstawiania chunków w seedzie
HTTP_ACCEPTED = 202  # POST …/export zwraca 202 (K19 §3, trasa 2)
WORKER_ID = "measure:1:0"
PARSER_CONFIG: dict[str, Any] = {"chunk_token_num": 128, "delimiter": "\n"}
MiB = 1 << 20

# Kryterium K19/brief: czas i przyrost pamięci dla „rocznika GUS".
MAX_TASK_SECONDS = 180.0  # ≤ 3 min
MAX_RSS_GROWTH_BYTES = 300 * MiB  # ≤ 300 MB przyrostu RSS

# Krótki słownik polskich słów (deterministyczny generator treści chunków).
WORDS = [
    "rocznik",
    "gmina",
    "powiat",
    "wojewodztwo",
    "ludnosc",
    "bezrobocie",
    "wynagrodzenie",
    "gospodarstwo",
    "przemysl",
    "rolnictwo",
    "budownictwo",
    "handel",
    "transport",
    "edukacja",
    "zdrowie",
    "kultura",
    "turystyka",
    "inwestycja",
    "dochody",
    "wydatki",
    "budzet",
    "podatek",
    "demografia",
    "migracja",
    "zatrudnienie",
    "place",
    "produkcja",
    "eksport",
    "import",
    "uslugi",
    "mieszkalnictwo",
    "infrastruktura",
    "srodowisko",
    "emisja",
]


def _chunk_content(index: int) -> str:
    """Treść chunka ~``CONTENT_CHARS`` znaków z losowych słów PL (deterministyczna)."""
    rng = random.Random(index)  # noqa: S311 — generator z seedem, nie kryptografia
    parts: list[str] = []
    length = 0
    while length < CONTENT_CHARS:
        word = rng.choice(WORDS)
        parts.append(word)
        length += len(word) + 1
    return " ".join(parts)[:CONTENT_CHARS]


def _vector(index: int, dim: int) -> list[float]:
    """Losowy, znormalizowany L2 wektor wymiaru ``dim`` (deterministyczny per ``index``)."""
    rng = random.Random(random.Random(index).getrandbits(64))  # noqa: S311 — generator z seedem
    raw = [rng.gauss(0.0, 1.0) for _ in range(dim)]
    norm = sum(value * value for value in raw) ** 0.5 or 1.0
    return [value / norm for value in raw]


def _rss_bytes() -> int:
    """Bieżący RSS procesu w bajtach (``/proc/self/statm``: pole 2 = strony rezydentne)."""
    fields = Path("/proc/self/statm").read_text(encoding="ascii").split()
    return int(fields[1]) * os.sysconf("SC_PAGE_SIZE")


def _peak_rss_bytes() -> int:
    """Szczyt RSS procesu w bajtach (``resource.getrusage``; ``ru_maxrss`` w KiB na Linuksie)."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024


# --- baza i kontener ---------------------------------------------------------------------------


def _root_connection() -> pymysql.Connection:
    """Połączenie root do założenia i skasowania bazy pomiarowej (jak fixture ``fresh_db``)."""
    return pymysql.connect(
        host=os.environ["WD_DB_HOST"],
        port=int(os.environ["WD_DB_PORT"]),
        user="root",
        password=os.environ.get("WD_TEST_DB_ROOT_PASSWORD", "root-test"),
        autocommit=True,
    )


def _create_db(name: str) -> None:
    """Tworzy bazę pomiarową i nadaje prawa użytkownikowi ``wawelsky``."""
    connection = _root_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_uca1400_ai_ci"
            )
            cursor.execute(f"GRANT ALL PRIVILEGES ON `{name}`.* TO 'wawelsky'@'%'")
    finally:
        connection.close()


def _drop_db(name: str) -> None:
    """Kasuje bazę pomiarową (sprzątanie po biegu)."""
    connection = _root_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"DROP DATABASE IF EXISTS `{name}`")
    finally:
        connection.close()


# --- seed syntetycznego datasetu --------------------------------------------------------------


async def _seed_actor(container: Container) -> str:
    """Wstawia użytkownika-aktora (FK ``datasets.tenant_id`` → ``users``); zwraca jego id."""
    actor = uuid.uuid4().hex
    now = container.clock.now_ms()
    async with transaction(_sm(container)) as session:
        await users_repo.insert(
            session,
            user_id=actor,
            email=f"{actor[:12]}@example.com",
            nickname="Measure",
            password_hash=None,
            auth_source="local",
            oidc_sub=None,
            is_superuser=False,
            is_service=False,
            now_ms=now,
        )
    return actor


def _sessionmaker(container: Container) -> async_sessionmaker[AsyncSession]:
    """Fabryka sesji z kontenera; brak (kontener nie wystartował) → ``RuntimeError``."""
    sessionmaker = container.sessionmaker
    if sessionmaker is None:
        raise RuntimeError("container not started")
    return sessionmaker


_sm = _sessionmaker


async def _seed_dataset(container: Container, actor: str, *, dim: int) -> str:
    """Wstawia dataset o wymiarze ``dim`` w tenancie aktora; zwraca jego id."""
    dataset_id = container.id_gen.new_id()
    async with transaction(_sm(container)) as session:
        await datasets_repo.insert(
            session,
            id=dataset_id,
            tenant_id=actor,
            created_by=actor,
            name="Rocznik GUS",
            description="syntetyczny dataset pomiarowy",
            avatar=None,
            language="Polish",
            embedding_model=MODEL,
            embedding_dim=dim,
            permission="me",
            chunk_method="naive",
            parser_config=PARSER_CONFIG,
            now_ms=container.clock.now_ms(),
        )
    return dataset_id


async def _seed_document(  # noqa: PLR0913 — pełny wiersz dokumentu w seedzie
    container: Container,
    *,
    dataset_id: str,
    actor: str,
    document_id: str,
    name: str,
    blob: bytes,
    chunk_count: int,
) -> None:
    """Wgrywa blob dokumentu do storage i wstawia wiersz ``documents`` (``location`` z klucza)."""
    suffix = "pdf"
    location = document_key(dataset_id, document_id, suffix)
    await container.storage.put(StorageKey(location), blob)
    now = container.clock.now_ms()
    async with transaction(_sm(container)) as session:
        await session.execute(
            text(
                "INSERT INTO documents (id, dataset_id, created_by, name, suffix, type, size,"
                " location, content_hash, chunk_method, parser_config, run, progress_msg,"
                " chunk_count, token_count, meta_fields, create_time, create_date,"
                " update_time, update_date)"
                " VALUES (:id, :ds, :by, :name, :suffix, :type, :size, :location, :hash,"
                " 'naive', :pc, '3', :msg, :chunks, :tokens, :meta, :now, :now_date,"
                " :now, :now_date)"
            ),
            {
                "id": document_id,
                "ds": dataset_id,
                "by": actor,
                "name": name,
                "suffix": suffix,
                "type": "pdf",
                "size": len(blob),
                "location": location,
                "hash": "0" * 32,
                "pc": json.dumps(PARSER_CONFIG),
                "msg": "gotowe",
                "chunks": chunk_count,
                "tokens": 4,
                "meta": json.dumps({"doc": name}),
                "now": now,
                "now_date": from_ms(now).replace(tzinfo=None),
            },
        )


async def _seed_chunks(
    container: Container, *, dataset_id: str, document_ids: Sequence[str], chunks: int
) -> list[str]:
    """Wstawia ``chunks`` chunków ``committed=1`` rozłożonych po dokumentach; zwraca id-y.

    Chunki lecą partiami (jeden ``INSERT`` na partię), żeby seed nie trzymał tysiąca otwartych
    transakcji — porządek ``(document_id, ordinal)`` odpowiada kolejności eksportu.
    """
    docs = len(document_ids)
    chunk_ids: list[str] = []
    now = container.clock.now_ms()
    now_date = from_ms(now).replace(tzinfo=None)
    batch: list[dict[str, Any]] = []
    async with transaction(_sm(container)) as session:
        for index in range(chunks):
            chunk_id = uuid.uuid4().hex[:16]
            chunk_ids.append(chunk_id)
            batch.append(
                {
                    "id": chunk_id,
                    "doc": document_ids[index % docs],
                    "ds": dataset_id,
                    "ordinal": index // docs,
                    "content": _chunk_content(index),
                    "now": now,
                    "now_date": now_date,
                }
            )
            if len(batch) >= CHUNK_INSERT_BATCH:
                await _insert_chunk_batch(session, batch)
                batch = []
        if batch:
            await _insert_chunk_batch(session, batch)
    return chunk_ids


async def _insert_chunk_batch(session: AsyncSession, batch: list[dict[str, Any]]) -> None:
    """Wstawia partię chunków ``committed=1`` (kolumny pochodne FT puste jak w eksporcie)."""
    await session.execute(
        text(
            "INSERT INTO chunks (id, document_id, dataset_id, ordinal, chunk_type, content,"
            " content_ft, content_stem, title_ft, keywords, questions, important_ft,"
            " question_ft, tags, positions, image_id, available, committed, token_count,"
            " embed_source, create_time, create_date, update_time, update_date)"
            " VALUES (:id, :doc, :ds, :ordinal, 'text', :content, :content, '', '', '[]',"
            " '[]', '', '', '{}', NULL, NULL, 1, 1, 3, 'content',"
            " :now, :now_date, :now, :now_date)"
        ),
        batch,
    )


async def _seed_vectors(
    container: Container, *, dataset_id: str, dim: int, chunk_ids: Sequence[str]
) -> None:
    """Tworzy tabelę wektorów wymiaru ``dim`` i wstawia wektory chunków partiami."""
    async with transaction(_sm(container)) as session:
        await vectors_repo.ensure_table(session, dim)
    for start in range(0, len(chunk_ids), VEC_BATCH):
        part = chunk_ids[start : start + VEC_BATCH]
        rows = [
            (chunk_id, dataset_id, _vector(start + offset, dim))
            for offset, chunk_id in enumerate(part)
        ]
        async with transaction(_sm(container)) as session:
            await vectors_repo.insert_many(session, dim, rows)
        del rows


async def _seed(container: Container, args: argparse.Namespace) -> dict[str, Any]:
    """Cały seed: aktor, dataset, 3 dokumenty (jeden ~23 MB), chunki, wektory."""
    actor = await _seed_actor(container)
    dataset_id = await _seed_dataset(container, actor, dim=args.dim)
    document_ids = [container.id_gen.new_id() for _ in range(args.docs)]
    per_doc = args.chunks // args.docs + 1
    for index, document_id in enumerate(document_ids):
        size = BIG_BLOB_BYTES if index == 0 else SMALL_BLOB_BYTES
        blob = random.Random(index).randbytes(size)  # noqa: S311 — generator z seedem
        await _seed_document(
            container,
            dataset_id=dataset_id,
            actor=actor,
            document_id=document_id,
            name=f"rocznik-{index + 1}.pdf",
            blob=blob,
            chunk_count=per_doc,
        )
        del blob
    chunk_ids = await _seed_chunks(
        container, dataset_id=dataset_id, document_ids=document_ids, chunks=args.chunks
    )
    await _seed_vectors(container, dataset_id=dataset_id, dim=args.dim, chunk_ids=chunk_ids)
    return {"actor": actor, "dataset_id": dataset_id, "blob_bytes": BIG_BLOB_BYTES}


# --- trasa (ASGI) + handler -------------------------------------------------------------------


def _app(container: Container, principal: Principal) -> FastAPI:
    """Aplikacja ASGI z nadpisaniem aktora (jak testy tras WD)."""
    app = create_app(container.settings, container)
    app.dependency_overrides[get_principal] = lambda: principal
    return app


async def _start_via_route(
    client: httpx.AsyncClient, dataset_id: str, *, include_vectors: bool
) -> tuple[dict[str, Any], str]:
    """Podgląd (trasa 1) i zlecenie eksportu (trasa 2); zwraca ``(preview, task_id)``."""
    preview = (await client.get(f"/api/wd/v1/datasets/{dataset_id}/export/preview")).json()["data"]
    started = await client.post(
        f"/api/wd/v1/datasets/{dataset_id}/export", json={"include_vectors": include_vectors}
    )
    assert started.status_code == HTTP_ACCEPTED, started.text
    task_id = started.json()["data"]["task_id"]
    return preview, task_id


async def _run_task(container: Container, task_id: str) -> float:
    """Claim zadania i wykonanie handlera jak slot workera; zwraca czas ``start`` → ``done``."""
    queue = DbTaskQueue(_sm(container), container.clock, container.id_gen)
    task = await queue.claim(WORKER_ID, ["export_dataset"])
    assert task is not None and task.id == task_id, "zadanie eksportu musi być do wzięcia"
    logger: logging.LoggerAdapter[logging.Logger] = logging.LoggerAdapter(
        logging.getLogger("measure.export_dataset"), {"task_id": task.id}
    )
    ctx = TaskContext(
        task=task, worker_id=WORKER_ID, container=container, logger=logger, queue=queue
    )
    started_at = time.perf_counter()
    await export_dataset(task, ctx)
    await queue.complete(task.id, WORKER_ID)
    return time.perf_counter() - started_at


async def _run_export(args: argparse.Namespace, settings: Settings) -> dict[str, Any]:
    """Bieg async: seed → trasa → handler; mierzy czas zadania i przyrost RSS."""
    container = Container(settings)
    await container.start()
    try:
        seeded = await _seed(container, args)
        principal = Principal(
            seeded["actor"], f"{seeded['actor'][:12]}@example.com", False, False, "jwt"
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_app(container, principal)), base_url="http://test"
        ) as client:
            preview, task_id = await _start_via_route(
                client, seeded["dataset_id"], include_vectors=args.vectors
            )
        rss_before = _rss_bytes()
        task_seconds = await _run_task(container, task_id)
        rss_after = _rss_bytes()
        path = export_package_path(settings.storage_root, task_id)
        package_bytes = path.stat().st_size
    finally:
        await container.aclose()
    return {
        "preview": preview,
        "task_id": task_id,
        "task_seconds": task_seconds,
        "package_bytes": package_bytes,
        "rss_before_bytes": rss_before,
        "rss_after_bytes": rss_after,
    }


def _measure(args: argparse.Namespace) -> dict[str, Any]:
    """Cały bieg pomiarowy: świeża baza, seed, trasa+handler, czas, rozmiar paczki, pamięć.

    Baza i migracje Alembic idą SYNCHRONICZNIE (``env.py`` woła ``asyncio.run``) — dopiero potem
    startuje pętla zdarzeń z kontenerem, seedem, klientem ASGI i handlerem.
    """
    db_name = worker_db_name("wd_measure_export")
    settings = Settings(env="test", db_name=db_name, storage_root=str(args.workdir / "storage"))
    _create_db(db_name)
    try:
        command.upgrade(alembic_cfg(settings), "head")
        run = asyncio.run(_run_export(args, settings))
    finally:
        _drop_db(db_name)
    growth = run["rss_after_bytes"] - run["rss_before_bytes"]
    return {
        "chunks": args.chunks,
        "dim": args.dim,
        "documents": args.docs,
        "include_vectors": args.vectors,
        "package_bytes": run["package_bytes"],
        "package_mib": round(run["package_bytes"] / MiB, 1),
        "preview_estimated_bytes": run["preview"]["estimated_bytes"],
        "preview_estimated_bytes_with_vectors": run["preview"]["estimated_bytes_with_vectors"],
        "task_seconds": round(run["task_seconds"], 2),
        "rss_before_mib": round(run["rss_before_bytes"] / MiB, 1),
        "rss_after_mib": round(run["rss_after_bytes"] / MiB, 1),
        "rss_growth_bytes": growth,
        "rss_growth_mib": round(growth / MiB, 1),
        "peak_rss_mib": round(_peak_rss_bytes() / MiB, 1),
        "limit_task_seconds": MAX_TASK_SECONDS,
        "limit_rss_growth_mib": MAX_RSS_GROWTH_BYTES // MiB,
        "within_time": run["task_seconds"] <= MAX_TASK_SECONDS,
        "within_memory": growth <= MAX_RSS_GROWTH_BYTES,
    }


def main() -> None:
    """Punkt wejścia CLI: parsuje argumenty, mierzy eksport i wypisuje wynik."""
    parser = argparse.ArgumentParser(
        description="Pomiar eksportu datasetu do paczki ``.wdkb.zip``."
    )
    parser.add_argument("--chunks", type=int, default=7251, help="liczba chunków w datasecie")
    parser.add_argument("--dim", type=int, default=1024, help="wymiar wektorów")
    parser.add_argument("--docs", type=int, default=3, help="liczba dokumentów")
    parser.add_argument(
        "--no-vectors",
        dest="vectors",
        action="store_false",
        help="eksport bez wektorów (``include_vectors=false``; pomiar E7-H1/T5)",
    )
    parser.add_argument("--out", type=Path, default=None, help="plik JSON z wynikiem pomiaru")
    parser.add_argument(
        "--workdir", type=Path, default=None, help="katalog roboczy (domyślnie świeży temp)"
    )
    args = parser.parse_args()
    if args.workdir is None:
        args.workdir = Path(tempfile.mkdtemp(prefix="wd-measure-export-"))
    args.workdir.mkdir(parents=True, exist_ok=True)
    result = _measure(args)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out is not None:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
