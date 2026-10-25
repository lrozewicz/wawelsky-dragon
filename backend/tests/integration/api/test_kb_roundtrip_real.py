"""Round-trip na danych z PRAWDZIWEJ ingestii: upload+parse → eksport → import (K19, E7-H1/T2).

Dowód, że paczka z bazy zasilonej prawdziwą ingestią (a nie ręcznie budowanymi fiksturami
chunków, jak w ``test_kb_roundtrip.py``) importuje się do NOWEGO datasetu na tej samej
instalacji, gdy docelowy model embeddingu ma ``models.dimension IS NULL`` (świeża instalacja,
DEC-342), i że chunki przechodzą 1:1. Tylko tak wychodzą wady, które w e2e E7-2 przeszły przez
ręczne fikstury: kształt ``tags`` (``[]`` vs ``{}``, DEC-341) i sonda wymiaru przy ``dimension
NULL`` (pusta lista modeli → brak domyślnego → nie da się zaimportować bazy).

Ścieżka jest wyłącznie użytkownika: ``container.ingest.upload`` + handler ``parse_document``
(``run_parse``) → ``POST /datasets/{id}/export`` + handler ``export_dataset`` + pobranie paczki →
sesja importu (porcje ``Content-Range``) → ``start`` → handler ``import_dataset``. Bez ręcznie
budowanych paczek i bez fikstur chunków.

Marker ``db`` + ``fakellm``: wymaga MariaDB i fake-llm (``WD_LLM_BASE_URL`` z ``verify.sh``).
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.auth.principal import get_principal
from app.core.config import Settings
from app.core.container import Container
from app.db.repositories import chunk_vectors as chunk_vectors_repo
from app.db.repositories import documents as documents_repo
from app.db.repositories.datasets import DatasetRow
from app.db.uow import transaction
from app.domain.policy import Principal
from app.main import create_app
from app.services.ingest_pipeline import run_parse
from app.worker.context import TaskContext
from app.worker.kb_handlers import KB_HANDLERS
from app.worker.loop import classify
from app.worker.queue import DbTaskQueue, TaskRow
from tests.integration.chat.conftest import seed_user
from tests.integration.ingest.conftest import seed_dataset
from tests.integration.ingest.pipeline_helpers import claim_context, make_container, make_source
from tests.integration.retrieval.conftest import principal_for

pytestmark = [
    pytest.mark.db,
    pytest.mark.fakellm,
    pytest.mark.skipif(
        not os.environ.get("WD_LLM_BASE_URL"),
        reason="fakellm: brak WD_LLM_BASE_URL (eksportuje verify.sh)",
    ),
]

# Korpus testowy repo: dwa małe polskie pliki tekstowe (backend/tests/fixtures/retrieval/).
CORPUS_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "retrieval"
DOC1 = "umowa-najmu.txt"
DOC2 = "regulamin-urlopow.txt"

MODEL = "fake-embed-1024"  # model z ``make_container`` (embedding, domyślny)
DIM = 1024
RUN_DONE = "3"  # RUN_CODES["DONE"]
WORKER_ID = "real-host:1:0"
IMPORT_NAME = "Baza z prawdziwej ingestii"
_ID_HEX_LEN = 32
_HTTP_OK = 200
_HTTP_CREATED = 201
_HTTP_ACCEPTED = 202


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener ze storage w tmp_path i modelami fake (wzorzec ``tests/integration/api``)."""
    instance = await make_container(migrated_db, tmp_path)
    yield instance
    await instance.aclose()


def _app(container: Container, principal: Principal | None) -> FastAPI:
    """Aplikacja na żywym kontenerze; ``principal=None`` → brak nadpisania (pobranie paczki)."""
    app = create_app(container.settings, container)
    if principal is not None:
        app.dependency_overrides[get_principal] = lambda: principal
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    """Klient ASGI nad aplikacją testową (jeden event loop, jak w ``test_kb_roundtrip``)."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _queue(container: Container) -> DbTaskQueue:
    """Kolejka na usługach kontenera (enqueue/claim/complete/snapshot)."""
    return DbTaskQueue(_sm(container), container.clock, container.id_gen)


def _sm(container: Container) -> async_sessionmaker[AsyncSession]:
    """Fabryka sesji z kontenera (istnieje po ``start()``)."""
    sessionmaker = container.sessionmaker
    assert sessionmaker is not None, "container nie wystartował"
    return sessionmaker


def _ctx(container: Container, task: TaskRow) -> TaskContext:
    """Kontekst zadania dla handlera (logger bez handlera, kolejka z kontenera)."""
    logger: logging.LoggerAdapter[logging.Logger] = logging.LoggerAdapter(
        logging.getLogger("test.kb_roundtrip_real"), {"task_id": task.id}
    )
    return TaskContext(
        task=task, worker_id=WORKER_ID, container=container, logger=logger, queue=_queue(container)
    )


# --- ingestia prawdziwą ścieżką (upload + handler parse_document) -------------------------------


async def _document(
    sm: async_sessionmaker[AsyncSession], document_id: str
) -> documents_repo.DocumentRow | None:
    """Świeży wiersz dokumentu po parsowaniu."""
    async with transaction(sm) as session:
        return await documents_repo.get(session, document_id)


async def _ingest_corpus_file(
    container: Container, sm: async_sessionmaker[AsyncSession], ds: DatasetRow, name: str
) -> None:
    """Wgrywa plik z korpusu i prowadzi go przez ``run_parse`` — jak worker (C4/C7)."""
    data = (CORPUS_DIR / name).read_bytes()
    doc = await container.ingest.upload(ds.id, make_source(data, name), created_by=ds.tenant_id)
    ctx = await claim_context(container, doc.id)
    await run_parse(container, ctx.task, ctx, executor=None)

    row = await _document(sm, doc.id)
    assert row is not None and row.run == RUN_DONE, row
    assert row.chunk_count > 0, "prawdziwa ingestia musi dać chunki"


async def _seed_dataset_a(container: Container, sm: async_sessionmaker[AsyncSession]) -> DatasetRow:
    """Dataset A: dwa dokumenty z korpusu przez prawdziwą ingestię (chunki + wektory)."""
    ds = await seed_dataset(sm)
    for name in (DOC1, DOC2):
        await _ingest_corpus_file(container, sm, ds, name)
    return ds


# --- wymiar modelu: świeża instalacja (dimension NULL) ------------------------------------------


async def _clear_model_dimension(sm: async_sessionmaker[AsyncSession], name: str) -> None:
    """Zeruje wymiar modelu (``models.dimension IS NULL`` — stan świeżej instalacji, DEC-342)."""
    async with transaction(sm) as session:
        await session.execute(
            text(
                "UPDATE models SET dimension = NULL WHERE name = :name AND model_type = 'embedding'"
            ),
            {"name": name},
        )


async def _model_dimension(sm: async_sessionmaker[AsyncSession], name: str) -> int | None:
    """Wymiar modelu z rejestru (``None`` = brak wymiaru w ``models.dimension``)."""
    async with transaction(sm) as session:
        value = (
            await session.execute(
                text("SELECT dimension FROM models WHERE name = :name"), {"name": name}
            )
        ).scalar_one()
    return int(value) if value is not None else None


# --- eksport A: trasa → handler → pobranie paczki -----------------------------------------------


async def _run_export_task(container: Container, task_id: str) -> None:
    """Claim zadania ``export_dataset`` i wykonanie handlera z ``KB_HANDLERS`` (jak worker)."""
    queue = _queue(container)
    task = await queue.claim(WORKER_ID, ["export_dataset"])
    assert task is not None and task.id == task_id, "zadanie eksportu nie zostało pobrane"
    ctx = _ctx(container, task)
    try:
        await KB_HANDLERS["export_dataset"](task, ctx)
    except Exception as exc:  # klasyfikacja jak w loop.classify
        await queue.fail(task.id, WORKER_ID, exc, transient=classify(exc) == "fail_transient")
        raise
    await queue.complete(task.id, WORKER_ID)


async def _export_package(container: Container, dataset_id: str, tenant_id: str) -> bytes:
    """Eksport A z wektorami: trasa 2 + handler + pobranie ``download_url`` bez cookie."""
    async with _client(_app(container, principal_for(tenant_id))) as client:
        started = await client.post(
            f"/api/wd/v1/datasets/{dataset_id}/export", json={"include_vectors": True}
        )
        assert started.status_code == _HTTP_ACCEPTED, started.text
        task_id: str = started.json()["data"]["task_id"]
    await _run_export_task(container, task_id)
    snapshot = await _queue(container).snapshot(task_id)
    assert snapshot is not None and snapshot.payload.get("result") is not None
    result: Mapping[str, Any] = snapshot.payload["result"]
    async with _client(_app(container, None)) as anon:
        download = await anon.get(str(result["download_url"]))
    assert download.status_code == _HTTP_OK, download.text
    return download.content


# --- import do nowego datasetu ------------------------------------------------------------------


async def _import_session(client: httpx.AsyncClient, data: bytes) -> str:
    """Zakłada sesję i wysyła paczkę w DWÓCH porcjach ``Content-Range``; zwraca ``import_id``."""
    created = await client.post(
        "/api/wd/v1/dataset-imports",
        json={"file_name": "baza-a.wdkb.zip", "size_bytes": len(data)},
    )
    assert created.status_code == _HTTP_CREATED, created.text
    import_id: str = created.json()["data"]["import_id"]
    assert len(import_id) == _ID_HEX_LEN
    split = len(data) // 2
    for start, end in ((0, split - 1), (split, len(data) - 1)):
        response = await client.put(
            f"/api/wd/v1/dataset-imports/{import_id}/content",
            content=data[start : end + 1],
            headers={
                "Content-Range": f"bytes {start}-{end}/{len(data)}",
                "Content-Type": "application/octet-stream",
            },
        )
        assert response.status_code == _HTTP_OK, response.text
    return import_id


async def _run_import_task(container: Container, task_id: str) -> str:
    """Claim zadania ``import_dataset`` i wykonanie handlera; wynik jak ``app.worker.loop``."""
    queue = _queue(container)
    task = await queue.claim(WORKER_ID, ["import_dataset"])
    assert task is not None and task.id == task_id
    ctx = _ctx(container, task)
    try:
        await KB_HANDLERS["import_dataset"](task, ctx)
    except Exception as exc:  # noqa: BLE001 — klasyfikacja jak w loop.classify
        await queue.fail(task.id, WORKER_ID, exc, transient=classify(exc) == "fail_transient")
        return "failed"
    await queue.complete(task.id, WORKER_ID)
    return "done"


async def _result_dataset(container: Container, task_id: str) -> str:
    """Id datasetu utworzonego przez import z ``payload.result`` zadania."""
    snapshot = await _queue(container).snapshot(task_id)
    assert snapshot is not None and snapshot.payload.get("result") is not None
    return str(snapshot.payload["result"]["dataset_id"])


async def _import_into_new_dataset(
    container: Container, actor_id: str, package: bytes
) -> tuple[str, Mapping[str, Any]]:
    """Sesja → porcje → ``ready`` → podsumowanie → ``start`` → handler; zwraca (id B, wynik)."""
    async with _client(_app(container, principal_for(actor_id))) as client:
        import_id = await _import_session(client, package)
        detail = (await client.get(f"/api/wd/v1/dataset-imports/{import_id}")).json()["data"]
        assert detail["state"] == "ready", detail
        started = await client.post(
            f"/api/wd/v1/dataset-imports/{import_id}/start",
            json={"name": IMPORT_NAME, "embedding_model": None},
        )
        assert started.status_code == _HTTP_ACCEPTED, started.text
        task_id: str = started.json()["data"]["task_id"]

    assert await _run_import_task(container, task_id) == "done"
    snapshot = await _queue(container).snapshot(task_id)
    assert snapshot is not None and snapshot.payload.get("result") is not None
    result: Mapping[str, Any] = snapshot.payload["result"]
    return str(result["dataset_id"]), result


# --- odczyt A i B do porównania ----------------------------------------------------------------


def _json(value: Any) -> Any:
    """JSON z bazy bywa tekstem — normalizuje do obiektu Pythona."""
    return json.loads(value) if isinstance(value, str) else value


async def _read_chunks(
    sm: async_sessionmaker[AsyncSession], dataset_id: str
) -> list[Mapping[str, Any]]:
    """Wiersze ``chunks`` datasetu z nazwą dokumentu (sortowane po (dokument, ordinal))."""
    async with transaction(sm) as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT c.id, c.ordinal, d.name AS doc_name, c.content, c.keywords,"
                        " c.questions, c.tags, c.positions, c.available FROM chunks c"
                        " JOIN documents d ON d.id = c.document_id"
                        " WHERE c.dataset_id = :ds ORDER BY d.name, c.ordinal"
                    ),
                    {"ds": dataset_id},
                )
            )
            .mappings()
            .all()
        )
    return rows


async def _read_vectors(
    sm: async_sessionmaker[AsyncSession], dataset_id: str, dim: int
) -> dict[str, list[float]]:
    """Wektory datasetu jako mapa ``chunk_id → lista float`` (``VEC_ToText``)."""
    table = chunk_vectors_repo.table_name(dim)
    async with transaction(sm) as session:
        rows = (
            await session.execute(
                text(
                    f"SELECT chunk_id, VEC_ToText(embedding) AS v FROM {table}"  # noqa: S608
                    " WHERE dataset_id = :ds"
                ),
                {"ds": dataset_id},
            )
        ).all()
    return {str(chunk_id): json.loads(vec) for chunk_id, vec in rows}


async def _document_names(sm: async_sessionmaker[AsyncSession], dataset_id: str) -> list[str]:
    """Nazwy dokumentów datasetu (kolejność alfabetyczna)."""
    async with transaction(sm) as session:
        rows = (
            await session.execute(
                text("SELECT name FROM documents WHERE dataset_id = :ds ORDER BY name"),
                {"ds": dataset_id},
            )
        ).scalars()
    return [str(name) for name in rows]


def _chunk_key(row: Mapping[str, Any]) -> tuple[str, int]:
    """Klucz porównania A↔B: (nazwa dokumentu, ordinal)."""
    return str(row["doc_name"]), int(row["ordinal"])


def _vectors_by_key(
    rows: Sequence[Mapping[str, Any]], vectors: Mapping[str, list[float]]
) -> dict[tuple[str, int], list[float]]:
    """Mapa ``(nazwa, ordinal) → wektor`` dla danego datasetu."""
    return {_chunk_key(row): vectors[str(row["id"])] for row in rows}


# --- test ---------------------------------------------------------------------------------------


async def test_roundtrip_real_ingestion_with_null_model_dimension(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Ingestia → eksport → import przy ``models.dimension IS NULL``; chunki i wektory 1:1.

    Kolejność wymagań E7-H1/T2: (1) dwa pliki korpusu przez prawdziwy upload+parse, (2) eksport
    z wektorami, (3) zerowanie ``models.dimension`` (świeża instalacja), (4) import do nowego
    datasetu (sonda wymiaru w ``build_summary`` daje ``compatible=true`` i ``reembed=false``),
    (5) porównanie chunków (``content``/``tags``/``available``/``keywords``/``questions``/
    ``positions``) i wektorów bez tolerancji.
    """
    # 1. Prawdziwa ingestia dwóch plików korpusu (chunki + wektory).
    ds = await _seed_dataset_a(container, sm)
    chunks_a = await _read_chunks(sm, ds.id)
    vectors_a = await _read_vectors(sm, ds.id, DIM)
    assert [row["doc_name"] for row in chunks_a].count(DOC1) > 0
    assert [row["doc_name"] for row in chunks_a].count(DOC2) > 0
    assert len(chunks_a) == len(vectors_a) > 0
    # Realna ingestia zostawia ``chunks.tags`` na DDL-default ``'[]'`` — lista, nie obiekt.
    assert all(isinstance(_json(row["tags"]), list) for row in chunks_a), "tags źródła to lista"

    # 2. Eksport A z wektorami (prawdziwa trasa + handler + pobranie paczki).
    package = await _export_package(container, ds.id, ds.tenant_id)

    # 3. Docelowy model bez wymiaru — świeża instalacja B (DEC-342).
    await _clear_model_dimension(sm, MODEL)
    assert await _model_dimension(sm, MODEL) is None

    # 4. Import do NOWEGO datasetu na tej samej instalacji, aktor B.
    actor_b = await seed_user(sm)
    dataset_b, result = await _import_into_new_dataset(container, actor_b, package)

    # Sonda wymiaru w podsumowaniu: model znów ma wymiar, import bez zbędnego reembeddingu.
    assert await _model_dimension(sm, MODEL) == DIM
    assert result["reembedded"] is False, result
    assert result["chunks"] == len(chunks_a), result

    # 5. Chunki i wektory 1:1 (nowe id, ta sama treść i metadane).
    assert dataset_b != ds.id
    assert await _document_names(sm, dataset_b) == await _document_names(sm, ds.id)
    chunks_b = await _read_chunks(sm, dataset_b)
    vectors_b = await _read_vectors(sm, dataset_b, DIM)
    by_key_a = {_chunk_key(row): row for row in chunks_a}
    by_key_b = {_chunk_key(row): row for row in chunks_b}
    assert set(by_key_a) == set(by_key_b)
    for key, row_b in by_key_b.items():
        row_a = by_key_a[key]
        assert str(row_b["id"]) != str(row_a["id"])  # nowe id chunka
        assert row_b["content"] == row_a["content"]
        assert _json(row_b["tags"]) == _json(row_a["tags"])
        assert isinstance(_json(row_b["tags"]), list)  # DEC-341: kształt z paczki, nie ``{}``
        assert bool(row_b["available"]) == bool(row_a["available"])
        assert _json(row_b["keywords"]) == _json(row_a["keywords"])
        assert _json(row_b["questions"]) == _json(row_a["questions"])
        assert _json(row_b["positions"]) == _json(row_a["positions"])

    vec_a = _vectors_by_key(chunks_a, vectors_a)
    vec_b = _vectors_by_key(chunks_b, vectors_b)
    assert set(vec_a) == set(vec_b)
    for key, vector in vec_b.items():
        assert vector == vec_a[key]  # float32 bez tolerancji
        assert len(vector) == DIM
