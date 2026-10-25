"""Test A→B dwóch tenantów: eksport → import bazy wiedzy (K19 §2/§3/§5, E7-1b-T9).

Ćwiczy pełną drogę użytkownika A (dataset z dokumentami, chunkiem edytowanym trasą edycji
chunka i chunkiem wyłączonym) do użytkownika B: **prawdziwy eksport A** (``POST
/datasets/{id}/export`` + handler ``export_dataset`` z ``KB_HANDLERS`` + pobranie paczki z
``download_url`` bez cookie) → sesja importu → porcje ``Content-Range`` → ``start`` → handler
``import_dataset`` → dataset w tenancie B z nowymi id. Sprawdza, że treść, ``keywords``,
``questions``, ``page_from``/``page_to``, ``tags`` (lista z DDL-default i niepusta — T12),
wektory 1:1, edycja i wyłączenie przetrwały, że retrieval
jako B zwraca zaimportowany chunk (a wyłączonego nie) i że tenanci się nie widzą (R-KB-01 kroki
5-8). Od T5 osobno: wektory po paczce są **bit w bit** jak w A, a ten sam retrieval przed i po
round-tripie zwraca tę samą liczbę trafień i tę samą kolejność (DEC-350).
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
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
from app.core.errors import PermissionDenied
from app.core.timeutil import from_ms
from app.db.repositories import chunk_vectors as chunk_vectors_repo
from app.db.repositories import chunks, chunks_import
from app.db.repositories import documents as documents_repo
from app.db.repositories import models as models_repo
from app.db.repositories.chunks_import import ChunkImportRow
from app.db.repositories.datasets import DatasetRow
from app.db.repositories.documents import DocumentRow
from app.db.uow import transaction
from app.domain.policy import Principal
from app.main import create_app
from app.services.retrieval import RetrievalQuery
from app.storage.keys import document_key
from app.text.fulltext import ft_text, stem_text
from app.worker.context import TaskContext
from app.worker.handlers.import_dataset import import_dataset
from app.worker.kb_handlers import KB_HANDLERS
from app.worker.loop import classify
from app.worker.queue import DbTaskQueue, TaskRow
from tests.integration.chat.conftest import seed_user
from tests.integration.datasets.conftest import seed_model
from tests.integration.ingest.conftest import seed_dataset
from tests.integration.ingest.pipeline_helpers import make_container
from tests.integration.retrieval.conftest import principal_for

pytestmark = [pytest.mark.db, pytest.mark.fakellm]

_HTTP_OK = 200
_HTTP_CREATED = 201
_HTTP_ACCEPTED = 202
_ID_HEX_LEN = 32
_WORKER_ID = "test-host:1:0"

MODEL = "fake-embed-1024"
DIM = 1024
ALT_MODEL = "fake-embed-3072"
ALT_DIM = 3072
TIME_MS = 1790157600000
RUN_DONE = "3"  # RUN_CODES["DONE"]
RUN_UNSTART = "0"  # RUN_CODES["UNSTART"]
SEED_TASK_ID = "a" * 32  # „public_id" zadania przy seedzie chunków A (unikalność id)

DOC1 = "umowa.txt"
DOC2 = "urlop.txt"
BLOB1 = b"Umowa najmu lokalu uzytkowego w Krakowie. " * 4
# Początkowa i edytowana treść chunka „edytowanego" (wymaganie 1 briefu).
CHUNK_EDIT_BEFORE = "Umowa najmu lokalu w Krakowie."
CHUNK_EDIT_AFTER = "Umowa najmu lokalu w Krakowie - aneks nr 2, czynsz 1500 zl."
CHUNK_DISABLED = "Czynsz najmu platny dziesiatego dnia miesiaca."
CHUNK_PLAIN = "Wniosek urlopowy sklada sie dwa tygodnie przed urlopem."
# Chunki z tagami (T12, DEC-341): lista pusta to DDL-default kolumny ``chunks.tags`` w bazie
# (wiersz z ingestii nie podaje tej kolumny), a niepusta — efekt edycji tagów w A.
CHUNK_TAGS_DEFAULT = "Chunk z domyslnymi tagami z bazy (DDL-default '[]')."
CHUNK_TAGS_LIST = "Chunk z tagami edytowanymi w A."
TAGS_DEFAULT: list[str] = []
TAGS_LIST = ["umowa", "najem"]
TENANT_A_CHUNKS = 5  # trzy chunki bazowe + dwa z tagami (T12)
# Pytanie porównania retrievalu A↔B (T5, DEC-350) — trafia w kilka chunków seedu A.
RETRIEVAL_QUESTION = "Umowa najmu lokalu w Krakowie"


@dataclass(frozen=True)
class TenantA:
    """Dataset A: dwa dokumenty, pięć chunków (edycja, wyłączenie, dwa kształty ``tags``)."""

    dataset: DatasetRow
    doc1: str
    doc2: str
    chunk_edit: str  # edytowany trasą edycji (ordinal 0 w DOC1)
    chunk_disabled: str  # available=false (ordinal 1 w DOC1)
    chunk_plain: str  # bez zmian (ordinal 0 w DOC2)


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener ze magazynem w tmp_path i modelami fake-llm (wzorzec tests/integration/api)."""
    instance = await make_container(migrated_db, tmp_path)
    yield instance
    await instance.aclose()


def _sm(container: Container) -> async_sessionmaker[AsyncSession]:
    """Fabryka sesji z kontenera (istnieje po ``start()``)."""
    sessionmaker = container.sessionmaker
    assert sessionmaker is not None, "container nie wystartował"
    return sessionmaker


def _app(container: Container, principal: Principal) -> FastAPI:
    """Aplikacja na żywym kontenerze z nadpisanym principalem (WD i trasy RAGFlow)."""
    app = create_app(container.settings, container)
    app.dependency_overrides[get_principal] = lambda: principal
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    """Klient ASGI nad aplikacją testową."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _queue(container: Container) -> DbTaskQueue:
    """Kolejka na usługach kontenera (enqueue/claim/complete)."""
    return DbTaskQueue(_sm(container), container.clock, container.id_gen)


# --- seed tenanta A -------------------------------------------------------------------------------


async def _set_model_dimension(sm: async_sessionmaker[AsyncSession], name: str, dim: int) -> None:
    """Ustawia wymiar modelu embeddingu (bez niego ``target.compatible`` = false → reembed)."""
    async with transaction(sm) as session:
        row = await models_repo.get_by_name(session, name, "embedding")
        assert row is not None, f"model {name} niezarejestrowany"
        await models_repo.set_dimension_if_null(session, row.id, dim, TIME_MS)


async def _insert_document(
    sm: async_sessionmaker[AsyncSession], ds: DatasetRow, name: str, *, run: str
) -> str:
    """Wstawia dokument ``name`` (status ``run``) w datasecie A; zwraca jego id."""
    doc_id = uuid.uuid4().hex
    suffix = name.rsplit(".", 1)[-1] if "." in name else ""
    now = from_ms(TIME_MS)
    async with transaction(sm) as session:
        await documents_repo.insert(
            session,
            DocumentRow(
                id=doc_id,
                dataset_id=ds.id,
                created_by=ds.tenant_id,
                name=name,
                suffix=suffix,
                type="doc",
                size=0,
                location=document_key(ds.id, doc_id, suffix),
                content_hash="",
                source_type="local",
                source_ref=None,
                chunk_method=ds.chunk_method,
                parser_config=ds.parser_config,
                run=run,
                progress=0.0,
                progress_msg="",
                error=None,
                process_begin_at=None,
                process_duration=0.0,
                chunk_count=0,
                token_count=0,
                enabled=True,
                meta_fields={"zespol": "prawny"},
                thumbnail=None,
                create_time=TIME_MS,
                create_date=now,
                update_time=TIME_MS,
                update_date=now,
            ),
        )
    return doc_id


def _chunk_row(  # noqa: PLR0913 — pełny wiersz chunka seedu A
    *,
    chunk: str,
    doc_id: str,
    ds_id: str,
    name: str,
    ordinal: int,
    content: str,
    keywords: Sequence[str],
    questions: Sequence[str],
    page_from: int,
    page_to: int,
    available: bool,
    tags: Any = None,
) -> ChunkImportRow:
    """``ChunkImportRow`` datasetu A (pola 1:1, kolumny FT jak ingestia).

    ``tags`` domyślnie obiekt (jak ``tag_feas`` RAGFlow); kolumna ``chunks.tags`` z ingestii ma
    DDL-default ``'[]'`` (lista), a edycja tagów może dać niepustą listę — oba kształty przechodzą
    przez paczkę (T12, DEC-341).
    """
    return ChunkImportRow(
        id=chunk,
        document_id=doc_id,
        dataset_id=ds_id,
        ordinal=ordinal,
        chunk_type="text",
        content=content,
        content_llm=None,
        content_ft=ft_text(content),
        content_stem=stem_text(content),
        title_ft=ft_text(Path(name).stem),
        keywords=keywords,
        questions=questions,
        important_ft=ft_text(" ".join(keywords)),
        question_ft=ft_text("\n".join(questions)),
        tags={} if tags is None else tags,
        positions=None,
        page_from=page_from,
        page_to=page_to,
        image_id=None,
        parent_id=None,
        available=available,
        token_count=len(content.split()),
        embed_source="content",
    )


async def _seed_tenant_a(container: Container, sm: async_sessionmaker[AsyncSession]) -> TenantA:
    """Tworzy dataset A: dwa dokumenty, pięć chunków (z wektorami), jeden wyłączony."""
    await _set_model_dimension(sm, MODEL, DIM)
    ds = await seed_dataset(sm)
    doc1 = await _insert_document(sm, ds, DOC1, run=RUN_DONE)
    doc2 = await _insert_document(sm, ds, DOC2, run=RUN_UNSTART)
    await container.storage.put(document_key(ds.id, doc1, "txt"), BLOB1)

    rows = [
        _chunk_row(
            chunk=chunks.chunk_id(doc1, SEED_TASK_ID, 0),
            doc_id=doc1,
            ds_id=ds.id,
            name=DOC1,
            ordinal=0,
            content=CHUNK_EDIT_BEFORE,
            keywords=["umowa", "najem"],
            questions=["Kto wynajmuje?"],
            page_from=1,
            page_to=2,
            available=True,
        ),
        _chunk_row(
            chunk=chunks.chunk_id(doc1, SEED_TASK_ID, 1),
            doc_id=doc1,
            ds_id=ds.id,
            name=DOC1,
            ordinal=1,
            content=CHUNK_DISABLED,
            keywords=["czynsz"],
            questions=[],
            page_from=2,
            page_to=2,
            available=False,
        ),
        _chunk_row(
            chunk=chunks.chunk_id(doc2, SEED_TASK_ID, 0),
            doc_id=doc2,
            ds_id=ds.id,
            name=DOC2,
            ordinal=0,
            content=CHUNK_PLAIN,
            keywords=["urlop"],
            questions=["Jak złożyć wniosek?"],
            page_from=1,
            page_to=1,
            available=True,
        ),
        _chunk_row(
            chunk=chunks.chunk_id(doc2, SEED_TASK_ID, 1),
            doc_id=doc2,
            ds_id=ds.id,
            name=DOC2,
            ordinal=1,
            content=CHUNK_TAGS_DEFAULT,
            keywords=["tagi"],
            questions=[],
            page_from=1,
            page_to=1,
            available=True,
            tags=TAGS_DEFAULT,
        ),
        _chunk_row(
            chunk=chunks.chunk_id(doc2, SEED_TASK_ID, 2),
            doc_id=doc2,
            ds_id=ds.id,
            name=DOC2,
            ordinal=2,
            content=CHUNK_TAGS_LIST,
            keywords=["tagi"],
            questions=[],
            page_from=1,
            page_to=1,
            available=True,
            tags=TAGS_LIST,
        ),
    ]
    vectors = await _embed(container, [row.content for row in rows])
    async with transaction(sm) as session:
        await chunks_import.insert_many(session, rows, now_ms=TIME_MS)
    async with transaction(sm) as session:
        await chunk_vectors_repo.ensure_table(session, DIM)
    async with transaction(sm) as session:
        await chunk_vectors_repo.insert_many(
            session, DIM, [(row.id, ds.id, vec) for row, vec in zip(rows, vectors, strict=True)]
        )
    return TenantA(
        dataset=ds,
        doc1=doc1,
        doc2=doc2,
        chunk_edit=rows[0].id,
        chunk_disabled=rows[1].id,
        chunk_plain=rows[2].id,
    )


async def _embed(container: Container, contents: Sequence[str]) -> list[list[float]]:
    """Wektory treści modelem paczki (deterministyczny fake-llm)."""
    registry = container.models
    llm = container.llm
    assert registry is not None and llm is not None, "container nie wystartował"
    ref = await registry.resolve(MODEL, "embedding")
    return await llm.embed(ref, list(contents))


# --- edycja chunka trasą RAGFlow ------------------------------------------------------------------


async def _edit_chunk_via_route(client: httpx.AsyncClient, a: TenantA, *, content: str) -> None:
    """Zmienia treść chunka trasą ``PATCH /api/v1/.../chunks/{id}`` (reembed + FT w trasie)."""
    response = await client.patch(
        f"/api/v1/datasets/{a.dataset.id}/documents/{a.doc1}/chunks/{a.chunk_edit}",
        json={"content": content},
    )
    assert response.status_code == _HTTP_OK, response.text


# --- eksport A: trasa → handler → pobranie paczki (R-KB-01 kroki 3-4) --------------------


async def _run_export_task(container: Container, task_id: str) -> None:
    """Claim zadania ``export_dataset`` i wykonanie handlera z ``KB_HANDLERS`` (jak worker)."""
    queue = _queue(container)
    task = await queue.claim(_WORKER_ID, ["export_dataset"])
    assert task is not None and task.id == task_id, "zadanie eksportu nie zostało pobrane"
    ctx = _ctx(container, task)
    try:
        await KB_HANDLERS["export_dataset"](task, ctx)
    except Exception as exc:  # klasyfikacja jak w loop.classify
        await queue.fail(task.id, _WORKER_ID, exc, transient=classify(exc) == "fail_transient")
        raise
    await queue.complete(task.id, _WORKER_ID)


async def _export_package(container: Container, dataset_id: str, tenant_id: str) -> bytes:
    """Eksport A: ``POST /datasets/{id}/export`` + handler + pobranie paczki bez cookie.

    Zlecenie idzie trasą 2 (202), wykonanie jak w workerze (claim + ``KB_HANDLERS``), a paczkę
    pobieramy z ``download_url`` **bez cookie** (trasa 5 zna wyłącznie podpis). Zwraca bajty ZIP.
    """
    async with _client(_app(container, principal_for(tenant_id))) as client:
        started = await client.post(f"/api/wd/v1/datasets/{dataset_id}/export", json={})
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


def _json(value: Any) -> Any:
    """JSON z bazy bywa tekstem — normalizuje do obiektu Pythona."""
    return json.loads(value) if isinstance(value, str) else value


async def _read_dataset(sm: async_sessionmaker[AsyncSession], dataset_id: str) -> Mapping[str, Any]:
    """Pola ``datasets`` potrzebne do porównania A↔B (K19 §2)."""
    async with transaction(sm) as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT name, description, language, chunk_method, parser_config,"
                        " similarity_threshold, vector_similarity_weight, pagerank,"
                        " embedding_model, embedding_dim FROM datasets WHERE id = :id"
                    ),
                    {"id": dataset_id},
                )
            )
            .mappings()
            .one()
        )
    return row


async def _read_documents(
    sm: async_sessionmaker[AsyncSession], dataset_id: str
) -> list[Mapping[str, Any]]:
    """Wiersze ``documents`` datasetu (sortowane po nazwie — stabilne refy)."""
    async with transaction(sm) as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT id, name, suffix, type, size, content_hash, chunk_method,"
                        " parser_config, meta_fields, run, progress_msg, token_count, chunk_count"
                        " FROM documents WHERE dataset_id = :ds ORDER BY name"
                    ),
                    {"ds": dataset_id},
                )
            )
            .mappings()
            .all()
        )
    return rows


async def _read_chunks(
    sm: async_sessionmaker[AsyncSession], dataset_id: str
) -> list[Mapping[str, Any]]:
    """Wiersze ``chunks`` datasetu z nazwą dokumentu (sortowane po (dokument, ordinal))."""
    async with transaction(sm) as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT c.id, c.document_id, d.name AS doc_name, c.ordinal, c.chunk_type,"
                        " c.content, c.content_llm, c.keywords, c.questions, c.tags, c.positions,"
                        " c.page_from, c.page_to, c.image_id, c.parent_id, c.available,"
                        " c.embed_source, c.token_count FROM chunks c"
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


# --- import u B: sesja → porcje → start --------------------------------------------------


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
    detail = (await client.get(f"/api/wd/v1/dataset-imports/{import_id}")).json()["data"]
    assert detail["state"] == "ready", detail
    return import_id


async def _start_import(
    client: httpx.AsyncClient, import_id: str, *, name: str, embedding_model: str | None
) -> str:
    """``POST .../start``; zwraca ``task_id`` zleconego zadania importu."""
    response = await client.post(
        f"/api/wd/v1/dataset-imports/{import_id}/start",
        json={"name": name, "embedding_model": embedding_model},
    )
    assert response.status_code == _HTTP_ACCEPTED, response.text
    task_id: str = response.json()["data"]["task_id"]
    return task_id


# --- wykonanie handlera (jak app.worker.loop) --------------------------------------------


def _ctx(container: Container, task: TaskRow) -> TaskContext:
    """Kontekst zadania dla handlera (logger bez handlera, kolejka z kontenera)."""
    logger: logging.LoggerAdapter[logging.Logger] = logging.LoggerAdapter(
        logging.getLogger("test.kb_roundtrip"), {"task_id": task.id}
    )
    return TaskContext(
        task=task, worker_id=_WORKER_ID, container=container, logger=logger, queue=_queue(container)
    )


async def _run_import_task(container: Container, task_id: str) -> str:
    """Claim zadania i wykonanie handlera; zwraca wynik jak ``app.worker.loop``."""
    queue = _queue(container)
    task = await queue.claim(_WORKER_ID, ["import_dataset"])
    assert task is not None and task.id == task_id
    ctx = _ctx(container, task)
    try:
        await import_dataset(task, ctx)
    except Exception as exc:  # noqa: BLE001 — klasyfikacja jak w loop.classify
        await queue.fail(task.id, _WORKER_ID, exc, transient=classify(exc) == "fail_transient")
        return "failed"
    await queue.complete(task.id, _WORKER_ID)
    return "done"


async def _result_dataset(container: Container, task_id: str) -> str:
    """Id datasetu utworzonego przez import z ``payload.result`` zadania."""
    snapshot = await _queue(container).snapshot(task_id)
    assert snapshot is not None and snapshot.payload.get("result") is not None
    return str(snapshot.payload["result"]["dataset_id"])


async def _roundtrip_dataset_b(container: Container, sm: async_sessionmaker[AsyncSession]) -> str:
    """A → prawdziwy eksport → import u B; zwraca id datasetu B (seed A bez edycji chunka)."""
    a = await _seed_tenant_a(container, sm)
    package = await _export_package(container, a.dataset.id, a.dataset.tenant_id)
    user_b = await seed_user(sm)
    async with _client(_app(container, principal_for(user_b))) as client_b:
        import_id = await _import_session(client_b, package)
        task_id = await _start_import(client_b, import_id, name="Baza A run", embedding_model=None)
    assert await _run_import_task(container, task_id) == "done"
    return await _result_dataset(container, task_id)


# --- odczyt B do porównania -------------------------------------------------------------


def _chunk_key(row: Mapping[str, Any]) -> tuple[str, int]:
    """Klucz porównania A↔B: (nazwa dokumentu, ordinal)."""
    return str(row["doc_name"]), int(row["ordinal"])


def _chunk_values(row: Mapping[str, Any]) -> dict[str, Any]:
    """Pola chunka, które muszą przetrwać A→B (K19 §2); ``tags`` w tym kształt (T12)."""
    return {
        "content": row["content"],
        "keywords": _json(row["keywords"]),
        "questions": _json(row["questions"]),
        "tags": _json(row["tags"]),
        "page_from": row["page_from"],
        "page_to": row["page_to"],
        "available": bool(row["available"]),
    }


def _vectors_by_key(
    rows: Sequence[Mapping[str, Any]], vectors: Mapping[str, list[float]]
) -> dict[tuple[str, int], list[float]]:
    """Mapa ``(nazwa, ordinal) → wektor`` dla danego datasetu."""
    return {_chunk_key(row): vectors[str(row["id"])] for row in rows}


async def _retrieve_contents(
    container: Container, principal: Principal, dataset_id: str, question: str
) -> list[str]:
    """Treści chunków zwróconych przez retrieval jako ``principal`` (próg 0, czysty wektor)."""
    result = await container.retrieval.retrieve(
        principal,
        RetrievalQuery(
            question=question,
            dataset_ids=(dataset_id,),
            similarity_threshold=0.0,
            vector_similarity_weight=1.0,
        ),
    )
    return [chunk.content for chunk in result.chunks]


async def _retrieve_hybrid(
    container: Container, principal: Principal, dataset_id: str, question: str
) -> tuple[int, list[tuple[str, str, float]]]:
    """Retrieval hybrydowy (jak krok czatu: wektor + FULLTEXT, domyślne okno kandydatów).

    Zwraca ``(total, [(nazwa dokumentu, treść, term_similarity), …])`` — liczba trafień i lista
    w kolejności zwracanej przez usługę. ``term_similarity`` jest liczona wyłącznie z treści
    i kolumn FULLTEXT chunka, więc po round-tripie ma być **identyczna** co do bitu.
    """
    result = await container.retrieval.retrieve(
        principal,
        RetrievalQuery(
            question=question,
            dataset_ids=(dataset_id,),
            similarity_threshold=0.0,
            vector_similarity_weight=0.3,
        ),
    )
    return result.total, [
        (chunk.document_name, chunk.content, chunk.term_similarity) for chunk in result.chunks
    ]


async def _read_vectors_hex(
    sm: async_sessionmaker[AsyncSession], dataset_id: str, dim: int
) -> dict[tuple[str, int], str]:
    """Wektory datasetu jako mapa ``(nazwa dokumentu, ordinal) → HEX(embedding)``.

    ``HEX`` daje surowe bajty wektora (float32), więc porównanie jest bit w bit. ``VEC_ToText``
    nadaje się tylko do podglądu: wypisuje 6 cyfr znaczących (DEC-350).
    """
    table = chunk_vectors_repo.table_name(dim)
    async with transaction(sm) as session:
        rows = (
            (
                await session.execute(
                    text(
                        f"SELECT d.name AS doc_name, c.ordinal, HEX(v.embedding) AS hex"  # noqa: S608
                        f" FROM {table} v JOIN chunks c ON c.id = v.chunk_id"
                        " JOIN documents d ON d.id = c.document_id WHERE v.dataset_id = :ds"
                    ),
                    {"ds": dataset_id},
                )
            )
            .mappings()
            .all()
        )
    return {(str(row["doc_name"]), int(row["ordinal"])): str(row["hex"]) for row in rows}


async def _read_ft_columns(
    sm: async_sessionmaker[AsyncSession], dataset_id: str
) -> dict[tuple[str, int], tuple[str, str, str, str, str]]:
    """Kolumny wejściowe wyszukiwania FULLTEXT po ``(nazwa dokumentu, ordinal)`` (DEC-350)."""
    async with transaction(sm) as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT d.name AS doc_name, c.ordinal, c.content_ft, c.content_stem,"
                        " c.title_ft, c.important_ft, c.question_ft FROM chunks c"
                        " JOIN documents d ON d.id = c.document_id WHERE c.dataset_id = :ds"
                    ),
                    {"ds": dataset_id},
                )
            )
            .mappings()
            .all()
        )
    return {
        (str(row["doc_name"]), int(row["ordinal"])): (
            str(row["content_ft"]),
            str(row["content_stem"]),
            str(row["title_ft"]),
            str(row["important_ft"]),
            str(row["question_ft"]),
        )
        for row in rows
    }


async def _export_import_b(
    container: Container, sm: async_sessionmaker[AsyncSession], a: TenantA
) -> tuple[str, str]:
    """Eksport A → import u B dla gotowego seedu A; zwraca ``(dataset_b, user_b)``."""
    package = await _export_package(container, a.dataset.id, a.dataset.tenant_id)
    user_b = await seed_user(sm)
    async with _client(_app(container, principal_for(user_b))) as client_b:
        import_id = await _import_session(client_b, package)
        task_id = await _start_import(
            client_b, import_id, name="Baza A retrieval", embedding_model=None
        )
    assert await _run_import_task(container, task_id) == "done"
    return await _result_dataset(container, task_id), user_b


# --- testy ------------------------------------------------------------------------------


async def test_roundtrip_two_tenants(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """A→B: treść, metadane, wektory i edycja przetrwały; tenanty się nie widzą."""
    a = await _seed_tenant_a(container, sm)
    # 1. Edycja chunka trasą RAGFlow (treść zmieniona + reembed).
    async with _client(_app(container, principal_for(a.dataset.tenant_id))) as client_a:
        await _edit_chunk_via_route(client_a, a, content=CHUNK_EDIT_AFTER)

    docs_a = await _read_documents(sm, a.dataset.id)
    chunks_a = await _read_chunks(sm, a.dataset.id)
    vectors_a = await _read_vectors(sm, a.dataset.id, DIM)
    edited_a = next(row for row in chunks_a if str(row["id"]) == a.chunk_edit)
    assert edited_a["content"] == CHUNK_EDIT_AFTER  # edycja zapisana w A

    # 2. Prawdziwy eksport A (trasa 2 + handler + pobranie) → import u B: sesja → porcje → start.
    package = await _export_package(container, a.dataset.id, a.dataset.tenant_id)
    user_b = await seed_user(sm)
    async with _client(_app(container, principal_for(user_b))) as client_b:
        import_id = await _import_session(client_b, package)
        task_id = await _start_import(client_b, import_id, name="Baza A", embedding_model=None)

    assert await _run_import_task(container, task_id) == "done"
    dataset_b = await _result_dataset(container, task_id)

    # 3. Dataset B: nowe id, tenant B, nazwa; dokumenty i chunki odpowiadają A.
    ds_b = await _read_dataset(sm, dataset_b)
    assert ds_b["name"] == "Baza A"
    assert dataset_b != a.dataset.id
    async with transaction(sm) as session:
        tenant_b = (
            await session.execute(
                text("SELECT tenant_id FROM datasets WHERE id = :id"), {"id": dataset_b}
            )
        ).scalar_one()
    assert tenant_b == user_b

    docs_b = await _read_documents(sm, dataset_b)
    assert [d["name"] for d in docs_b] == [d["name"] for d in docs_a]
    assert all(str(db["id"]) != str(da["id"]) for db, da in zip(docs_b, docs_a, strict=True))
    # Blob dokumentu z plikiem w paczce (files/<sha>) skopiowany do storage B.
    blob_b = document_key(dataset_b, str(docs_b[0]["id"]), str(docs_b[0]["suffix"]))
    assert await container.storage.exists(blob_b)
    copied = b"".join([piece async for piece in container.storage.open(blob_b)])
    assert copied == BLOB1

    chunks_b = await _read_chunks(sm, dataset_b)
    vectors_b = await _read_vectors(sm, dataset_b, DIM)
    by_key_a = {_chunk_key(row): row for row in chunks_a}
    by_key_b = {_chunk_key(row): row for row in chunks_b}
    assert set(by_key_a) == set(by_key_b)
    for key, row_b in by_key_b.items():
        assert str(row_b["id"]) != str(by_key_a[key]["id"])  # nowe id chunka
        assert _chunk_values(row_b) == _chunk_values(by_key_a[key])
    # Edytowany chunk zachował edytowaną treść; wyłączony nadal wyłączony.
    assert by_key_b[(DOC1, 0)]["content"] == CHUNK_EDIT_AFTER
    assert not bool(by_key_b[(DOC1, 1)]["available"])
    # ``tags`` z kolumny o DDL-default ``'[]'`` (lista) i niepusta lista z edycji — ta sama
    # wartość i ten sam typ u B; paczka z własnego eksportu nie może wywalić importu 500 (T12).
    assert [_json(by_key_b[(DOC2, i)]["tags"]) for i in (1, 2)] == [TAGS_DEFAULT, TAGS_LIST]
    # Eksport zapisuje w ``documents.jsonl`` ``run`` surowe (kod „3” = DONE, CONTRACT E7-1a §3),
    # a handler importu rozpoznaje „zakończony” po tym kodzie (K19 §2). Statusy dokumentów u B
    # (DONE/„nieuruchomiony") sprawdza osobno ``test_roundtrip_document_run_survives``.
    assert [d["name"] for d in docs_b] == [DOC1, DOC2]

    # 4. Wektory 1:1 (porównanie z A).
    vec_a = _vectors_by_key(chunks_a, vectors_a)
    vec_b = _vectors_by_key(chunks_b, vectors_b)
    for key, vector in vec_b.items():
        assert vector == pytest.approx(vec_a[key])

    # 5. Retrieval jako B zwraca zaimportowany chunk, a wyłączonego nie (mimo że ma wektor).
    principal_b = principal_for(user_b)
    assert CHUNK_PLAIN in await _retrieve_contents(container, principal_b, dataset_b, CHUNK_PLAIN)
    # Pytanie o wyłączony chunk: gdyby filtr ``available`` nie działał, trafiłby z sim 1.0.
    assert CHUNK_DISABLED not in await _retrieve_contents(
        container, principal_b, dataset_b, CHUNK_DISABLED
    )

    # 6. Tenanty się nie widzą (polityka: obcy dataset → brak dostępu).
    with pytest.raises(PermissionDenied):
        await container.retrieval.retrieve(
            principal_for(a.dataset.tenant_id),
            RetrievalQuery(question=CHUNK_PLAIN, dataset_ids=(dataset_b,)),
        )
    with pytest.raises(PermissionDenied):
        await container.retrieval.retrieve(
            principal_b,
            RetrievalQuery(question=CHUNK_PLAIN, dataset_ids=(a.dataset.id,)),
        )


async def test_roundtrip_document_run_survives(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Statusy dokumentów A→B: „zakończony" (RUN_DONE) i „nieuruchomiony" (R-KB-01 krok 6).

    Zabezpieczenie przed regresją statusów dokumentów u B: import rozpoznaje „zakończony"
    po surowym kodzie ``run`` z paczki (K19 §2), więc mutacja odczytu kodu zbija tę asercję.
    """
    dataset_b = await _roundtrip_dataset_b(container, sm)
    docs_b = await _read_documents(sm, dataset_b)
    assert [d["run"] for d in docs_b] == [RUN_DONE, RUN_UNSTART]


async def test_roundtrip_other_model_reembeds(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Wariant „inny model": model docelowy o innym wymiarze → ``reembedded=true``."""
    await seed_model(sm, ALT_MODEL, "embedding", dimension=ALT_DIM, is_default=False)
    a = await _seed_tenant_a(container, sm)
    package = await _export_package(container, a.dataset.id, a.dataset.tenant_id)
    user_b = await seed_user(sm)
    async with _client(_app(container, principal_for(user_b))) as client_b:
        import_id = await _import_session(client_b, package)
        task_id = await _start_import(
            client_b, import_id, name="Baza A alt", embedding_model=ALT_MODEL
        )

    assert await _run_import_task(container, task_id) == "done"
    snapshot = await _queue(container).snapshot(task_id)
    assert snapshot is not None and snapshot.payload.get("result") is not None
    assert snapshot.payload["result"]["reembedded"] is True
    assert snapshot.payload["result"]["chunks"] == TENANT_A_CHUNKS
    dataset_b = str(snapshot.payload["result"]["dataset_id"])
    # Chunki obecne, ale wektory policzone od nowa modelem docelowym (dim ALT_DIM).
    chunks_b = await _read_chunks(sm, dataset_b)
    assert len(chunks_b) == TENANT_A_CHUNKS
    assert len(await _read_vectors(sm, dataset_b, ALT_DIM)) == TENANT_A_CHUNKS


async def test_roundtrip_vectors_bit_exact(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """A→B: wektory bit w bit, a kolumny FULLTEXT chunka znak w znak (T5, DEC-350).

    Eksport czytał wektor przez ``VEC_ToText``, a to wypisuje float32 z **6 cyframi znaczącymi**:
    każdy komponent paczki różnił się od wektora źródłowego do ~5e-6 (rel.), a dystans cosinusowy do
    ~1e-8 — wyszukiwanie dostawało inne dystanse niż przed eksportem. Ten test pinuje wektor 1:1
    («odpowiedź czatu jak przed» z SC-E67-08 k4 nie może zależeć od zapisu wektora do paczki).
    """
    a = await _seed_tenant_a(container, sm)
    hex_a = await _read_vectors_hex(sm, a.dataset.id, DIM)
    ft_a = await _read_ft_columns(sm, a.dataset.id)
    dataset_b, _ = await _export_import_b(container, sm, a)

    assert await _read_vectors_hex(sm, dataset_b, DIM) == hex_a
    # Wejścia wyszukiwania FULLTEXT (liczone jak ingestia, DEC-328) są identyczne — różnica liczby
    # trafień po imporcie bierze się ze statystyk indeksu FTS MariaDB, nie z danych (DEC-350).
    assert await _read_ft_columns(sm, dataset_b) == ft_a


async def test_roundtrip_retrieval_matches(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Ten sam retrieval przed i po A→B: ta sama liczba trafień i ta sama kolejność (T5, DEC-350).

    Korpus testu mieści się w oknie kandydatów (``top_k``/``rerank_candidates_count``), więc ani
    okno wektorowe, ani okno FULLTEXT nie tnie remisów na granicy — wynik musi być identyczny.
    Przy korpusie większym niż okno skład okna FULLTEXT zależy od stanu indeksu FTS MariaDB
    (liczby trafień mogą się różnić o kilka sztuk) — ten test pinuje stabilność tam, gdzie powinna.
    """
    a = await _seed_tenant_a(container, sm)
    total_a, hits_a = await _retrieve_hybrid(
        container, principal_for(a.dataset.tenant_id), a.dataset.id, RETRIEVAL_QUESTION
    )
    dataset_b, user_b = await _export_import_b(container, sm, a)
    total_b, hits_b = await _retrieve_hybrid(
        container, principal_for(user_b), dataset_b, RETRIEVAL_QUESTION
    )

    assert hits_a, "pytanie testu nie trafia w żaden chunk"
    assert total_b == total_a
    assert hits_b == hits_a
