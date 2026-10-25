"""Kontraktowe testy trasy WD ``GET /api/wd/v1/stats`` (zadanie T5, kontrakt E3-6a §2-§4).

Sprawdzają: kształt odpowiedzi na świeżym stosie (same zera), liczniki kolejki po wstawieniu
zadań w stanach queued/running/dead, aktywność workerów wg okna 60 s (czasy przez ``iso_ms``),
straż administratora (401/403) oraz brak ścieżek storage i sekretów w treści odpowiedzi.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.container import Container
from app.core.timeutil import now_ms
from app.core.version import APP_VERSION
from app.db.repositories import tasks as tasks_repo
from app.db.repositories import worker_heartbeat as heartbeat_repo
from app.db.uow import transaction

pytestmark = pytest.mark.contract

OK = 200
UNAUTHORIZED = 401
FORBIDDEN = 403
BASE = "/api/wd/v1/stats"
STALE_HEARTBEAT_MS = 10 * 60 * 1000


async def _seed_task(sm: async_sessionmaker[AsyncSession], *, status: str, timestamp: int) -> None:
    """Wstawia zadanie w zadanym stanie (queued przez repo, inne przez UPDATE statusu)."""
    public_id = uuid.uuid4().hex
    async with transaction(sm) as session:
        await tasks_repo.insert(
            session,
            public_id=public_id,
            task_type="parse_document",
            payload_json="{}",
            document_id=None,
            dataset_id=None,
            priority=0,
            max_attempts=3,
            digest=None,
            next_attempt_at=timestamp,
            now_ms=timestamp,
        )
        if status != "queued":
            await session.execute(
                text("UPDATE tasks SET status = :status WHERE public_id = :public_id"),
                {"status": status, "public_id": public_id},
            )


async def _seed_heartbeat(
    sm: async_sessionmaker[AsyncSession], *, worker_id: str, heartbeat_at: int
) -> None:
    """Zapisuje tętno workera (``started_at`` = ``heartbeat_at``, puste capabilities)."""
    async with transaction(sm) as session:
        await heartbeat_repo.upsert(
            session,
            worker_id=worker_id,
            started_at=heartbeat_at,
            heartbeat_at=heartbeat_at,
            capabilities={},
            version=APP_VERSION,
        )


async def test_stats_returns_zeroes_on_a_fresh_stack(admin: httpx.AsyncClient) -> None:
    """Świeży stos bez workerów i zadań: same zera, sondy zielone (kontrakt §2 ``stats_get``)."""
    response = await admin.get(BASE)

    assert response.status_code == OK, response.text
    data = response.json()["data"]
    assert set(data) == {"version", "database", "storage", "workers", "queue"}
    assert data["version"] == APP_VERSION
    assert set(data["database"]) == {"ok", "elapsed_ms"}
    assert data["database"]["ok"] is True
    assert isinstance(data["database"]["elapsed_ms"], float)
    assert set(data["storage"]) == {"ok", "elapsed_ms"}
    assert data["storage"]["ok"] is True
    assert data["workers"] == {"active": 0, "items": []}
    assert data["queue"] == {"queued": 0, "running": 0, "dead": 0}


async def test_stats_counts_queue_by_status(
    admin: httpx.AsyncClient, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Zadania queued x2, running x1, dead x1 → dokładnie te liczniki (kontrakt §4)."""
    timestamp = now_ms()
    for status in ("queued", "queued", "running", "dead"):
        await _seed_task(sm, status=status, timestamp=timestamp)

    response = await admin.get(BASE)

    assert response.status_code == OK, response.text
    assert response.json()["data"]["queue"] == {"queued": 2, "running": 1, "dead": 1}


async def test_stats_marks_only_fresh_heartbeats_active(
    admin: httpx.AsyncClient,
    sm: async_sessionmaker[AsyncSession],
    container: Container,
) -> None:
    """Tętno z teraz → ``active`` true, sprzed 10 min → false; oba w ``items`` (kontrakt §4)."""
    timestamp = container.clock.now_ms()
    await _seed_heartbeat(sm, worker_id="host-a:1:0", heartbeat_at=timestamp)
    await _seed_heartbeat(sm, worker_id="host-b:2:0", heartbeat_at=timestamp - STALE_HEARTBEAT_MS)

    response = await admin.get(BASE)

    assert response.status_code == OK, response.text
    workers = response.json()["data"]["workers"]
    assert [item["worker_id"] for item in workers["items"]] == ["host-a:1:0", "host-b:2:0"]
    assert {item["worker_id"]: item["active"] for item in workers["items"]} == {
        "host-a:1:0": True,
        "host-b:2:0": False,
    }
    assert workers["active"] == 1
    assert all(item["heartbeat_at"].endswith("Z") for item in workers["items"])


async def test_stats_requires_admin(anon: httpx.AsyncClient, member: httpx.AsyncClient) -> None:
    """Bez nagłówka → 401; zwykły użytkownik → 403 (kontrakt §0 p. 1)."""
    anon_response = await anon.get(BASE)
    member_response = await member.get(BASE)

    assert anon_response.status_code == UNAUTHORIZED, anon_response.text
    assert member_response.status_code == FORBIDDEN, member_response.text


async def test_stats_response_hides_storage_paths_and_secrets(
    admin: httpx.AsyncClient, container: Container
) -> None:
    """Treść odpowiedzi nie zawiera ścieżki storage ani klucza szyfrowania (kontrakt §0 p. 7)."""
    response = await admin.get(BASE)

    assert response.status_code == OK, response.text
    assert str(container.settings.storage_root) not in response.text
    assert container.settings.crypto_key.get_secret_value() not in response.text
