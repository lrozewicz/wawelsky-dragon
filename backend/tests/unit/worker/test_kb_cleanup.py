"""Testy sprzątania plików eksportu/importu (CONTRACT E7-1f §6, K19 §5).

Bez bazy i bez ``sleep``: zegar zamrożony (``FrozenClock``), sesja to atrapa
(wzorzec ``tests/unit/worker/test_queue_unit.py``), a czasy plików ustawia ``os.utime``.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.worker import kb_cleanup
from app.worker.kb_cleanup import RETENTION_MS, cleanup_loop, run_cleanup
from tests.fakes.clock import FrozenClock

_NOW = 1_790_157_600_000
_OLD_MS = _NOW - RETENTION_MS - 60_000  # 25 h temu — starsze niż doba
_FRESH_MS = _NOW - 60_000  # minutę temu — zostaje
_OLD_ID = "a" * 32


class _FakeResult:
    """Atrapa Result: ``all()`` (wiersze jak z SQL) i ``rowcount``."""

    def __init__(self, rows: list[tuple[Any, ...]] | None = None, rowcount: int = 0) -> None:
        self._rows = rows if rows is not None else []
        self.rowcount = rowcount

    def all(self) -> list[tuple[Any, ...]]:
        return list(self._rows)


class _FakeTransaction:
    """Atrapa transakcji sesji (async context manager)."""

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakeSession:
    """Atrapa AsyncSession: zdejmuje wyniki z kolejki i rejestruje wywołania."""

    def __init__(self, results: list[_FakeResult]) -> None:
        self._results = list(results)
        self.executed: list[tuple[str, dict[str, Any] | None]] = []

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _FakeResult:
        self.executed.append((str(statement), params))
        return self._results.pop(0)

    def begin(self) -> _FakeTransaction:
        return _FakeTransaction()

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakeSessionmaker:
    """Atrapa async_sessionmaker: każde wywołanie zwraca tę samą sesję."""

    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    def __call__(self) -> _FakeSession:
        return self.session


def _container(tmp_path: Path, session: _FakeSession | None = None) -> Container:
    """Kontener testowy: magazyn w tmp_path, sesja to atrapa (wartości z CONTRACT §6)."""
    container = Container(Settings(env="test", storage_root=str(tmp_path)))
    if session is not None:
        container.sessionmaker = cast(async_sessionmaker[AsyncSession], _FakeSessionmaker(session))
    return container


def _put(path: Path, *, mtime_ms: int) -> Path:
    """Tworzy plik z zadanym czasem modyfikacji (sekundy dla ``os.utime``)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    seconds = mtime_ms / 1000
    os.utime(path, (seconds, seconds))
    return path


@pytest.fixture
def session() -> _FakeSession:
    """Sesja-atrapa bez wygasłych wierszy: sam ``SELECT`` z ``expire_older``."""
    return _FakeSession([_FakeResult(rows=[])])


async def test_run_cleanup_removes_only_files_older_than_a_day(
    tmp_path: Path, session: _FakeSession
) -> None:
    """Pliki starsze niż 24 h wypadają z ``exports/`` i ``imports/``; świeże zostają (§6)."""
    old_archive = _put(tmp_path / "exports" / "old.wdkb.zip", mtime_ms=_OLD_MS)
    old_part = _put(tmp_path / "exports" / "old.wdkb.zip.part", mtime_ms=_OLD_MS)
    fresh = _put(tmp_path / "exports" / "fresh.wdkb.zip", mtime_ms=_FRESH_MS)
    old_upload = _put(tmp_path / "imports" / "old.wdkb.zip", mtime_ms=_OLD_MS)

    await run_cleanup(_container(tmp_path, session), now_ms=_NOW)

    assert not old_archive.exists()
    assert not old_part.exists()
    assert not old_upload.exists()
    assert fresh.exists()


async def test_run_cleanup_marks_expired_imports_and_removes_their_files(
    tmp_path: Path,
) -> None:
    """Wiersze ``expires_at < now`` → ``expired``; plik ``imports/<id>.wdkb.zip`` znika (§6)."""
    expired_file = _put(tmp_path / "imports" / f"{_OLD_ID}.wdkb.zip", mtime_ms=_FRESH_MS)
    fresh_file = _put(tmp_path / "imports" / f"{'b' * 32}.wdkb.zip", mtime_ms=_FRESH_MS)
    session = _FakeSession([_FakeResult(rows=[(_OLD_ID,)]), _FakeResult(rowcount=1)])

    await run_cleanup(_container(tmp_path, session), now_ms=_NOW)

    assert not expired_file.exists()
    assert fresh_file.exists()
    statement, params = session.executed[0]
    assert "SELECT id FROM dataset_imports" in statement
    assert params == {"before_ms": _NOW}
    update, update_params = session.executed[1]
    assert "UPDATE dataset_imports SET state = 'expired'" in update
    assert update_params is not None
    assert update_params["before_ms"] == _NOW
    assert update_params["now_ms"] == _NOW


async def test_run_cleanup_without_directories_does_not_fail(
    tmp_path: Path, session: _FakeSession
) -> None:
    """Brak ``exports/``/``imports/`` (świeży magazyn) nie jest błędem (§6)."""
    await run_cleanup(_container(tmp_path, session), now_ms=_NOW)

    assert list(tmp_path.iterdir()) == []  # noqa: ASYNC240 — odczyt katalogu w teście


async def test_cleanup_loop_runs_first_pass_then_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Przegląd przy starcie i wyjście na ``stop`` — bez realnego czekania (§6)."""
    passes: list[int] = []
    stop = asyncio.Event()
    container = _container(tmp_path)
    clock = FrozenClock(_NOW)

    async def _fake_run(container: Container, *, now_ms: int) -> None:
        passes.append(now_ms)
        stop.set()

    monkeypatch.setattr(kb_cleanup, "run_cleanup", _fake_run)
    await asyncio.wait_for(cleanup_loop(container, stop, interval_s=3600, clock=clock), timeout=2)

    assert passes == [_NOW]


async def test_cleanup_loop_repeats_until_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kolejne przebiegi co ``interval_s`` (tu: zero) aż do ``stop`` (§6)."""
    passes: list[int] = []
    stop = asyncio.Event()
    container = _container(tmp_path)
    clock = FrozenClock(_NOW)

    async def _fake_run(container: Container, *, now_ms: int) -> None:
        passes.append(now_ms)
        clock.advance(1000)
        if len(passes) == 3:  # noqa: PLR2004 — trzy przebiegi wystarczą za dowód pętli
            stop.set()

    monkeypatch.setattr(kb_cleanup, "run_cleanup", _fake_run)
    await asyncio.wait_for(cleanup_loop(container, stop, interval_s=0, clock=clock), timeout=2)

    assert passes == [_NOW, _NOW + 1000, _NOW + 2000]


async def test_cleanup_loop_survives_a_failing_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Błąd przebiegu (np. restart MariiDB) nie zabija sprzątania — kolejny idzie dalej (§6)."""
    passes: list[int] = []
    stop = asyncio.Event()
    container = _container(tmp_path)
    clock = FrozenClock(_NOW)

    async def _fake_run(container: Container, *, now_ms: int) -> None:
        passes.append(now_ms)
        if len(passes) == 1:
            raise RuntimeError("MariiDB niedostępna")
        stop.set()

    monkeypatch.setattr(kb_cleanup, "run_cleanup", _fake_run)
    with caplog.at_level(logging.ERROR, logger="app.worker"):
        await asyncio.wait_for(cleanup_loop(container, stop, interval_s=0, clock=clock), timeout=2)

    assert passes == [_NOW, _NOW]
    assert "kb cleanup pass failed" in caplog.text
