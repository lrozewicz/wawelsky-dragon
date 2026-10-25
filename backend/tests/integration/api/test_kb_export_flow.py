"""Test CAŁEGO przepływu eksportu paczki ``.wdkb.zip`` przez HTTP (K19, R-KB-01/04/05).

Zakres (brief E7-1a-T3a): podgląd (liczby i szacunek), ``POST`` → zadanie kolejki w kolejności
etapów ``files→chunks→vectors→finalize`` odpytywane ``GET /tasks/{id}`` (jak użytkownik),
pobranie ``download_url`` **bez** cookie/nagłówków (200, ZIP przechodzący ``validate_package``),
restart handlera na tym samym zadaniu (jedna paczka), wygaśnięcie linku po 24 h (410) i sprzątanie
``exports/``, uprawnienia (członek zespołu 403) oraz zły/podmieniony podpis (403). Na końcu audyt
``dataset_exported``. Wszystko na MariaDB i fake-llm.

Ścieżka użytkownika idzie wyłącznie trasami HTTP (``/api/wd/v1/...``) plus wykonaniem handlera z
``KB_HANDLERS`` na zadaniu z kolejki — jak robi to ``app.worker.loop``. Dataset ma > 1000 chunków,
żeby etapy ``chunks``/``vectors`` raportowały postęp w kilku partiach i odpytywanie zdążyło je
zobaczyć w kolejności.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import uuid
import zipfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.auth.principal import get_principal
from app.core.config import Settings
from app.core.container import Container
from app.core.ids import UuidV7Generator
from app.core.timeutil import from_ms
from app.db.repositories import chunk_vectors as chunk_vectors_repo
from app.db.repositories import chunks, chunks_import
from app.db.repositories import documents as documents_repo
from app.db.repositories.chunks_import import ChunkImportRow
from app.db.repositories.datasets import DatasetRow
from app.db.repositories.documents import DocumentRow
from app.db.uow import transaction
from app.domain.policy import Principal
from app.main import create_app
from app.services.kb_export_link import (
    EXPORT_LINK_TTL_S,
    export_package_path,
    sign_export,
)
from app.services.kb_package.validate import ValidatedPackage, validate_package
from app.storage.keys import document_key
from app.text.fulltext import ft_text, stem_text
from app.worker.context import TaskContext
from app.worker.kb_cleanup import run_cleanup
from app.worker.kb_handlers import KB_HANDLERS
from app.worker.loop import classify
from app.worker.queue import DbTaskQueue, TaskRow
from tests.fakes.clock import FrozenClock
from tests.integration.chat.conftest import seed_user
from tests.integration.ingest.conftest import seed_dataset
from tests.integration.ingest.pipeline_helpers import register_models
from tests.integration.retrieval.conftest import principal_for

pytestmark = [pytest.mark.db, pytest.mark.fakellm]

WORKER_ID = "flow-host:1:0"
DIM = 8
CHUNKS = 1024  # > CHUNKS_BATCH (1000) — kilka partii etapów ``chunks``/``vectors``
TIME_MS = 1790157600000
SEED_TASK_ID = "a" * 32  # część deterministycznego id chunka (unikalność)
MAX_BYTES = 100 * 1024 * 1024
MAX_RATIO = 100
DAY_MS = EXPORT_LINK_TTL_S * 1000
SLUG = "korpus"  # dataset ``seed_dataset`` nazywa się „Korpus"

DOC1 = "umowa.txt"
DOC2 = "urlop.txt"
BLOB1 = b"Umowa najmu lokalu uzytkowego w Krakowie. " * 4

_HTTP_OK = 200
_HTTP_ACCEPTED = 202
_HTTP_FORBIDDEN = 403
_HTTP_EXPIRED = 410
_ID_HEX_LEN = 32


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener z zegarem zamrożonym (do przesunięcia o dobę) i modelami fake-llm."""
    instance = Container(
        migrated_db.model_copy(update={"storage_root": str(tmp_path), "ocr_engine": "none"}),
        clock=FrozenClock(TIME_MS),
        id_gen=UuidV7Generator(),
    )
    await instance.start()
    assert instance.sessionmaker is not None
    await register_models(instance.sessionmaker)
    yield instance
    await instance.aclose()


def _sm(container: Container) -> async_sessionmaker[AsyncSession]:
    """Fabryka sesji z kontenera (istnieje po ``start()``)."""
    sessionmaker = container.sessionmaker
    assert sessionmaker is not None, "container nie wystartował"
    return sessionmaker


def _clock(container: Container) -> FrozenClock:
    """Zamrożony zegar kontenera (fixture) — ``advance`` symuluje upływ doby."""
    return cast(FrozenClock, container.clock)


def _app(container: Container, principal: Principal | None) -> FastAPI:
    """Aplikacja na żywym kontenerze; ``principal=None`` → brak nadpisania (trasa bez aktora)."""
    app = create_app(container.settings, container)
    if principal is not None:
        app.dependency_overrides[get_principal] = lambda: principal
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    """Klient ASGI nad aplikacją testową (bez nagłówka Authorization)."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _queue(container: Container) -> DbTaskQueue:
    """Kolejka na usługach kontenera (enqueue/claim/complete/snapshot)."""
    return DbTaskQueue(_sm(container), container.clock, container.id_gen)


# --- seed ----------------------------------------------------------------------------------------


async def _insert_document(
    sm: async_sessionmaker[AsyncSession], ds: DatasetRow, name: str, *, run: str
) -> str:
    """Wstawia dokument ``name`` (status ``run``) w datasecie; zwraca jego id."""
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


def _chunk_row(
    *, chunk: str, doc_id: str, ds_id: str, ordinal: int, content: str
) -> ChunkImportRow:
    """``ChunkImportRow`` datasetu (pola 1:1, kolumny FT jak ingestia)."""
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
        title_ft=ft_text("umowa"),
        keywords=["umowa"],
        questions=[],
        important_ft=ft_text("umowa"),
        question_ft="",
        tags={},
        positions=None,
        page_from=1,
        page_to=1,
        image_id=None,
        parent_id=None,
        available=True,
        token_count=len(content.split()),
        embed_source="content",
    )


async def _seed_dataset_with_chunks(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> DatasetRow:
    """Dataset A: 2 dokumenty (>1000 chunków z wektorami), jeden dokument ma plik w storage."""
    ds = await seed_dataset(sm, embedding_dim=DIM)
    doc1 = await _insert_document(sm, ds, DOC1, run="3")
    await _insert_document(sm, ds, DOC2, run="0")
    await container.storage.put(document_key(ds.id, doc1, "txt"), BLOB1)

    rows = [
        _chunk_row(
            chunk=chunks.chunk_id(doc1, SEED_TASK_ID, ordinal),
            doc_id=doc1,
            ds_id=ds.id,
            ordinal=ordinal,
            content=f"Chunk {ordinal} dokumentu eksportu baz wiedzy.",
        )
        for ordinal in range(CHUNKS)
    ]
    async with transaction(sm) as session:
        await chunks_import.insert_many(session, rows, now_ms=TIME_MS)
    async with transaction(sm) as session:
        await chunk_vectors_repo.ensure_table(session, DIM)
    async with transaction(sm) as session:
        vector = [float(index) for index in range(DIM)]
        await chunk_vectors_repo.insert_many(
            session, DIM, [(row.id, ds.id, vector) for row in rows]
        )
    return ds


async def _set_permission(
    sm: async_sessionmaker[AsyncSession], dataset_id: str, value: str
) -> None:
    """Ustawia ``datasets.permission`` (``team`` → członek zespołu ma READ)."""
    async with transaction(sm) as session:
        await session.execute(
            text("UPDATE datasets SET permission = :p WHERE id = :id"),
            {"p": value, "id": dataset_id},
        )


# --- przebieg zadania jak w workerze -------------------------------------------------------------


def _ctx(container: Container, task: TaskRow) -> TaskContext:
    """Kontekst zadania dla handlera (logger bez handlera, kolejka z kontenera)."""
    logger: logging.LoggerAdapter[logging.Logger] = logging.LoggerAdapter(
        logging.getLogger("test.kb_export_flow"), {"task_id": task.id}
    )
    return TaskContext(
        task=task, worker_id=WORKER_ID, container=container, logger=logger, queue=_queue(container)
    )


async def _run_export_task(container: Container, task_id: str, *, repeat: int = 1) -> None:
    """Claim zadania i wykonanie handlera ``export_dataset`` z ``KB_HANDLERS`` ``repeat`` razy."""
    queue = _queue(container)
    task = await queue.claim(WORKER_ID, ["export_dataset"])
    assert task is not None and task.id == task_id, "zadanie eksportu nie zostało pobrane"
    ctx = _ctx(container, task)
    for _ in range(repeat):
        try:
            await KB_HANDLERS["export_dataset"](task, ctx)
        except Exception as exc:  # klasyfikacja jak w loop.classify
            await queue.fail(task.id, WORKER_ID, exc, transient=classify(exc) == "fail_transient")
            raise
    await queue.complete(task.id, WORKER_ID)


async def _start_export(
    client: httpx.AsyncClient, dataset_id: str, *, include_vectors: bool = True
) -> str:
    """``POST /datasets/{id}/export``; zwraca ``task_id`` zleconego zadania (202)."""
    response = await client.post(
        f"/api/wd/v1/datasets/{dataset_id}/export", json={"include_vectors": include_vectors}
    )
    assert response.status_code == _HTTP_ACCEPTED, response.text
    task_id: str = response.json()["data"]["task_id"]
    assert len(task_id) == _ID_HEX_LEN
    return task_id


async def _details(client: httpx.AsyncClient, task_id: str) -> dict[str, Any]:
    """``data`` zadania z ``GET /tasks/{id}`` (trasa 3)."""
    response = await client.get(f"/api/wd/v1/tasks/{task_id}")
    assert response.status_code == _HTTP_OK, response.text
    return cast(dict[str, Any], response.json()["data"])


async def _poll_task(
    client: httpx.AsyncClient, task_id: str
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Odpytywanie zadania co krok pętli; zbiera kolejne ``stage`` i ``message`` do ``done``."""
    stages: list[str] = []
    messages: list[str] = []
    while True:
        data = await _details(client, task_id)
        stage = data["stage"]
        if stage is not None and (not stages or stages[-1] != stage):
            stages.append(stage)
        message = data["message"] or ""
        if message and (not messages or messages[-1] != message):
            messages.append(message)
        if data["status"] in ("done", "failed", "cancelled"):
            return data, stages, messages
        await asyncio.sleep(0)


def _secret(container: Container) -> str:
    """Sekret linku pobrania — jak w usłudze (``settings.secret_key``)."""
    return container.settings.secret_key.get_secret_value()


def _exp_sig(result: dict[str, Any], task_id: str) -> tuple[int, str]:
    """``exp`` (sekundy) i ``sig`` z ``download_url`` wyniku eksportu."""
    query = parse_qs(urlparse(result["download_url"]).query)
    return int(query["exp"][0]), query["sig"][0]


# --- testy ---------------------------------------------------------------------------------------


async def test_export_flow_preview_start_download(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """R-KB-01/2-4: podgląd → POST → etapy → ``done`` → pobranie bez cookie; audyt (h)."""
    ds = await _seed_dataset_with_chunks(container, sm)
    client_app = _app(container, principal_for(ds.tenant_id))

    async with _client(client_app) as client:
        # (a) R-KB-01/2: podgląd — liczby = dataset, szacunek z wektorami > bez wektorów.
        preview = (await client.get(f"/api/wd/v1/datasets/{ds.id}/export/preview")).json()["data"]
        assert (preview["dataset_id"], preview["documents"], preview["chunks"]) == (
            ds.id,
            2,
            CHUNKS,
        )
        assert preview["estimated_bytes_with_vectors"] > preview["estimated_bytes"]
        assert preview["embedding"]["dimension"] == DIM

        # (b) R-KB-01/3: POST → GET /tasks/{id} pokazuje stage files→chunks→vectors→finalize.
        task_id = await _start_export(client, ds.id)
        _, (done, stages, messages) = await asyncio.gather(
            _run_export_task(container, task_id), _poll_task(client, task_id)
        )

        assert stages == ["files", "chunks", "vectors", "finalize"], stages
        assert any("Chunki " in message for message in messages), messages
        assert done["status"] == "done", done
        result = done["result"]
        assert result["download_url"].startswith(f"/api/wd/v1/exports/{task_id}/download?")
        assert result["file_name"] == f"{SLUG}.wdkb.zip"

        # (c) R-KB-01/4: pobranie bez cookie/nagłówków → 200, ZIP z wpisami, walidator OK.
        path = export_package_path(container.settings.storage_root, task_id)
        package = await asyncio.to_thread(path.read_bytes)

    async with _client(_app(container, None)) as anon:
        download = await anon.get(result["download_url"])
    assert download.status_code == _HTTP_OK, download.text
    assert download.headers["content-type"] == "application/zip"
    assert download.headers["content-disposition"] == f'attachment; filename="{SLUG}.wdkb.zip"'
    assert "set-cookie" not in download.headers
    assert len(download.content) == result["size_bytes"]
    assert download.content == package

    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        names = archive.namelist()
        doc_lines = [
            json.loads(line) for line in archive.read("documents.jsonl").decode().splitlines()
        ]
    assert "manifest.json" in names
    assert "documents.jsonl" in names
    assert "chunks.jsonl" in names
    assert "vectors/000000.npy" in names
    assert any(name.startswith("files/") for name in names), names
    # Kontrakt E7-1a §3: ``run`` w ``documents.jsonl`` idzie z DB S U R O W E (kod „3" = DONE,
    # „0" = UNSTART); po nazwie, bo kolejność linii jest po ``id``. DONE ma plik, UNSTART nie.
    runs = {str(line["name"]): str(line["run"]) for line in doc_lines}
    assert runs == {DOC1: "3", DOC2: "0"}, runs
    validated = validate_package(path, max_bytes=MAX_BYTES, max_ratio=MAX_RATIO)
    assert isinstance(validated, ValidatedPackage), validated

    # (h) audyt ``dataset_exported`` istnieje po zakończeniu.
    async with transaction(sm) as session:
        audited = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM audit_log WHERE action = 'dataset_exported'"
                    " AND target_id = :ds"
                ),
                {"ds": ds.id},
            )
        ).scalar_one()
    assert int(audited) == 1


async def test_export_restart_leaves_single_package(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """R-KB-04/3: handler uruchomiony dwa razy na tym samym zadaniu → jedna paczka ``exports/``."""
    ds = await _seed_dataset_with_chunks(container, sm)

    async with _client(_app(container, principal_for(ds.tenant_id))) as client:
        task_id = await _start_export(client, ds.id)

    await _run_export_task(container, task_id, repeat=2)

    exports_dir = Path(container.settings.storage_root) / "exports"
    files = sorted(entry.name for entry in exports_dir.iterdir())
    assert files == [f"{task_id}.wdkb.zip"], files


async def test_export_link_expires_and_cleanup_removes_file(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """R-KB-04/4: po dobie link → 410 ``export_expired``; ``run_cleanup`` usuwa plik."""
    ds = await _seed_dataset_with_chunks(container, sm)

    async with _client(_app(container, principal_for(ds.tenant_id))) as client:
        task_id = await _start_export(client, ds.id)
        await _run_export_task(container, task_id)
        result = (await _details(client, task_id))["result"]

    path = export_package_path(container.settings.storage_root, task_id)
    assert path.is_file()
    # Plik ma mtime w chwili eksportu (zegar zamrożony); doba później jest starszy niż retencja.
    stamp_ns = TIME_MS * 1_000_000
    os.utime(path, ns=(stamp_ns, stamp_ns))

    _clock(container).advance(DAY_MS + 1000)

    async with _client(_app(container, None)) as anon:
        expired = await anon.get(result["download_url"])
    assert expired.status_code == _HTTP_EXPIRED, expired.text
    assert expired.json()["error"]["code"] == "export_expired"

    await run_cleanup(container, now_ms=_clock(container).now_ms())
    assert not path.exists()


async def test_export_team_member_is_forbidden(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """R-KB-05/1: członek zespołu (dataset ``team``) → 403 ``forbidden``."""
    ds = await _seed_dataset_with_chunks(container, sm)
    await _set_permission(sm, ds.id, "team")
    member_id = await seed_user(sm)

    async with _client(_app(container, principal_for(member_id))) as client:
        response = await client.post(f"/api/wd/v1/datasets/{ds.id}/export", json={})

    assert response.status_code == _HTTP_FORBIDDEN, response.text
    assert response.json()["error"]["code"] == "forbidden"


async def test_export_changed_signature_and_exp_are_forbidden(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """R-KB-05/3: zmieniony ``sig`` albo ``exp`` → 403 ``invalid_signature``."""
    ds = await _seed_dataset_with_chunks(container, sm)

    async with _client(_app(container, principal_for(ds.tenant_id))) as client:
        task_id = await _start_export(client, ds.id)
        await _run_export_task(container, task_id)
        result = (await _details(client, task_id))["result"]

    exp, sig = _exp_sig(result, task_id)

    async with _client(_app(container, None)) as anon:
        bad_sig = await anon.get(
            f"/api/wd/v1/exports/{task_id}/download", params={"exp": exp, "sig": "0" * 64}
        )
        bad_exp = await anon.get(
            f"/api/wd/v1/exports/{task_id}/download", params={"exp": exp + 1, "sig": sig}
        )

    for response in (bad_sig, bad_exp):
        assert response.status_code == _HTTP_FORBIDDEN, response.text
        assert response.json()["error"]["code"] == "invalid_signature"
    # Kontrola: niezmieniony link i podpis przechodzą (200).
    assert sign_export(_secret(container), task_id, exp) == sig
