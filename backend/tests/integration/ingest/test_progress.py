"""Testy ProgressReporter na MariaDB — dławienie zapisu postępu (brief T7, kontrakt C7)."""

import re

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.timeutil import Clock
from app.db.repositories import documents as documents_repo
from app.db.repositories.documents import DocumentRow
from app.db.uow import transaction
from app.services.ingest_progress import PROGRESS_THROTTLE_MS, ProgressReporter
from app.worker.errors import TaskLost
from tests.fakes.clock import FrozenClock
from tests.integration.ingest.conftest import make_document_row, seed_dataset

pytestmark = pytest.mark.db

_LINE_RE = re.compile(r"^\d\d:\d\d:\d\d ")


class FakeCtx:
    """Atrapa kontekstu zadania: rejestruje reporty, check_cancel bez skutku (brief T7)."""

    def __init__(self, *, lost: bool = False) -> None:
        self.reports: list[tuple[float, str | None]] = []
        self._lost = lost

    async def report(self, progress: float, msg: str | None = None) -> None:
        self.reports.append((progress, msg))
        if self._lost:
            raise TaskLost("przejęte")

    async def check_cancel(self) -> None:
        return None


async def _insert_document(sm: async_sessionmaker[AsyncSession]) -> DocumentRow:
    """Dokument w bazie (seed_dataset + documents.insert)."""
    ds = await seed_dataset(sm)
    row = make_document_row(ds)
    async with transaction(sm) as session:
        await documents_repo.insert(session, row)
    return row


async def _document(sm: async_sessionmaker[AsyncSession], document_id: str) -> DocumentRow:
    """Świeży odczyt dokumentu w osobnej transakcji."""
    async with transaction(sm) as session:
        row = await documents_repo.get(session, document_id)
    assert row is not None
    return row


def _lines(doc: DocumentRow) -> list[str]:
    """Linie progress_msg dokumentu."""
    return doc.progress_msg.split("\n") if doc.progress_msg else []


def _bodies(lines: list[str]) -> list[str]:
    """Linie bez prefiksu godziny (HH:MM:SS)."""
    return [line.split(" ", 1)[1] for line in lines]


async def test_first_report_writes_immediately(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """Pierwszy report zapisuje od razu (pierwszy zapis obiektu), bez force (brief T7)."""
    doc = await _insert_document(sm)
    clock: Clock = FrozenClock()
    ctx = FakeCtx()
    rep = ProgressReporter(sm, clock, ctx, doc.id)

    await rep.report(0.01, "Task has been received.")

    stored = await _document(sm, doc.id)
    lines = _lines(stored)
    assert len(lines) == 1
    assert _LINE_RE.match(lines[0])
    assert _bodies(lines) == ["Task has been received."]
    assert stored.progress == 0.01  # noqa: PLR2004 — wartości postępu z tabeli kontraktu C7
    assert ctx.reports == [(0.01, "Task has been received.")]


async def test_second_report_within_throttle_is_buffered(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """Drugi report w < 1000 ms nie zapisuje — linia czeka w buforze (brief T7)."""
    doc = await _insert_document(sm)
    rep = ProgressReporter(sm, FrozenClock(), FakeCtx(), doc.id)

    await rep.report(0.01, "pierwsza")
    await rep.report(0.40, "druga")

    stored = await _document(sm, doc.id)
    assert _bodies(_lines(stored)) == ["pierwsza"]
    assert stored.progress == 0.01  # noqa: PLR2004 — wartości postępu z tabeli kontraktu C7


async def test_force_writes_buffered_lines(sm: async_sessionmaker[AsyncSession]) -> None:
    """force=True zapisuje bufor także przed upływem dławienia (brief T7)."""
    doc = await _insert_document(sm)
    rep = ProgressReporter(sm, FrozenClock(), FakeCtx(), doc.id)

    await rep.report(0.01, "pierwsza")
    await rep.report(0.40, "druga")
    await rep.report(0.60, "trzecia", force=True)

    stored = await _document(sm, doc.id)
    assert _bodies(_lines(stored)) == ["pierwsza", "druga", "trzecia"]
    assert stored.progress == 0.60  # noqa: PLR2004 — wartości postępu z tabeli kontraktu C7


async def test_advance_past_throttle_writes_overdue_lines(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """Po >= PROGRESS_THROTTLE_MS kolejny report zapisuje obie zaległe linie (brief T7)."""
    doc = await _insert_document(sm)
    clock = FrozenClock()
    rep = ProgressReporter(sm, clock, FakeCtx(), doc.id)

    await rep.report(0.01, "pierwsza")
    await rep.report(0.40, "druga")
    clock.advance(PROGRESS_THROTTLE_MS)
    await rep.report(0.60, "trzecia")

    stored = await _document(sm, doc.id)
    assert _bodies(_lines(stored)) == ["pierwsza", "druga", "trzecia"]
    assert stored.progress == 0.60  # noqa: PLR2004 — wartości postępu z tabeli kontraktu C7


async def test_flush_writes_buffer(sm: async_sessionmaker[AsyncSession]) -> None:
    """flush() dopisuje zaległy bufor do progress_msg; drugi flush bez skutku (brief T7)."""
    doc = await _insert_document(sm)
    rep = ProgressReporter(sm, FrozenClock(), FakeCtx(), doc.id)

    await rep.report(0.01, "pierwsza")
    await rep.report(0.40, "druga")
    await rep.flush()

    stored = await _document(sm, doc.id)
    lines = _lines(stored)
    assert _bodies(lines) == ["pierwsza", "druga"]
    assert stored.progress == 0.40  # noqa: PLR2004 — wartości postępu z tabeli kontraktu C7
    await rep.flush()

    again = await _document(sm, doc.id)
    assert _lines(again) == lines


async def test_report_without_msg_appends_no_empty_line(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """report(progress) bez msg nie dopisuje pustej linii (brief T7)."""
    doc = await _insert_document(sm)
    rep = ProgressReporter(sm, FrozenClock(), FakeCtx(), doc.id)

    await rep.report(0.01, "pierwsza")
    await rep.report(0.50)  # bez msg; wyzwolony flush ma pusty bufor → bez zapisu
    await rep.report(0.90, "ostatnia", force=True)

    stored = await _document(sm, doc.id)
    lines = _lines(stored)
    assert _bodies(lines) == ["pierwsza", "ostatnia"]
    assert all(line.strip() for line in lines)
    assert stored.progress == 0.90  # noqa: PLR2004 — wartości postępu z tabeli kontraktu C7


async def test_task_lost_from_ctx_passes_through(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """TaskLost z heartbeatu przepuszczamy — brak zapisu do dokumentu (C7)."""
    doc = await _insert_document(sm)
    rep = ProgressReporter(sm, FrozenClock(), FakeCtx(lost=True), doc.id)

    try:
        await rep.report(0.01, "Task has been received.")
    except TaskLost:
        pass
    else:  # pragma: no cover
        raise AssertionError("TaskLost musiał przelecieć")

    stored = await _document(sm, doc.id)
    assert stored.progress_msg == ""
