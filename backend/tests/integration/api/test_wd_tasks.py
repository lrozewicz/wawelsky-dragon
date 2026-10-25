"""Testy HTTP tras zadań WD ``/api/wd/v1/tasks/{task_id}`` (K19 §3 trasy 3-4).

Zakres: inicjator widzi własne zadanie, obcy dostaje 404 (nie zdradzamy istnienia),
superuser widzi cudze, zadanie innego typu jest nieobecne, brak sesji → 401,
stop ``queued`` → ``stopped: true`` + ``cancel_requested``, stop po ``done`` → ``false``,
status wewnętrzny ``dead`` → ``failed``, kształt ``data`` zgodny z K19 §3.
"""

import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.auth.principal import get_principal
from app.core.config import Settings
from app.core.container import Container
from app.db.uow import transaction
from app.domain.policy import Principal
from app.main import create_app
from app.worker.queue import DbTaskQueue, NewTask
from tests.integration.chat.conftest import seed_user
from tests.integration.ingest.pipeline_helpers import make_container
from tests.integration.retrieval.conftest import principal_for

pytestmark = pytest.mark.db

_HTTP_OK = 200
_HTTP_UNAUTHORIZED = 401
_HTTP_NOT_FOUND = 404
_WORKER_ID = "w:1:0"

# K19 §3: klucze ``WdTask`` (kolejność nieznacząca — porównujemy zbiór).
_WD_TASK_KEYS = {
    "task_id",
    "kind",
    "dataset_id",
    "status",
    "stage",
    "done",
    "total",
    "progress",
    "message",
    "error",
    "created_at",
    "finished_at",
    "result",
}

_EXPORT_RESULT: dict[str, Any] = {
    "download_url": "/api/wd/v1/exports/abc/download?exp=1&sig=deadbeef",
    "expires_at": 1_790_000_000_000,
    "size_bytes": 123,
    "file_name": "korpus.wdkb.zip",
}


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener testowy ze magazynem w tmp_path (wzorzec ``tests/integration/api``)."""
    instance = await make_container(migrated_db, tmp_path)
    yield instance
    await instance.aclose()


def _app(container: Container, principal: Principal | None) -> FastAPI:
    """Aplikacja na żywym kontenerze; ``principal=None`` → brak nadpisania (ścieżka 401)."""
    app = create_app(container.settings, container)
    if principal is not None:
        app.dependency_overrides[get_principal] = lambda: principal
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    """Klient ASGI nad aplikacją testową."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _queue(container: Container) -> DbTaskQueue:
    """Kolejka na usługach kontenera (enqueue/claim/complete)."""
    return DbTaskQueue(
        cast("async_sessionmaker[AsyncSession]", container.sessionmaker),
        container.clock,
        container.id_gen,
    )


async def _enqueue(container: Container, task_type: str, payload: dict[str, Any]) -> str:
    """Wstawia zadanie danego typu z payloadem; zwraca ``task_id``."""
    return await _queue(container).enqueue(NewTask(cast("Any", task_type), payload))


async def test_own_export_task_has_the_contract_shape(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Inicjator: 200, ``kind=export``, ``status=queued`` i pełny zestaw pól ``WdTask``."""
    alice_id = await seed_user(sm)
    task_id = await _enqueue(
        container, "export_dataset", {"actor_id": alice_id, "include_vectors": True}
    )

    async with _client(_app(container, principal_for(alice_id))) as client:
        response = await client.get(f"/api/wd/v1/tasks/{task_id}")

    assert response.status_code == _HTTP_OK, response.text
    data = response.json()["data"]
    assert set(data) == _WD_TASK_KEYS
    assert (data["task_id"], data["kind"], data["status"]) == (task_id, "export", "queued")
    assert data["stage"] is None
    assert (data["done"], data["total"]) == (0, 0)
    assert data["message"] == ""
    assert data["error"] is None
    assert data["result"] is None
    assert data["finished_at"] is None
    assert data["created_at"] > 0


async def test_foreign_user_does_not_see_the_task(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Obcy użytkownik: 404 ``not_found`` — zadanie nie istnieje w jego przestrzeni."""
    owner_id = await seed_user(sm)
    stranger_id = await seed_user(sm)
    task_id = await _enqueue(container, "export_dataset", {"actor_id": owner_id})

    async with _client(_app(container, principal_for(stranger_id))) as client:
        response = await client.get(f"/api/wd/v1/tasks/{task_id}")

    assert response.status_code == _HTTP_NOT_FOUND, response.text
    assert response.json()["error"]["code"] == "not_found"


async def test_superuser_sees_a_foreign_task(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Superuser: 200 na cudzym zadaniu (K19 §Uprawnienia tras 3-4)."""
    owner_id = await seed_user(sm)
    admin_id = await seed_user(sm)
    task_id = await _enqueue(container, "import_dataset", {"actor_id": owner_id, "import_id": "i"})

    async with _client(_app(container, principal_for(admin_id, superuser=True))) as client:
        response = await client.get(f"/api/wd/v1/tasks/{task_id}")

    assert response.status_code == _HTTP_OK, response.text
    assert response.json()["data"]["kind"] == "import"


async def test_task_of_another_type_is_not_found(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Zadanie ``parse_document`` (nawet właściciela) nie ma trasy w powierzchni WD (§3)."""
    alice_id = await seed_user(sm)
    task_id = await _enqueue(container, "parse_document", {"actor_id": alice_id})

    async with _client(_app(container, principal_for(alice_id))) as client:
        response = await client.get(f"/api/wd/v1/tasks/{task_id}")

    assert response.status_code == _HTTP_NOT_FOUND, response.text


async def test_unknown_task_id_is_not_found(container: Container) -> None:
    """Nieznany ``task_id`` → 404 (bez odróżnienia od cudzego zadania)."""
    alice_id = uuid.uuid4().hex

    async with _client(_app(container, principal_for(alice_id))) as client:
        response = await client.get(f"/api/wd/v1/tasks/{alice_id}")

    assert response.status_code == _HTTP_NOT_FOUND, response.text


async def test_without_session_returns_401(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Brak nagłówka ``Authorization`` → 401 kopertą WD (K3)."""
    alice_id = await seed_user(sm)
    task_id = await _enqueue(container, "export_dataset", {"actor_id": alice_id})

    async with _client(_app(container, None)) as client:
        response = await client.get(f"/api/wd/v1/tasks/{task_id}")

    assert response.status_code == _HTTP_UNAUTHORIZED, response.text
    assert response.json()["error"]["code"] == "unauthorized"


async def test_stop_queued_task_requests_cancel(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Stop zadania ``queued``: 200 ``stopped: true`` i zapisane ``cancel_requested``."""
    alice_id = await seed_user(sm)
    task_id = await _enqueue(container, "export_dataset", {"actor_id": alice_id})

    async with _client(_app(container, principal_for(alice_id))) as client:
        response = await client.post(f"/api/wd/v1/tasks/{task_id}/stop")

    assert response.status_code == _HTTP_OK, response.text
    assert response.json()["data"] == {"stopped": True}
    async with transaction(sm) as session:
        row = (
            (
                await session.execute(
                    text("SELECT cancel_requested, status FROM tasks WHERE public_id = :id"),
                    {"id": task_id},
                )
            )
            .mappings()
            .one()
        )
    assert (int(row["cancel_requested"]), row["status"]) == (1, "queued")


async def test_stop_finished_task_returns_false(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Stop zadania już ``done``: ``stopped: false`` (K19 §3 trasa 4)."""
    alice_id = await seed_user(sm)
    task_id = await _enqueue(
        container,
        "export_dataset",
        {
            "actor_id": alice_id,
            "stage": "finalize",
            "done": 3,
            "total": 3,
            "result": _EXPORT_RESULT,
        },
    )
    queue = _queue(container)
    claimed = await queue.claim(_WORKER_ID, ["export_dataset"])
    assert claimed is not None
    await queue.complete(task_id, _WORKER_ID)

    async with _client(_app(container, principal_for(alice_id))) as client:
        stop = await client.post(f"/api/wd/v1/tasks/{task_id}/stop")
        detail = await client.get(f"/api/wd/v1/tasks/{task_id}")

    assert stop.status_code == _HTTP_OK, stop.text
    assert stop.json()["data"] == {"stopped": False}
    data = detail.json()["data"]
    assert data["status"] == "done"
    assert (data["stage"], data["done"], data["total"]) == ("finalize", 3, 3)
    assert data["result"] == _EXPORT_RESULT
    assert data["finished_at"] is not None


async def test_dead_task_is_reported_as_failed(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Status wewnętrzny ``dead`` → ``failed`` z komunikatem z kolumny ``error`` (§3)."""
    alice_id = await seed_user(sm)
    task_id = await _enqueue(container, "import_dataset", {"actor_id": alice_id, "import_id": "i"})
    queue = _queue(container)
    claimed = await queue.claim(_WORKER_ID, ["import_dataset"])
    assert claimed is not None
    await queue.fail(task_id, _WORKER_ID, RuntimeError("padło"), transient=True)
    async with transaction(sm) as session:
        await session.execute(
            text("UPDATE tasks SET status = 'dead' WHERE public_id = :id"), {"id": task_id}
        )

    async with _client(_app(container, principal_for(alice_id))) as client:
        response = await client.get(f"/api/wd/v1/tasks/{task_id}")

    assert response.status_code == _HTTP_OK, response.text
    data = response.json()["data"]
    assert data["status"] == "failed"
    assert data["error"] == {"code": "task_failed", "message": "padło"}


async def test_import_result_uses_the_import_shape(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Wynik importu w ``payload["result"]`` serializuje się jak ``ImportResult`` (unia §3)."""
    alice_id = await seed_user(sm)
    result = {
        "dataset_id": "d" * 32,
        "dataset_name": "Korpus z paczki",
        "documents": 2,
        "chunks": 5,
        "reembedded": False,
    }
    task_id = await _enqueue(
        container, "import_dataset", {"actor_id": alice_id, "import_id": "i", "result": result}
    )
    queue = _queue(container)
    claimed = await queue.claim(_WORKER_ID, ["import_dataset"])
    assert claimed is not None
    await queue.complete(task_id, _WORKER_ID)

    async with _client(_app(container, principal_for(alice_id))) as client:
        response = await client.get(f"/api/wd/v1/tasks/{task_id}")

    assert response.status_code == _HTTP_OK, response.text
    assert response.json()["data"]["result"] == result
