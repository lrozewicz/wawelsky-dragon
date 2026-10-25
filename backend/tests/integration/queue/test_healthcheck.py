"""Testy integracyjne healthchecka i wejścia workera na MariaDB (brief T5, wymaganie 4)."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pymysql
import pytest

from app.core.config import Settings
from app.worker import healthcheck
from app.worker.healthcheck import check
from app.worker.loop import host_name
from tests.integration.db.helpers import BACKEND_DIR

pytestmark = pytest.mark.db


def _connect(settings: Settings) -> pymysql.Connection:
    """Połączenie pymysql do bazy testowej (jak w helpers i conftest)."""
    return pymysql.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password.get_secret_value(),
        database=settings.db_name,
    )


def _insert_heartbeat(settings: Settings, worker_id: str, at_ms: int) -> None:
    """Wstawia wiersz worker_heartbeat przez pymysql (brief T5, pkt 4)."""
    connection = _connect(settings)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO worker_heartbeat (worker_id, started_at, heartbeat_at,"
                " capabilities, version) VALUES (%s, %s, %s, '{}', '0.0.0')",
                (worker_id, at_ms, at_ms),
            )
        connection.commit()
    finally:
        connection.close()


def _worker_env(migrated_db: Settings, tmp_path: Path) -> dict[str, str]:
    """Env procesu potomnego (brief T5, pkt 4); WD_DB_* dziedziczone z verify.sh."""
    return {
        **os.environ,
        "WD_ENV": "test",
        "WD_DB_NAME": migrated_db.db_name,
        "WD_STORAGE_ROOT": str(tmp_path),
        "WD_LOG_FORMAT": "json",
    }


async def test_check_true_for_fresh_own_heartbeat(migrated_db: Settings) -> None:
    """Świeży wiersz naszego hosta → check True (brief T5)."""
    _insert_heartbeat(migrated_db, f"{host_name()}:1", int(time.time() * 1000))
    assert await check(migrated_db) is True


async def test_check_false_for_stale_heartbeat(migrated_db: Settings) -> None:
    """Tętno naszego hosta starsze niż 60 s (heartbeat_at = now - 120 s) → False (brief T5)."""
    stale = int(time.time() * 1000) - 120_000
    _insert_heartbeat(migrated_db, f"{host_name()}:1", stale)
    assert await check(migrated_db) is False


async def test_check_false_for_other_host_only(migrated_db: Settings) -> None:
    """Świeży wiersz innego hosta, brak naszego → False (brief T5)."""
    _insert_heartbeat(migrated_db, "innyhost:1", int(time.time() * 1000))
    assert await check(migrated_db) is False


async def test_check_false_for_empty_table(migrated_db: Settings) -> None:
    """Pusta tabela worker_heartbeat → False (brief T5)."""
    assert await check(migrated_db) is False


def test_main_exit_codes(migrated_db: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """main() → 1 na pustej tabeli, 0 po wstawieniu świeżego tętna naszego hosta (brief T5)."""
    monkeypatch.setenv("WD_ENV", "test")
    monkeypatch.setenv("WD_DB_NAME", migrated_db.db_name)
    assert healthcheck.main() == 1
    _insert_heartbeat(migrated_db, f"{host_name()}:1", int(time.time() * 1000))
    assert healthcheck.main() == 0


def test_worker_process_healthcheck_and_sigterm(migrated_db: Settings, tmp_path: Path) -> None:
    """Proces workera: tętno ≤ 20 s, healthcheck 0, SIGTERM → kod 0 (brief T5, pkt 4).

    Stałe argumenty, bez shell (ruff S603 nie flaguje listy z `sys.executable`).
    """
    env = _worker_env(migrated_db, tmp_path)
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.worker.main"],
        cwd=BACKEND_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        connection = _connect(migrated_db)
        try:
            deadline = time.monotonic() + 20.0
            while True:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT COUNT(*) FROM worker_heartbeat WHERE worker_id LIKE %s",
                        (f"{host_name()}:%",),
                    )
                    count = int(cursor.fetchone()[0])
                if count > 0:
                    break
                if time.monotonic() >= deadline:
                    proc.kill()
                    proc.wait(timeout=10)
                    raise AssertionError(
                        "worker nie zapisał tętna w 20 s; wyjście procesu:\n" + proc.stdout.read()
                    )
                time.sleep(0.2)  # sync test — pętla oczekiwania z briefu T5
        finally:
            connection.close()

        # Po starcie workera układ storage istnieje (brief T5, pkt 4).
        assert (tmp_path / "files").is_dir()
        assert (tmp_path / "tmp").is_dir()

        result = subprocess.run(
            [sys.executable, "-m", "app.worker.healthcheck"],
            cwd=BACKEND_DIR,
            env=env,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, f"healthcheck zwrócił kod {result.returncode}, oczekiwano 0"

        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=20) == 0, (
            "worker nie zakończył się kodem 0 po SIGTERM; wyjście procesu:\n" + proc.stdout.read()
        )
    finally:
        if proc.poll() is None:
            proc.kill()
