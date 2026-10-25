"""Pomiar importu dużej paczki ``.wdkb.zip`` (brief E7-1b-T8 p. 6) — skrypt uruchamiany ręcznie.

NIE jest zbierany przez pytest (brak prefiksu ``test_``). Uruchamia się na stosie testowym
(``eval "$(tools/dev/up.sh test env)"`` po ``tools/dev/up.sh test up mariadb-test fake-llm``):

    cd backend && uv run python tests/integration/kb_import_measure.py \\
        --chunks 30000 --dim 1024 --docs 40 --out /tmp/import.json

Skrypt generuje syntetyczną paczkę (domyślnie ≈ „rocznik GUS": 30 000 chunków po ~800 znaków
losowych słów PL, 40 dokumentów, wektory losowe znormalizowane), zakłada świeżą bazę (jak
fixture ``fresh_db`` + migracje Alembic), wysyła paczkę porcjami ``IMPORT_CHUNK_SIZE`` (8 MiB)
przez ASGI/HTTP, startuje import i mierzy: czas uploadu wraz z walidacją, czas zadania
(``start`` → ``done``) oraz szczyt pamięci procesu (``resource.getrusage(RUSAGE_SELF).ru_maxrss``).
Wynik zapisuje jako JSON (``--out``) i wypisuje czytelnie na stdout. Paczka tworzona jest
strumieniowo (``PackageWriter`` + ``NpyWriter``), więc pamięć szczytowa pochodzi z realnej pracy,
nie z trzymania całej paczki w liście.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import logging
import os
import random
import resource
import sys
import tempfile
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

# Skrypt uruchamiany wprost (``python tests/integration/kb_import_measure.py``) — katalog skryptu
# nie jest katalogiem ``backend``, więc dokładamy go do ``sys.path`` jak robi to pytest.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx
import pymysql
from fastapi import FastAPI

from alembic import command
from app.api.auth.principal import get_principal
from app.core.config import Settings
from app.core.container import Container
from app.db.repositories import models as models_repo
from app.db.repositories import users as users_repo
from app.db.uow import transaction
from app.domain.policy import Principal
from app.main import create_app
from app.services.kb_package import format as fmt
from app.services.kb_package.writer import PackageWriter
from app.worker.context import TaskContext
from app.worker.kb_handlers import KB_HANDLERS
from app.worker.queue import DbTaskQueue
from tests.integration.db.helpers import alembic_cfg, worker_db_name

MODEL = "fake-embed-1024"  # model docelowy = model paczki → import 1:1 (bez reembeddingu)
UPLOAD_PIECE = 8 * 1024 * 1024  # IMPORT_CHUNK_SIZE — porcja uploadu przez ``Content-Range``
CONTENT_CHARS = 800  # docelowa długość treści chunka (znaki)
DOC_BLOB_BYTES = 20 * 1024  # rozmiar pliku każdego dokumentu (~20 KB)
HTTP_OK = 200  # porcja uploadu przyjęta poprawnie (K19 §3, trasa 7)
WORKER_ID = "measure:1:0"
PARSER_CONFIG: dict[str, Any] = {"chunk_token_num": 128, "delimiter": "\n"}

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


def _jsonl(rows: Iterator[dict[str, Any]]) -> Iterator[bytes]:
    """Strumień linii JSONL (bez trzymania całej listy w pamięci)."""
    for row in rows:
        yield (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")


def _document_lines(docs: int, blobs: list[bytes]) -> Iterator[dict[str, Any]]:
    """Linie ``documents.jsonl``: ``docs`` dokumentów, każdy z własnym plikiem (K19 §2)."""
    for index in range(docs):
        blob = blobs[index]
        yield {
            "ref": f"d{index + 1}",
            "name": f"rocznik-{index + 1}.pdf",
            "type": "pdf",
            "suffix": "pdf",
            "size": len(blob),
            "file_sha256": hashlib.sha256(blob).hexdigest(),
            "chunk_method": "naive",
            "parser_config": PARSER_CONFIG,
            "meta_fields": {"doc": index + 1},
            "run": "3",  # DONE — run surowe (K19 §2)
            "progress_msg": "gotowe",
            "token_num": 10,
            "chunk_num": 0,
        }


def _chunk_lines(chunks: int, docs: int) -> Iterator[dict[str, Any]]:
    """Linie ``chunks.jsonl``: ``chunks`` chunków rozłożonych po ``docs`` dokumentach (K19 §2)."""
    for index in range(chunks):
        yield {
            "ref": f"c{index + 1}",
            "document_ref": f"d{index % docs + 1}",
            "ordinal": index // docs,
            "chunk_type": "text",
            "content": _chunk_content(index),
            "content_llm": None,
            "keywords": [],
            "questions": [],
            "tags": {},
            "positions": None,
            "page_from": None,
            "page_to": None,
            "image_sha256": None,
            "parent_ref": None,
            "available": True,
            "embed_source": "content",
            "token_count": 8,
        }


def _vector_parts(chunks: int, dim: int) -> Iterator[bytes]:
    """Wektory jako kolejne wpisy ``vectors/00000k.npy`` (NPY 1.0 strumieniowo, bez numpy)."""
    total_parts = max(1, -(-chunks // fmt.VECTOR_PART_ROWS))
    for part in range(total_parts):
        first = part * fmt.VECTOR_PART_ROWS
        rows = min(fmt.VECTOR_PART_ROWS, chunks - first)
        buffer = io.BytesIO()
        writer = fmt.NpyWriter(buffer, dim)
        for offset in range(rows):
            writer.write_rows([_vector(first + offset, dim)])
        writer.close()
        yield buffer.getvalue()


def _manifest(*, docs: int, chunks: int, dim: int) -> fmt.Manifest:
    """Manifest syntetycznej paczki (K19 §2) z licznikami rocznika."""
    return fmt.Manifest.model_validate(
        {
            "format": fmt.FORMAT_NAME,
            "schema_version": fmt.SCHEMA_VERSION,
            "wd_version": "0.9.0",
            "created_at": "2026-10-12T21:00:00Z",
            "source_instance_id": "0123456789abcdef0123456789abcdef",
            "dataset": {
                "name": "Rocznik GUS",
                "description": "syntetyczna paczka pomiarowa",
                "language": "Polish",
                "chunk_method": "naive",
                "parser_config": PARSER_CONFIG,
                "similarity_threshold": 0.2,
                "vector_similarity_weight": 0.3,
                "pagerank": 0,
            },
            "embedding": {"model_name": MODEL, "dimension": dim, "included": True},
            "counts": {"documents": docs, "chunks": chunks, "vectors": chunks},
            "entries": [],
        }
    )


def build_package(path: Path, *, chunks: int, dim: int, docs: int) -> int:
    """Buduje paczkę strumieniowo; zwraca jej rozmiar w bajtach."""
    blobs = [_blob(index) for index in range(docs)]
    writer = PackageWriter(path, max_bytes=1 << 40)
    writer.add_file(fmt.DOCUMENTS_PATH, _jsonl(_document_lines(docs, blobs)))
    writer.add_file(fmt.CHUNKS_PATH, _jsonl(_chunk_lines(chunks, docs)))
    for part, data in enumerate(_vector_parts(chunks, dim)):
        writer.add_file(fmt.vector_part_path(part), (data,))
    for blob in blobs:
        writer.add_file(f"{fmt.FILES_PREFIX}{hashlib.sha256(blob).hexdigest()}", (blob,))
    return writer.finish(_manifest(docs=docs, chunks=chunks, dim=dim))


def _blob(index: int) -> bytes:
    """Deterministyczny „nieściśliwy" plik dokumentu (``DOC_BLOB_BYTES`` losowych bajtów)."""
    return random.Random(index).randbytes(DOC_BLOB_BYTES)  # noqa: S311 — generator z seedem


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


async def _seed(container: Container, *, actor: str, dim: int) -> None:
    """Rejestruje model docelowy (z wymiarem paczki) i użytkownika-aktora importu."""
    now = int(time.time() * 1000)
    model_id = uuid.uuid4().hex
    async with transaction(container.sessionmaker) as session:
        await models_repo.insert(
            session,
            id=model_id,
            name=MODEL,
            model_type="embedding",
            is_default=True,
            now_ms=now,
        )
        await models_repo.set_dimension_if_null(session, model_id, dim, now)
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


def _app(container: Container, principal: Principal) -> FastAPI:
    """Aplikacja ASGI z nadpisaniem aktora (jak testy tras WD)."""
    app = create_app(container.settings, container)
    app.dependency_overrides[get_principal] = lambda: principal
    return app


async def _upload_and_start(
    client: httpx.AsyncClient, path: Path, size: int
) -> tuple[float, str, dict[str, Any]]:
    """Zakłada sesję, wysyła paczkę porcjami, startuje import; zwraca czasy i ``TaskRef``.

    Zwraca ``(upload_seconds, import_id, task_ref)`` — ``upload_seconds`` obejmuje ostatnią
    porcję razem z walidacją paczki (``state=ready``), czyli „upload + walidacja" z briefu.
    """
    created = (
        await client.post(
            "/api/wd/v1/dataset-imports",
            json={"file_name": "rocznik.wdkb.zip", "size_bytes": size},
        )
    ).json()["data"]
    import_id = created["import_id"]
    started_at = time.perf_counter()
    with path.open("rb") as fp:
        offset = 0
        while offset < size:
            piece = fp.read(UPLOAD_PIECE)
            assert piece, "plik paczki krótszy niż zadeklarowany rozmiar"
            end = offset + len(piece) - 1
            response = await client.put(
                f"/api/wd/v1/dataset-imports/{import_id}/content",
                content=piece,
                headers={
                    "Content-Range": f"bytes {offset}-{end}/{size}",
                    "Content-Type": "application/octet-stream",
                },
            )
            assert response.status_code == HTTP_OK, response.text
            offset = end + 1
    upload_seconds = time.perf_counter() - started_at
    final = response.json()["data"]
    assert final["state"] == "ready", final
    started = (
        await client.post(
            f"/api/wd/v1/dataset-imports/{import_id}/start",
            json={"name": "Import pomiarowy", "embedding_model": None},
        )
    ).json()["data"]
    return upload_seconds, import_id, started


async def _run_task(container: Container, task_id: str) -> float:
    """Claim zadania i wykonanie handlera jak slot workera; zwraca czas ``start`` → ``done``."""
    queue = DbTaskQueue(container.sessionmaker, container.clock, container.id_gen)
    task = await queue.claim(WORKER_ID, ["import_dataset"])
    assert task is not None and task.id == task_id, "zadanie importu musi być do wzięcia"
    logger: logging.LoggerAdapter[logging.Logger] = logging.LoggerAdapter(
        logging.getLogger("measure.import_dataset"), {"task_id": task.id}
    )
    ctx = TaskContext(
        task=task, worker_id=WORKER_ID, container=container, logger=logger, queue=queue
    )
    started_at = time.perf_counter()
    await KB_HANDLERS["import_dataset"](task, ctx)
    await queue.complete(task.id, WORKER_ID)
    return time.perf_counter() - started_at


async def _run_import(
    args: argparse.Namespace, settings: Settings, package_path: Path, package_bytes: int
) -> dict[str, Any]:
    """Bieg async: kontener, upload+walidacja, zadanie; zwraca czasy (``start`` → ``done``)."""
    actor = uuid.uuid4().hex
    container = Container(settings)
    await container.start()
    try:
        await _seed(container, actor=actor, dim=args.dim)
        principal = Principal(actor, f"{actor[:12]}@example.com", False, False, "jwt")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_app(container, principal)), base_url="http://test"
        ) as client:
            upload_seconds, _import_id, task_ref = await _upload_and_start(
                client, package_path, package_bytes
            )
            task_seconds = await _run_task(container, task_ref["task_id"])
    finally:
        await container.aclose()
    return {"upload_seconds": upload_seconds, "task_seconds": task_seconds}


def _measure(args: argparse.Namespace) -> dict[str, Any]:
    """Cały bieg pomiarowy: świeża baza, paczka, upload+walidacja, zadanie, pamięć szczytowa.

    Baza i migracje Alembic idą SYNCHRONICZNIE (``env.py`` woła ``asyncio.run``) — dopiero potem
    startuje pętla zdarzeń z kontenerem i klientem ASGI.
    """
    db_name = worker_db_name("wd_measure")
    package_path = args.workdir / "rocznik.wdkb.zip"
    settings = Settings(env="test", db_name=db_name, storage_root=str(args.workdir / "storage"))
    _create_db(db_name)
    try:
        command.upgrade(alembic_cfg(settings), "head")
        package_bytes = build_package(
            package_path, chunks=args.chunks, dim=args.dim, docs=args.docs
        )
        timings = asyncio.run(_run_import(args, settings, package_path, package_bytes))
    finally:
        _drop_db(db_name)
    peak_rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    return {
        "chunks": args.chunks,
        "dim": args.dim,
        "documents": args.docs,
        "package_bytes": package_bytes,
        "package_mib": round(package_bytes / (1 << 20), 1),
        "upload_seconds": round(timings["upload_seconds"], 2),
        "task_seconds": round(timings["task_seconds"], 2),
        "peak_rss_bytes": peak_rss_bytes,
        "peak_rss_mib": round(peak_rss_bytes / (1 << 20), 1),
    }


def main() -> None:
    """Punkt wejścia CLI: parsuje argumenty, mierzy import i wypisuje wynik."""
    parser = argparse.ArgumentParser(description="Pomiar importu paczki ``.wdkb.zip``.")
    parser.add_argument("--chunks", type=int, default=30_000, help="liczba chunków w paczce")
    parser.add_argument("--dim", type=int, default=1024, help="wymiar wektorów")
    parser.add_argument("--docs", type=int, default=40, help="liczba dokumentów")
    parser.add_argument("--out", type=Path, default=None, help="plik JSON z wynikiem pomiaru")
    parser.add_argument(
        "--workdir", type=Path, default=None, help="katalog roboczy (domyślnie świeży temp)"
    )
    args = parser.parse_args()
    if args.workdir is None:
        args.workdir = Path(tempfile.mkdtemp(prefix="wd-measure-"))
    args.workdir.mkdir(parents=True, exist_ok=True)
    result = _measure(args)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out is not None:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
