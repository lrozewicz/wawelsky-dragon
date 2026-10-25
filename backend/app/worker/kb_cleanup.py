"""Sprzątanie plików tymczasowych eksportu/importu (K19 §5, CONTRACT E7-1f §6).

Przegląd uruchamiany przez workera przy starcie i co ``DEFAULT_INTERVAL_S`` (≤ 1 h):
pliki w ``<storage_root>/exports`` i ``<storage_root>/imports`` starsze niż doba wg mtime
oraz wiersze ``dataset_imports`` po ``expires_at`` (→ ``expired``) wraz z ich plikami.
Zegar jest wstrzykiwany (``now_ms``/``Clock``) — bez ``sleep`` w testach.
"""

import asyncio
import contextlib
import logging
from collections.abc import Sequence
from pathlib import Path

from app.core.container import Container
from app.core.timeutil import Clock
from app.db.repositories import dataset_imports as imports_repo
from app.db.uow import transaction

EXPORTS_DIR = "exports"
IMPORTS_DIR = "imports"

# Dobowa retencja plików tymczasowych (K19 §5) i odstęp przeglądów (≤ 1 h, K19 §5).
RETENTION_MS = 24 * 60 * 60 * 1000
DEFAULT_INTERVAL_S = 3600.0

logger = logging.getLogger("app.worker")


def _remove_stale(directory: Path, *, cutoff_ms: int) -> int:
    """Usuwa pliki z ``directory`` o mtime starszym niż ``cutoff_ms``; brak katalogu → 0.

    Plik zniknięty w trakcie przeglądu (wyścig z handlerem) nie jest błędem —
    ``unlink(missing_ok=True)``.
    """
    if not directory.is_dir():
        return 0
    removed = 0
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        if int(path.stat().st_mtime * 1000) < cutoff_ms:
            path.unlink(missing_ok=True)
            removed += 1
    return removed


def _remove_import_files(root: Path, import_ids: Sequence[str]) -> int:
    """Usuwa paczki wygasłych sesji importu: ``imports/<id>.wdkb.zip`` i ``.part`` (K19 §5)."""
    removed = 0
    for import_id in import_ids:
        for name in (f"{import_id}.wdkb.zip", f"{import_id}.wdkb.zip.part"):
            path = root / IMPORTS_DIR / name
            if path.is_file():
                path.unlink(missing_ok=True)
                removed += 1
    return removed


async def run_cleanup(container: Container, *, now_ms: int) -> None:
    """Jeden przebieg sprzątania (K19 §5): pliki > 24 h i wygasłe sesje importu.

    Wiersze ``dataset_imports`` z ``expires_at < now_ms`` przechodzą w ``expired``;
    pliki tych sesji usuwamy po zmianie stanu (nazwy wracają z repozytorium).
    """
    root = Path(container.settings.storage_root)
    cutoff_ms = now_ms - RETENTION_MS
    removed = _remove_stale(root / EXPORTS_DIR, cutoff_ms=cutoff_ms)
    removed += _remove_stale(root / IMPORTS_DIR, cutoff_ms=cutoff_ms)
    sessionmaker = container.sessionmaker
    if sessionmaker is None:  # pragma: no cover — kontener workera zawsze po start()
        raise RuntimeError("container not started")
    async with transaction(sessionmaker) as session:
        expired = await imports_repo.expire_older(session, before_ms=now_ms, now_ms=now_ms)
    removed += _remove_import_files(root, expired)
    if removed or expired:
        logger.info(
            "kb cleanup finished",
            extra={
                "event": "kb_cleanup",
                "removed_files": removed,
                "expired_imports": len(expired),
            },
        )


async def cleanup_loop(
    container: Container,
    stop: asyncio.Event,
    *,
    interval_s: float = DEFAULT_INTERVAL_S,
    clock: Clock | None = None,
) -> None:
    """Przegląd przy starcie, potem co ``interval_s`` aż do ``stop`` (CONTRACT §6).

    Czekanie to ``stop.wait()`` z limitem, nie ``sleep`` — zatrzymanie workera kończy
    pętlę natychmiast, a brak ``stop`` nie blokuje pierwszy przebieg. Błąd jednego
    przebiegu (np. restart MariiDB) jest logowany i nie zabija sprzątania — wzorzec
    ``Scheduler.run_forever`` (K12 §5).
    """
    time_clock: Clock = clock if clock is not None else container.clock
    while not stop.is_set():
        try:
            await run_cleanup(container, now_ms=time_clock.now_ms())
        except Exception:
            # Błąd przebiegu logujemy, pętla żyje dalej (K19 §5).
            logger.exception("kb cleanup pass failed")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval_s)
