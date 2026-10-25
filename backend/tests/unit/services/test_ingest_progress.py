"""Test `ProgressReporter.last_progress` — bieżący procent dla hooka logu zadania (C1)."""

from app.services.ingest_progress import ProgressReporter
from tests.fakes.clock import FrozenClock


class _Ctx:
    """Atrapa kontekstu zadania: report bez skutku (bez DB)."""

    async def report(self, _progress: float, _msg: str | None = None) -> None:
        return None


async def test_last_progress_tracks_reports_without_db_write() -> None:
    """`last_progress` startuje z 0.0 i idzie za reportem; bez msg nie dotyka bazy (C1)."""
    rep = ProgressReporter(None, FrozenClock(), _Ctx(), "doc")  # type: ignore[arg-type]
    assert rep.last_progress == 0.0
    await rep.report(0.4)  # bez msg → pusty bufor → flush nie sięga do sessionmaker
    assert rep.last_progress == 0.4  # noqa: PLR2004 — wartość postępu z tabeli kontraktu C7
