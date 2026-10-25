"""Trafność szacunku rozmiaru paczki eksportu na prawdziwej ingestii (K19 §3 trasa 1; E7-H1/T5).

Cel zadania: podgląd eksportu (``estimated_bytes`` / ``estimated_bytes_with_vectors``) ma
szacować realną paczkę z odchyłką ≤ 25 % w obie strony. Test przechodzi ścieżkę użytkownika:
upload dwóch plików korpusu przez prawdziwą ingestię (``run_parse``) → eksport handlerem
``export_dataset`` (jak worker) → porównanie odpowiedzi podglądu z rozmiarem PLIKU paczki,
dla ``include_vectors=true`` i ``false``. Model: pliki źródłowe 1:1, tekst po DEFLATE,
wektory NPY float32 bez kompresji (``docs/perf/E7-H1.md``).

Marker ``db`` + ``fakellm``: wymaga MariaDB i fake-llm (``WD_LLM_BASE_URL`` z ``verify.sh``).
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.auth.principal import get_principal
from app.core.config import Settings
from app.core.container import Container
from app.db.repositories import documents as documents_repo
from app.db.repositories.datasets import DatasetRow
from app.db.uow import transaction
from app.domain.policy import Principal
from app.main import create_app
from app.services.ingest_pipeline import run_parse
from app.worker.context import TaskContext
from app.worker.kb_handlers import KB_HANDLERS
from app.worker.queue import DbTaskQueue, TaskRow
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

# Korpus testowy repo: dwa realne polskie pliki tekstowe (jak test round-trip E7-H1/T2).
CORPUS_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "retrieval"
DOCS = ("umowa-najmu.txt", "regulamin-urlopow.txt")

RUN_DONE = "3"  # RUN_CODES["DONE"]
WORKER_ID = "estimate:1:0"
TOLERANCE = 0.25
_HTTP_OK = 200
_HTTP_ACCEPTED = 202


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener ze storage w tmp_path i modelami fake (wzorzec ``tests/integration/api``)."""
    instance = await make_container(migrated_db, tmp_path)
    yield instance
    await instance.aclose()


def _sm(container: Container) -> async_sessionmaker[AsyncSession]:
    """Fabryka sesji z kontenera (istnieje po ``start()``)."""
    sessionmaker = container.sessionmaker
    assert sessionmaker is not None, "container nie wystartował"
    return sessionmaker


def _app(container: Container, principal: Principal | None) -> FastAPI:
    """Aplikacja na żywym kontenerze; ``principal=None`` → brak nadpisania aktora."""
    app = create_app(container.settings, container)
    if principal is not None:
        app.dependency_overrides[get_principal] = lambda: principal
    return app


def _client(container: Container, principal: Principal | None) -> httpx.AsyncClient:
    """Klient ASGI nad aplikacją testową (jeden event loop)."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(container, principal)), base_url="http://test"
    )


def _queue(container: Container) -> DbTaskQueue:
    """Kolejka na usługach kontenera (enqueue/claim/complete/snapshot)."""
    return DbTaskQueue(_sm(container), container.clock, container.id_gen)


def _ctx(container: Container, task: TaskRow) -> TaskContext:
    """Kontekst zadania dla handlera (logger bez handlera, kolejka z kontenera)."""
    logger: logging.LoggerAdapter[logging.Logger] = logging.LoggerAdapter(
        logging.getLogger("test.kb_export_estimate"), {"task_id": task.id}
    )
    return TaskContext(
        task=task, worker_id=WORKER_ID, container=container, logger=logger, queue=_queue(container)
    )


async def _ingest_corpus(container: Container, dataset_id: str, name: str) -> None:
    """Wgrywa plik korpusu i prowadzi go przez ``run_parse`` — realna ingestia (chunki+wektory)."""
    data = (CORPUS_DIR / name).read_bytes()
    doc = await container.ingest.upload(dataset_id, make_source(data, name), created_by=dataset_id)
    ctx = await claim_context(container, doc.id)
    await run_parse(container, ctx.task, ctx, executor=None)
    async with transaction(_sm(container)) as session:
        row = await documents_repo.get(session, doc.id)
    assert row is not None and row.run == RUN_DONE, "prawdziwa ingestia musi dać „zakończony”"
    assert row.chunk_count > 0, "prawdziwa ingestia musi dać chunki"


async def _preview(container: Container, dataset_id: str, tenant_id: str) -> dict[str, Any]:
    """Odpowiedź trasy 1 (``ExportPreview``) dla właściciela datasetu."""
    async with _client(container, principal_for(tenant_id)) as client:
        response = await client.get(f"/api/wd/v1/datasets/{dataset_id}/export/preview")
    assert response.status_code == _HTTP_OK, response.text
    data: dict[str, Any] = response.json()["data"]
    return data


async def _export_package(
    container: Container, dataset_id: str, tenant_id: str, *, include_vectors: bool
) -> int:
    """Zleca eksport (trasa 2), wykonuje handler i zwraca rozmiar PLIKU paczki w bajtach."""
    async with _client(container, principal_for(tenant_id)) as client:
        started = await client.post(
            f"/api/wd/v1/datasets/{dataset_id}/export",
            json={"include_vectors": include_vectors},
        )
    assert started.status_code == _HTTP_ACCEPTED, started.text
    task_id: str = started.json()["data"]["task_id"]

    queue = _queue(container)
    task = await queue.claim(WORKER_ID, ["export_dataset"])
    assert task is not None and task.id == task_id, "zadanie eksportu musi być do wzięcia"
    await KB_HANDLERS["export_dataset"](task, _ctx(container, task))
    await queue.complete(task.id, WORKER_ID)

    path = Path(container.settings.storage_root) / "exports" / f"{task_id}.wdkb.zip"
    assert path.is_file(), "eksport musi zostawić plik paczki"
    return path.stat().st_size


async def _seed_corpus_dataset(container: Container) -> DatasetRow:
    """Dataset z dwoma dokumentami korpusu przez prawdziwą ingestię (jak E7-H1/T2)."""
    dataset = await seed_dataset(_sm(container))
    for name in DOCS:
        await _ingest_corpus(container, dataset.id, name)
    return dataset


@pytest.mark.parametrize("include_vectors", [False, True])
async def test_estimate_matches_the_exported_package(
    container: Container, include_vectors: bool
) -> None:
    """Szacunek podglądu vs realny plik paczki: odchyłka względna ≤ 0,25 w obie strony.

    Warianty ``include_vectors`` w osobnych przypadkach parametryzacji (każdy zakłada własny
    dataset), żeby eksport nie zależał od kolejności ani stanu poprzedniego zadania.
    """
    dataset = await _seed_corpus_dataset(container)
    preview = await _preview(container, dataset.id, dataset.tenant_id)
    actual = await _export_package(
        container, dataset.id, dataset.tenant_id, include_vectors=include_vectors
    )
    key = "estimated_bytes_with_vectors" if include_vectors else "estimated_bytes"
    estimated = int(preview[key])
    assert actual > 0
    assert abs(estimated / actual - 1) <= TOLERANCE, (key, estimated, actual)
