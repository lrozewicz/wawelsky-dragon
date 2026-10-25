"""Handler zadania ``import_dataset`` — import paczki ``.wdkb.zip`` (K19 §3/§5, CONTRACT E7-1b §3).

Zadanie zleca ``start`` (T6) z payloadem ``actor_id``/``import_id``/``name``/``embedding_model``/
``dataset_id``/``reembed``; ``dataset_id`` jest ustalone raz, więc ponowienie po restarcie workera
sprząta poprzednią próbę i pracuje na tym samym id (dokładnie jeden dataset po ukończeniu). Stop
(``TaskCancelled``) albo porażka trwała sprzątają częściowy import i ustawiają sesję ``invalid``;
wyjątek leci dalej, więc kolejka zamyka zadanie jako ``cancelled``/``failed``. Wyjątek przejściowy
NIE sprząta — następna próba posprząta resztki (wymaganie 4).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import bindparam, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import NotFound
from app.core.timeutil import from_ms
from app.db.repositories import chunks as chunks_repo
from app.db.repositories import dataset_imports as imports_repo
from app.db.repositories import datasets as datasets_repo
from app.db.repositories import documents as documents_repo
from app.db.repositories import users as users_repo
from app.db.repositories.task_payload import patch_payload
from app.db.uow import transaction
from app.services.datasets import EMBEDDING_PROBE_TEXT
from app.services.kb_import_chunks import write_chunks
from app.services.kb_import_embed import embed_chunks
from app.services.kb_import_write import (
    ImportPlan,
    create_dataset_with_documents,
    remove_partial_import,
)
from app.services.kb_package.reader import PackageReader
from app.services.kb_package.validate import ValidatedPackage, validate_package
from app.worker.errors import PermanentError, TaskCancelled
from app.worker.kb_cleanup import IMPORTS_DIR

if TYPE_CHECKING:
    from app.core.container import Container
    from app.llm.gateway import LLMGateway
    from app.llm.registry import ModelRegistry
    from app.llm.types import ModelRef
    from app.worker.context import TaskContext
    from app.worker.queue import TaskRow

__all__ = ["import_dataset"]

IMPORT_SUFFIX = ".wdkb.zip"
DONE_RUN = "3"  # RUN_CODES["DONE"] — „zakończony" z paczki przetrwa import (K19 §2)
NAME_CONFLICT_CONSTRAINT = "uq_datasets_tenant_name_ci"

# Postęp 0..1 wg etapów (CONTRACT §3 p. 1): files → documents → chunks → vectors|embedding → koniec.
_BANDS: dict[str, tuple[float, float]] = {
    "files": (0.0, 0.1),
    "documents": (0.1, 0.2),
    "chunks": (0.2, 0.5),
    "vectors": (0.5, 0.95),
    "embedding": (0.5, 0.95),
}
_LABELS: dict[str, str] = {
    "files": "Pliki",
    "documents": "Dokumenty",
    "chunks": "Chunki",
    "vectors": "Wektory",
    "embedding": "Embedding",
    "finalize": "Finalizacja",
}
# Komunikaty dla przypadków ``IntegrityError`` (nazwa zajęta w międzyczasie / niespójna paczka).
_INTEGRITY: dict[str, str] = {
    "name_conflict": "Nazwa datasetu jest już zajęta",
    "invalid_archive": "Paczka jest niespójna (dane niezgodne ze schematem)",
}
# Dokumenty spoza paczki „zakończone" → „nieuruchomiony" (K19 §2); brak funkcji repo na run='0'.
_UNSTART_SQL = text(
    "UPDATE documents SET run = '0', progress = 0, progress_msg = '',"
    " update_time = :now, update_date = :now_date WHERE id IN :ids"
).bindparams(bindparam("ids", expanding=True))


class _ImportFailure(PermanentError):
    """Porażka trwała importu z kodem dla ``payload.error_code`` i ``WdTask.error.code``."""

    def __init__(self, message: str, *, error_code: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class _TaskProgress:
    """``ImportProgress`` (CONTRACT §2) na ``TaskContext``: payload + heartbeat z postępem."""

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


async def import_dataset(task: TaskRow, ctx: TaskContext) -> None:
    """Importuje paczkę do datasetu z payloadu (CONTRACT §3); wyjątki rozstrzyga kolejka."""
    container = ctx.container
    actor_id, import_id, name, dataset_id, reembed, embedding_model = _payload(task)
    path = _package_path(container, import_id)
    progress = _TaskProgress(ctx)
    await remove_partial_import(container, dataset_id=dataset_id)
    try:
        pkg = await _revalidate(container, path)
        plan = await _plan(
            container,
            pkg=pkg,
            actor_id=actor_id,
            name=name,
            embedding_model=embedding_model,
            dataset_id=dataset_id,
            reembed=reembed,
            task_public_id=task.id,
        )
        doc_ids = await create_dataset_with_documents(
            container, pkg=pkg, plan=plan, progress=progress
        )
        chunk_ids = await write_chunks(
            container,
            pkg=pkg,
            plan=plan,
            doc_ids=doc_ids,
            progress=progress,
            with_vectors=not reembed,
        )
        if reembed:
            await embed_chunks(
                container, plan=plan, chunk_ids=list(chunk_ids.values()), progress=progress
            )
        await _finalize(ctx, pkg=pkg, plan=plan, doc_ids=doc_ids, progress=progress)
    except TaskCancelled:
        await _abort(ctx, dataset_id, import_id, "import_cancelled", "Import został zatrzymany")
        raise
    except _ImportFailure as exc:
        await _abort(ctx, dataset_id, import_id, exc.error_code, str(exc))
        raise
    except PermanentError as exc:
        await _abort(ctx, dataset_id, import_id, "import_failed", str(exc))
        raise
    except IntegrityError as exc:
        code = "name_conflict" if _is_name_conflict(exc) else "invalid_archive"
        await _abort(ctx, dataset_id, import_id, code, _INTEGRITY[code])
        raise _ImportFailure(_INTEGRITY[code], error_code=code) from exc
    await asyncio.to_thread(_remove_file, path)


def _payload(task: TaskRow) -> tuple[str, str, str, str, bool, str | None]:
    """Odczyt payloadu: ``(actor_id, import_id, name, dataset_id, reembed, embedding_model)``.

    Brak któregokolwiek klucza wymaganego to porażka trwała ``import_failed`` (nie ``KeyError``,
    który kolejka zaklasyfikowałaby jako przejściowy i ponawiała); ``embedding_model`` jest
    opcjonalny (``None`` = model paczki).
    """
    payload = task.payload
    try:
        actor_id = str(payload["actor_id"])
        import_id = str(payload["import_id"])
        name = str(payload["name"])
        dataset_id = str(payload["dataset_id"])
        reembed = bool(payload["reembed"])
    except KeyError as exc:
        message = f"Zadanie importu bez pola {exc.args[0]}"
        raise _ImportFailure(message, error_code="import_failed") from exc
    model = payload.get("embedding_model")
    return (
        actor_id,
        import_id,
        name,
        dataset_id,
        reembed,
        str(model) if model is not None else None,
    )


async def _revalidate(container: Container, path: Path) -> ValidatedPackage:
    """Ponownie waliduje paczkę (defence in depth); kod porażki to kod pierwszego błędu."""
    settings = container.settings
    outcome = await asyncio.to_thread(
        validate_package,
        path,
        max_bytes=settings.export_max_bytes,
        max_ratio=settings.max_archive_ratio,
    )
    if isinstance(outcome, ValidatedPackage):
        return outcome
    first = outcome[0]
    raise _ImportFailure(first.message, error_code=first.code)


async def _plan(  # noqa: PLR0913 — pola planu z payloadu i manifestu paczki
    container: Container,
    *,
    pkg: ValidatedPackage,
    actor_id: str,
    name: str,
    embedding_model: str | None,
    dataset_id: str,
    reembed: bool,
    task_public_id: str,
) -> ImportPlan:
    """Plan importu: model docelowy z rejestru (albo paczki) i wymiar (CONTRACT §3 p. 2)."""
    requested = embedding_model or pkg.manifest.embedding.model_name
    registry = _registry(container)
    try:
        ref = await registry.resolve(requested, "embedding")
    except NotFound as exc:
        raise _ImportFailure(
            f"Model embeddingu niedostępny: {requested}", error_code="import_failed"
        ) from exc
    dimension = (
        await _target_dimension(container, ref) if reembed else pkg.manifest.embedding.dimension
    )
    return ImportPlan(
        dataset_id=dataset_id,
        actor_id=actor_id,
        name=name,
        embedding_model=ref.name,
        embedding_dim=dimension,
        reembed=reembed,
        task_public_id=task_public_id,
    )


async def _target_dimension(container: Container, ref: ModelRef) -> int:
    """Wymiar modelu docelowego: zapisany w rejestrze albo zmierzony sondą embeddingu."""
    if ref.dimension is not None:
        return int(ref.dimension)
    vector = (await _llm(container).embed(ref, [EMBEDDING_PROBE_TEXT]))[0]
    dimension = len(vector)
    if ref.id is not None:
        await _registry(container).set_dimension(ref.id, dimension)
    return dimension


async def _finalize(
    ctx: TaskContext,
    *,
    pkg: ValidatedPackage,
    plan: ImportPlan,
    doc_ids: Mapping[str, str],
    progress: _TaskProgress,
) -> None:
    """Statusy dokumentów (DONE/„nieuruchomiony"), recount, ``payload.result`` i audyt."""
    container = ctx.container
    reader = PackageReader(pkg)
    done_ids = [doc_ids[line.ref] for line in reader.documents() if line.run == DONE_RUN]
    all_ids = list(doc_ids.values())
    done_set = set(done_ids)
    other_ids = [doc_id for doc_id in all_ids if doc_id not in done_set]
    now = container.clock.now_ms()
    async with transaction(_sessionmaker(container)) as session:
        for doc_id in done_ids:
            await documents_repo.finish_done(session, doc_id, duration_s=0.0, now_ms=now)
        if other_ids:
            # Dokumenty spoza paczki „zakończone" → „nieuruchomiony" (K19 §2).
            await session.execute(
                _UNSTART_SQL, {"ids": other_ids, "now": now, "now_date": from_ms(now)}
            )
        for doc_id in all_ids:
            await chunks_repo.recount_document(session, doc_id, now_ms=now)
        await datasets_repo.recount(session, plan.dataset_id, now_ms=now)
        record = await datasets_repo.get_record(session, plan.dataset_id)
        await patch_payload(
            session,
            public_id=ctx.task.id,
            patch={
                "result": {
                    "dataset_id": plan.dataset_id,
                    "dataset_name": plan.name,
                    "documents": record.document_count if record is not None else len(all_ids),
                    "chunks": record.chunk_count if record is not None else 0,
                    "reembedded": plan.reembed,
                }
            },
            now_ms=now,
        )
    await progress.stage("finalize", 1, 1)
    documents = record.document_count if record is not None else len(all_ids)
    chunks = record.chunk_count if record is not None else 0
    await _audit(ctx, plan=plan, pkg=pkg, documents=documents, chunks=chunks)


async def _abort(
    ctx: TaskContext, dataset_id: str, import_id: str, code: str, message: str
) -> None:
    """Sprzątanie po Stopie/porażce: usuwa częściowy import i zamyka sesję jako ``invalid``."""
    container = ctx.container
    await remove_partial_import(container, dataset_id=dataset_id)
    now = container.clock.now_ms()
    async with transaction(_sessionmaker(container)) as session:
        await imports_repo.set_state(
            session,
            import_id=import_id,
            state="invalid",
            errors=[{"code": code, "message": message}],
            now_ms=now,
        )
        await patch_payload(session, public_id=ctx.task.id, patch={"error_code": code}, now_ms=now)


async def _audit(
    ctx: TaskContext, *, plan: ImportPlan, pkg: ValidatedPackage, documents: int, chunks: int
) -> None:
    """Wpis audytu ``dataset_imported`` (K19 §3 Uprawnienia) po udanym imporcie."""
    audit = ctx.container.audit
    if audit is None:
        raise RuntimeError("container not started")
    await audit.record(
        actor_label=await _actor_label(ctx.container, plan.actor_id),
        action="dataset_imported",
        target_type="dataset",
        target_id=plan.dataset_id,
        details={
            "dataset_id": plan.dataset_id,
            "task_id": plan.task_public_id,
            "source_instance_id": pkg.manifest.source_instance_id,
            "reembedded": plan.reembed,
            "documents": documents,
            "chunks": chunks,
        },
        actor_id=plan.actor_id,
    )


async def _actor_label(container: Container, actor_id: str) -> str:
    """Etykieta aktora do audytu: e-mail użytkownika, a gdy brak wiersza — jego id."""
    async with transaction(_sessionmaker(container)) as session:
        row = await users_repo.get_by_id(session, actor_id)
    return row.email if row is not None else actor_id


def _is_name_conflict(exc: IntegrityError) -> bool:
    """Czy ``IntegrityError`` pochodzi z unikalnej nazwy datasetu w tenancie aktora."""
    return NAME_CONFLICT_CONSTRAINT in str(exc)


def _package_path(container: Container, import_id: str) -> Path:
    """Ścieżka paczki: ``<storage_root>/imports/<import_id>.wdkb.zip`` (CONTRACT §4)."""
    return Path(container.settings.storage_root) / IMPORTS_DIR / f"{import_id}{IMPORT_SUFFIX}"


def _remove_file(path: Path) -> None:
    """Usuwa plik paczki po sukcesie; brak pliku to nie błąd (sync, w wątku — ASYNC240)."""
    path.unlink(missing_ok=True)


def _registry(container: Container) -> ModelRegistry:
    """Rejestr modeli z kontenera; brak (kontener nie wystartował) → ``RuntimeError`` (C4)."""
    registry = container.models
    if registry is None:
        raise RuntimeError("container not started")
    return registry


def _llm(container: Container) -> LLMGateway:
    """Bramka LLM z kontenera; brak (kontener nie wystartował) → ``RuntimeError`` (C4)."""
    llm = container.llm
    if llm is None:
        raise RuntimeError("container not started")
    return llm


def _sessionmaker(container: Container) -> async_sessionmaker[AsyncSession]:
    """Fabryka sesji z kontenera; brak (kontener nie wystartował) → ``RuntimeError`` (C4)."""
    sessionmaker = container.sessionmaker
    if sessionmaker is None:
        raise RuntimeError("container not started")
    return sessionmaker
