"""Testy endpointu gotowości na prawdziwej migracji alembic (brief T4, kontrakt C7/C8).

Wszystkie synchroniczne (`def`) — env.py robi `asyncio.run` (kontrakt C7/C12).
"""

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from alembic import command
from app.core.config import Settings
from app.db.schema import SCHEMA_HEAD
from app.main import create_app
from tests.integration.db.helpers import alembic_cfg

pytestmark = pytest.mark.db

_OK = 200
_NOT_READY = 503
_NOT_MIGRATED = f"schema not migrated (expected {SCHEMA_HEAD})"


def _ready(app: Settings) -> Response:
    """Odpowiedź /health/ready aplikacji na danej bazie (TestClient z lifespan)."""
    with TestClient(create_app(app)) as c:
        return c.get("/health/ready")


def test_ready_503_before_migration(fresh_db: Settings) -> None:
    """Świeża baza, bez migracji → 503 not_ready z komunikatem o braku migracji."""
    resp = _ready(fresh_db)
    assert resp.status_code == _NOT_READY
    body = resp.json()
    assert body["error"]["code"] == "not_ready"
    assert body["error"]["message"] == _NOT_MIGRATED


def test_ready_200_after_migration(fresh_db: Settings) -> None:
    """Po `upgrade head` → 200 {"status": "ready"}."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    resp = _ready(fresh_db)
    assert resp.status_code == _OK
    assert resp.json() == {"status": "ready"}


def test_ready_503_after_downgrade(fresh_db: Settings) -> None:
    """Po `downgrade base` → znowu 503 not_ready (schema not migrated)."""
    cfg = alembic_cfg(fresh_db)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    resp = _ready(fresh_db)
    assert resp.status_code == _NOT_READY
    assert resp.json()["error"]["code"] == "not_ready"
    assert resp.json()["error"]["message"] == _NOT_MIGRATED
