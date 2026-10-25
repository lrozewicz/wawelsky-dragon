"""Test check_ready bez bazy (kontrakt C5) — DB nieosiągalna."""

from app.core.config import Settings
from app.db.engine import make_engine
from app.db.health import check_ready


async def test_check_ready_unavailable() -> None:
    """Port 1: połączenie odrzucone → przyczyna "database unavailable" (engine posprzątany)."""
    engine = make_engine(Settings(env="test", db_host="127.0.0.1", db_port=1))
    try:
        assert await check_ready(engine) == "database unavailable"
    finally:
        await engine.dispose()
