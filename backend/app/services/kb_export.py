"""Logika tras eksportu paczki ``.wdkb.zip`` (K19 §3 trasy 1, 2 i 5; CONTRACT E7-1a §4).

``KbExportService`` obsługuje podgląd (``preview``), zlecenie zadania (``start``) i pobranie
gotowej paczki podpisanym linkiem (``download``). Uprawnienia rozstrzyga wyłącznie
``app.domain.policy``: trasy 1-2 wymagają właściciela datasetu albo superusera (członek zespołu
z ``permission=team`` ma READ, ale nie eksportuje — K19 §Uprawnienia). Trasa pobrania nie zna
aktora: autoryzuje ją podpis HMAC z ``app.services.kb_export_link``.

Warstwy: usługa nie importuje ``app.api`` ani nie składa kopert — oddaje ``dict`` o kształtach
K19 (``ExportPreview``, ``TaskRef``), które trasa waliduje modelami z ``app.api.wd.kb_schemas``.
Zadanie ``export_dataset`` tylko zlecamy (``queued``); wykonuje je handler E7-1a-T2.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import (
    ExportExpired,
    ExportInProgress,
    Forbidden,
    InvalidSignature,
    NotFound,
    PackageTooLarge,
)
from app.db.repositories import datasets as datasets_repo
from app.db.repositories.datasets import DatasetRecord
from app.db.uow import transaction
from app.domain.policy import Action, Principal, ResourceRef, can
from app.services.kb_export_link import export_package_path, verify_export
from app.services.kb_package.format import VECTOR_PART_ROWS
from app.worker.queue import DbTaskQueue, NewTask, TaskSnapshot, TaskType

if TYPE_CHECKING:
    from app.core.container import Container

__all__ = ["KbExportService", "estimate_package_bytes"]

# Typ zadania kolejki, które zleca ``start`` (K19 §3, CONTRACT §3).
_EXPORT_TASK: TaskType = "export_dataset"
# Statusy, w których zadanie eksportu tego datasetu blokuje kolejny ``start`` (K19 §3, trasa 2).
_STATUSES_IN_PROGRESS: tuple[str, ...] = ("queued", "running")

# Współczynnik kompresji DEFLATE wpisów tekstowych paczki: bajty paczki na bajt treści chunków
# (``documents.jsonl`` + ``chunks.jsonl``; K19 §2). Zmierzony na realnej prozie PL (E7-H1/T5,
# ``docs/perf/E7-H1.md``): ``chunks.jsonl`` 2 049 B / 6 424 B treści = 0,319 dla 12 chunków,
# 0,235 dla 2 000+ chunków — klucze JSON powtarzają się, więc większa paczka kompresuje lepiej.
# Stała przyjmuje wartość asymptotyczną (duże bazy), a małe (gdzie tekst to margines plików
# i wektorów) nadal mieszczą się w tolerancji ±25 %.
TEXT_DEFLATE_RATIO = 0.25
# Nagłówek NPY 1.0 na część wektorów (``format.py``: 10 B prefiksu + nagłówek ASCII do 64 B).
VECTOR_HEADER_BYTES = 128

# Komunikaty kopert WD (K19 §3 tabela kodów) — bez szczegółów, które mogłyby coś ujawnić.
_MSG_NOT_FOUND = "Dataset not found"
_MSG_FORBIDDEN = "Only the dataset owner can export it"
_MSG_INVALID_SIGNATURE = "Invalid download signature"
_MSG_EXPIRED = "Export link expired"
_MSG_TOO_LARGE = "Export estimate exceeds the package limit"
_MSG_IN_PROGRESS = "Export already in progress"

# Agregaty podglądu (CONTRACT §4): liczby z DB, chunki wyłącznie ``committed=1``.
_ESTIMATE_SQL = text(
    "SELECT"
    " (SELECT COUNT(*) FROM documents WHERE dataset_id = :ds) AS documents,"
    " (SELECT COUNT(*) FROM chunks WHERE dataset_id = :ds AND committed = 1) AS chunks,"
    " COALESCE((SELECT SUM(size) FROM documents WHERE dataset_id = :ds), 0) AS file_bytes,"
    " COALESCE((SELECT SUM(LENGTH(content) + COALESCE(LENGTH(content_llm), 0)) FROM chunks"
    " WHERE dataset_id = :ds AND committed = 1), 0) AS content_bytes"
)

# Istniejące zadanie eksportu datasetu (K19 §3, trasa 2 → 409 ``export_in_progress``).
_ACTIVE_TASK_SQL = text(
    "SELECT public_id FROM tasks"
    " WHERE dataset_id = :ds AND task_type = :task_type AND status IN ('queued', 'running')"
    " ORDER BY id LIMIT 1"
)


@dataclass(frozen=True)
class _Estimate:
    """Agregaty podglądu liczone wprost z DB (CONTRACT §4)."""

    documents: int
    chunks: int
    # Σ documents.size (pliki źródłowe ~1:1, zwykle nie kompresują się).
    file_bytes: int
    # Σ LENGTH(content)+COALESCE(LENGTH(content_llm),0) chunktów ``committed=1``.
    content_bytes: int


def _vector_bytes(chunks: int, dimension: int) -> int:
    """Bajty wektorów: float32 little-endian bez kompresji + nagłówki NPY części (K19 §2)."""
    parts = -(-chunks // VECTOR_PART_ROWS) if chunks else 0
    return chunks * dimension * 4 + parts * VECTOR_HEADER_BYTES


def estimate_package_bytes(
    *,
    chunks: int,
    file_bytes: int,
    content_bytes: int,
    dimension: int,
    include_vectors: bool,
) -> int:
    """Szacunek rozmiaru paczki ``.wdkb.zip`` (K19 §3 trasa 1, E7-H1/T5).

    Pliki źródłowe wg rozmiaru (deflate zwykle ich nie ściska), tekst (``documents.jsonl`` +
    ``chunks.jsonl``) po współczynniku DEFLATE (:data:`TEXT_DEFLATE_RATIO`), wektory NPY
    float32 bez kompresji (``chunks·dimension·4`` + nagłówki części).
    """
    total = file_bytes + round(TEXT_DEFLATE_RATIO * content_bytes)
    if include_vectors:
        total += _vector_bytes(chunks, dimension)
    return total


def _ref(record: DatasetRecord) -> ResourceRef:
    """ResourceRef datasetu dla polityki (wzorzec ``app.services.datasets._ref``)."""
    return ResourceRef(
        kind="dataset", owner_id=record.tenant_id, permission=record.permission, id=record.id
    )


class KbExportService:
    """Podgląd, zlecenie i pobranie eksportu bazy wiedzy (CONTRACT E7-1a §4)."""

    def __init__(self, container: Container) -> None:
        self._container = container

    async def preview(self, principal: Principal, dataset_id: str) -> dict[str, Any]:
        """Szacunek eksportu datasetu (K19 §3, trasa 1) — kształt ``ExportPreview``."""
        async with transaction(self._sessionmaker()) as session:
            record = self._authorize(principal, await datasets_repo.get_record(session, dataset_id))
            estimate = await self._estimate(session, dataset_id)
        return self._preview_data(record, estimate)

    async def start(
        self, principal: Principal, dataset_id: str, *, include_vectors: bool
    ) -> dict[str, Any]:
        """Zleca zadanie ``export_dataset`` (K19 §3, trasa 2) — kształt ``TaskRef``.

        X-blokada wiersza datasetu (``datasets_repo.lock``) trzymana przez całą transakcję
        serializuje wyścig dwóch równoległych ``POST`` (CONTRACT §4, DEC-324): drugi start
        po zwolnieniu blokady widzi już zadanie pierwszego i zwraca 409.
        """
        async with transaction(self._sessionmaker()) as session:
            await datasets_repo.lock(session, dataset_id)
            record = self._authorize(principal, await datasets_repo.get_record(session, dataset_id))
            existing = await self._active_task(session, dataset_id)
            if existing is not None:
                raise ExportInProgress(_MSG_IN_PROGRESS, details={"task_id": existing})
            estimate = await self._estimate(session, dataset_id)
            size = self._estimated_bytes(estimate, record, include_vectors=include_vectors)
            if size > self._container.settings.export_max_bytes:
                raise PackageTooLarge(_MSG_TOO_LARGE)
            payload: dict[str, Any] = {
                "actor_id": principal.user_id,
                "include_vectors": include_vectors,
            }
            task_id = await self._queue().enqueue(
                NewTask(_EXPORT_TASK, payload, dataset_id=dataset_id, max_attempts=3)
            )
        return {"task_id": task_id, "status": "queued"}

    async def download(self, task_id: str, *, exp: int, sig: str) -> tuple[Path, str]:
        """Weryfikuje podpis linku i zwraca ``(ścieżka pliku, nazwa pliku)`` (K19 §3, trasa 5).

        Kolejność wg CONTRACT §4: najpierw podpis (zły/brak → 403 ``invalid_signature``, bez
        ujawniania czegokolwiek o zadaniu), potem wygaśnięcie i stan zadania/pliku (→ 410).
        """
        secret = self._container.settings.secret_key.get_secret_value()
        if not verify_export(secret, task_id, exp, sig):
            raise InvalidSignature(_MSG_INVALID_SIGNATURE)
        now_s = self._container.clock.now_ms() // 1000
        if exp < now_s:
            raise ExportExpired(_MSG_EXPIRED)
        snapshot = await self._queue().snapshot(task_id)
        file_name = self._download_file_name(snapshot)
        path = export_package_path(self._container.settings.storage_root, task_id)
        if not path.is_file():
            raise ExportExpired(_MSG_EXPIRED)
        return path, file_name

    # --- wewnętrzne ---------------------------------------------------------------------------

    def _sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        """Fabryka sesji z kontenera (wzorzec ``app.services.datasets``)."""
        return cast("async_sessionmaker[AsyncSession]", self._container.sessionmaker)

    def _queue(self) -> DbTaskQueue:
        """Kolejka zadań na usługach kontenera (ta sama droga co ``app.api.wd.tasks``)."""
        return DbTaskQueue(self._sessionmaker(), self._container.clock, self._container.id_gen)

    def _authorize(self, principal: Principal, record: DatasetRecord | None) -> DatasetRecord:
        """Dostęp do tras 1-2 (K19 §Uprawnienia): brak albo brak READ → 404, nie-właściciel → 403.

        READ daje właścicielowi i członkowi zespołu (``permission=team``); eksport wymaga więc
        dodatkowo akcji właścicielskiej (``DELETE``), którą przechodzi wyłącznie właściciel albo
        superuser — członek zespołu kończy na 403 ``forbidden``.
        """
        if record is None or not can(principal, Action.READ, _ref(record)):
            raise NotFound(_MSG_NOT_FOUND)
        if not can(principal, Action.DELETE, _ref(record)):
            raise Forbidden(_MSG_FORBIDDEN)
        return record

    def _preview_data(self, record: DatasetRecord, estimate: _Estimate) -> dict[str, Any]:
        """``ExportPreview`` (K19 §3): liczby z DB, wymiar z wiersza datasetu, limit z env."""
        return {
            "dataset_id": record.id,
            "name": record.name,
            "documents": estimate.documents,
            "chunks": estimate.chunks,
            "estimated_bytes": self._estimated_bytes(estimate, record, include_vectors=False),
            "estimated_bytes_with_vectors": self._estimated_bytes(
                estimate, record, include_vectors=True
            ),
            "embedding": {
                "model_name": record.embedding_model,
                "dimension": record.embedding_dim,
            },
            "max_bytes": self._container.settings.export_max_bytes,
        }

    async def _estimate(self, session: AsyncSession, dataset_id: str) -> _Estimate:
        """Agregaty podglądu z DB (CONTRACT §4); szacunek liczy :func:`estimate_package_bytes`."""
        row = (await session.execute(_ESTIMATE_SQL, {"ds": dataset_id})).one()
        return _Estimate(
            documents=int(row[0]),
            chunks=int(row[1]),
            file_bytes=int(row[2]),
            content_bytes=int(row[3]),
        )

    @staticmethod
    def _estimated_bytes(
        estimate: _Estimate, record: DatasetRecord, *, include_vectors: bool
    ) -> int:
        """Szacunek rozmiaru paczki datasetu (CONTRACT §4, model E7-H1/T5)."""
        return estimate_package_bytes(
            chunks=estimate.chunks,
            file_bytes=estimate.file_bytes,
            content_bytes=estimate.content_bytes,
            dimension=record.embedding_dim,
            include_vectors=include_vectors,
        )

    async def _active_task(self, session: AsyncSession, dataset_id: str) -> str | None:
        """Id zadania eksportu w ``queued``/``running`` dla datasetu albo ``None`` (K19 §3)."""
        found = (
            await session.execute(_ACTIVE_TASK_SQL, {"ds": dataset_id, "task_type": _EXPORT_TASK})
        ).first()
        return str(found[0]) if found is not None else None

    @staticmethod
    def _download_file_name(snapshot: TaskSnapshot | None) -> str:
        """Nazwa pliku z ``payload.result`` ukończonego eksportu; inaczej 410 ``export_expired``."""
        if snapshot is None or snapshot.task_type != _EXPORT_TASK or snapshot.status != "done":
            raise ExportExpired(_MSG_EXPIRED)
        result = snapshot.payload.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("file_name"), str):
            raise ExportExpired(_MSG_EXPIRED)
        file_name: str = result["file_name"]
        return file_name
