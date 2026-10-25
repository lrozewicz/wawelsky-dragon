"""Handler zadania ``export_dataset`` — budowa paczki ``.wdkb.zip`` (K19 §3, CONTRACT E7-1a §3).

Zadanie zleca ``start`` (T1) z payloadem ``actor_id``/``include_vectors``; ``dataset_id`` jest
kolumną zadania. ``build_package`` (``app.services.kb_export_build``) pisze paczkę strumieniowo,
raportując etapy przez ``_TaskProgress`` (payload ``stage``/``done``/``total`` + heartbeat).
``build_package`` wywołuje ``writer.abort()`` przy każdym wyjątku (także ``TaskCancelled``),
więc ``.part`` znika; tutaj mapujemy porażki trwałe na ``error_code`` w payloadzie
(``package_too_large``, ``manifest_too_large``) i po sukcesie zapisujemy ``result`` + wpis audytu
``dataset_exported``. Ponowienie po restarcie workera idzie od zera: na starcie usuwamy stary
``.part``/plik tego ``task_id``, wynik = jedna paczka ``exports/<task_id>.wdkb.zip``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import users as users_repo
from app.db.repositories.task_payload import patch_payload
from app.db.uow import transaction
from app.services.kb_export_build import (
    BuildResult,
    ManifestTooLarge,
    PackageTooLarge,
    build_package,
)
from app.services.kb_export_link import (
    EXPORT_LINK_TTL_S,
    download_path,
    export_package_path,
    sign_export,
)
from app.worker.errors import PermanentError, TaskCancelled

if TYPE_CHECKING:
    from app.core.container import Container
    from app.worker.context import TaskContext
    from app.worker.queue import TaskRow

__all__ = ["export_dataset"]

# Progres 0..1 wg etapów (CONTRACT §3): files → chunks → vectors → finish.
_BANDS: dict[str, tuple[float, float]] = {
    "files": (0.0, 0.1),
    "chunks": (0.1, 0.4),
    "vectors": (0.4, 0.95),
}
_LABELS: dict[str, str] = {
    "files": "Pliki",
    "chunks": "Chunki",
    "vectors": "Wektory",
    "finalize": "Finalizacja",
}


class _ExportFailure(PermanentError):
    """Porażka trwała eksportu z kodem dla ``payload.error_code`` i ``WdTask.error.code``."""

    def __init__(self, message: str, *, error_code: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class _TaskProgress:
    """``ExportProgress`` (CONTRACT §3) na ``TaskContext``: payload + heartbeat z postępem."""

    def __init__(self, ctx: TaskContext) -> None:
        self._ctx = ctx

    async def stage(self, stage: str, done: int, total: int) -> None:
        """Zapisuje ``stage``/``done``/``total`` w payloadzie i raportuje heartbeat (bez cancel)."""
        container = self._ctx.container
        now = container.clock.now_ms()
        async with transaction(_sessionmaker(container)) as session:
            await patch_payload(
                session,
                public_id=self._ctx.task.id,
                patch={"stage": stage, "done": done, "total": total},
                now_ms=now,
            )
        await self._ctx.report(_progress(stage, done, total), f"{_LABELS[stage]} {done}/{total}")

    async def check_cancel(self) -> None:
        """Rzuca ``TaskCancelled``, gdy zadanie ma zaplanowane anulowanie."""
        await self._ctx.check_cancel()


def _progress(stage: str, done: int, total: int) -> float:
    """Postęp 0..1 dla etapu i licznika (``done``/``total``)."""
    if stage == "finalize":
        return 1.0
    low, high = _BANDS[stage]
    return high if total <= 0 else low + (high - low) * (done / total)


async def export_dataset(task: TaskRow, ctx: TaskContext) -> None:
    """Buduje paczkę datasetu z zadania (CONTRACT §3); wyjątki rozstrzyga kolejka."""
    container = ctx.container
    actor_id, include_vectors = _payload(task)
    dataset_id = task.dataset_id
    if dataset_id is None:
        raise _ExportFailure("Zadanie eksportu bez dataset_id", error_code="not_found")
    _remove_stale(container, task.id)
    progress = _TaskProgress(ctx)
    try:
        result = await build_package(
            container,
            task_id=task.id,
            dataset_id=dataset_id,
            include_vectors=include_vectors,
            progress=progress,
        )
    except TaskCancelled:
        raise
    except ManifestTooLarge as exc:
        await _set_error_code(ctx, "manifest_too_large")
        raise _ExportFailure(str(exc), error_code="manifest_too_large") from exc
    except PackageTooLarge as exc:
        await _set_error_code(ctx, "package_too_large")
        raise _ExportFailure(str(exc), error_code="package_too_large") from exc
    await _finish(ctx, result=result)
    await _audit(
        ctx,
        actor_id=actor_id,
        dataset_id=dataset_id,
        include_vectors=include_vectors,
        size_bytes=result.size_bytes,
    )


def _payload(task: TaskRow) -> tuple[str, bool]:
    """Odczyt payloadu: ``(actor_id, include_vectors)``; brak klucza → porażka trwała."""
    payload = task.payload
    try:
        actor_id = str(payload["actor_id"])
        include_vectors = bool(payload["include_vectors"])
    except KeyError as exc:
        message = f"Zadanie eksportu bez pola {exc.args[0]}"
        raise _ExportFailure(message, error_code="validation_failed") from exc
    return actor_id, include_vectors


def _remove_stale(container: Container, task_id: str) -> None:
    """Usuwa stary ``.part``/gotowy plik tego ``task_id`` przed budową (ponowienie)."""
    path = export_package_path(container.settings.storage_root, task_id)
    path.unlink(missing_ok=True)
    path.with_name(path.name + ".part").unlink(missing_ok=True)


async def _finish(ctx: TaskContext, *, result: BuildResult) -> None:
    """Zapisuje ``result`` (ExportResult, K19 §3) z podpisanym linkiem ważnym 24 h."""
    container = ctx.container
    now_ms = container.clock.now_ms()
    exp = now_ms // 1000 + EXPORT_LINK_TTL_S
    sig = sign_export(container.settings.secret_key.get_secret_value(), ctx.task.id, exp)
    result_dict: dict[str, Any] = {
        "download_url": download_path(ctx.task.id, exp, sig),
        "expires_at": exp * 1000,
        "size_bytes": result.size_bytes,
        "file_name": result.file_name,
    }
    async with transaction(_sessionmaker(container)) as session:
        await patch_payload(
            session, public_id=ctx.task.id, patch={"result": result_dict}, now_ms=now_ms
        )


async def _set_error_code(ctx: TaskContext, code: str) -> None:
    """Zapisuje ``error_code`` w payloadzie przy porażce trwałej (CONTRACT §3)."""
    container = ctx.container
    now = container.clock.now_ms()
    async with transaction(_sessionmaker(container)) as session:
        await patch_payload(session, public_id=ctx.task.id, patch={"error_code": code}, now_ms=now)


async def _audit(
    ctx: TaskContext, *, actor_id: str, dataset_id: str, include_vectors: bool, size_bytes: int
) -> None:
    """Wpis audytu ``dataset_exported`` (K19 §3 Uprawnienia) po udanym eksporcie."""
    audit = ctx.container.audit
    if audit is None:
        raise RuntimeError("container not started")
    await audit.record(
        actor_label=await _actor_label(ctx.container, actor_id),
        action="dataset_exported",
        target_type="dataset",
        target_id=dataset_id,
        details={
            "dataset_id": dataset_id,
            "task_id": ctx.task.id,
            "include_vectors": include_vectors,
            "size_bytes": size_bytes,
        },
        actor_id=actor_id,
    )


async def _actor_label(container: Container, actor_id: str) -> str:
    """Etykieta aktora do audytu: e-mail użytkownika, a gdy brak wiersza — jego id."""
    async with transaction(_sessionmaker(container)) as session:
        row = await users_repo.get_by_id(session, actor_id)
    return row.email if row is not None else actor_id


def _sessionmaker(container: Container) -> async_sessionmaker[AsyncSession]:
    """Fabryka sesji z kontenera; brak (kontener nie wystartował) → ``RuntimeError``."""
    sessionmaker = container.sessionmaker
    if sessionmaker is None:
        raise RuntimeError("container not started")
    return sessionmaker
