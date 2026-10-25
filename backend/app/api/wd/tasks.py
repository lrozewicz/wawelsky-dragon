"""Trasy zadań WD ``/api/wd/v1/tasks/{task_id}`` (K19 §3 trasy 3-4, CONTRACT E7-1f §7).

``GET`` oddaje stan zadania eksportu/importu, ``POST .../stop`` prosi o jego zatrzymanie.
Aktorem jest zwykły zalogowany użytkownik (sesja cookie albo klucz API) — nie administrator:
dostęp rozstrzyga polityka ``app.domain.policy``, a każde odrzucenie to **404** ``not_found``
(nie zdradzamy istnienia cudzego zadania, K19 §Uprawnienia). Zadania innych typów niż
``export_dataset``/``import_dataset`` też są tu nieobecne (404).

Widok zadania pochodzi z portu kolejki (``app.worker.queue``) — warstwa API nie dotyka
``app.db`` (kontrakt lint-imports ``api-no-db``), a właścicielem tabeli ``tasks`` jest kolejka.
"""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import APIRouter, Path, Request, status
from pydantic import BaseModel, Field

from app.api.auth.principal import PrincipalDep, container_of
from app.api.wd.common import Envelope, wd_responses
from app.api.wd.kb_schemas import (
    ExportResult,
    ImportResult,
    TaskError,
    WdTask,
    WdTaskKind,
    WdTaskStage,
    WdTaskStatus,
)
from app.core.errors import NotFound
from app.domain.policy import Action, Principal, ResourceRef, can
from app.worker.queue import DbTaskQueue, TaskQueue, TaskSnapshot

router = APIRouter(prefix="/api/wd/v1", tags=["tasks"])

TaskIdPath = Annotated[str, Path(min_length=1, description="Identyfikator zadania")]

# Typ zadania kolejki → ``kind`` koperty ``WdTask`` (K19 §3).
_KINDS: dict[str, WdTaskKind] = {"export_dataset": "export", "import_dataset": "import"}
# Status wewnętrzny → status koperty: ``dead`` (trwała porażka) jest dla użytkownika ``failed``.
_STATUSES: dict[str, str] = {"dead": "failed"}
_STAGES: tuple[str, ...] = ("files", "documents", "chunks", "vectors", "embedding", "finalize")
# Statusy, w których zadanie da się jeszcze zatrzymać (K19 §3 trasa 4 → ``stopped: true``).
_STOPPABLE: tuple[str, ...] = ("queued", "running")
_DEFAULT_ERROR_CODE = "task_failed"
_NOT_FOUND_MESSAGE = "Task not found"


class TaskStopResult(BaseModel):
    """Potwierdzenie ``POST /tasks/{id}/stop`` (K19 §3 trasa 4).

    Nazwa niekolidująca z ``StopResult`` tras ragflow (``documents/stop``), żeby komponent
    OpenAPI nie musiał być rozróżniany prefiksem modułu.
    """

    stopped: bool = Field(
        description="True, gdy zadanie było queued/running i przyjęło prośbę o zatrzymanie"
    )


def _queue(request: Request) -> DbTaskQueue:
    """Kolejka zadań z kontenera żądania (kontrakt C7) — port zamiast sięgania do ``app.db``."""
    container = container_of(request)
    sessionmaker = container.sessionmaker
    if sessionmaker is None:  # pragma: no cover — kontener API startuje w lifespanie
        raise RuntimeError("container not started")
    return DbTaskQueue(sessionmaker, container.clock, container.id_gen)


def _visible(principal: Principal, snapshot: TaskSnapshot) -> bool:
    """Inicjator zadania (``payload.actor_id``) albo superuser (K19 §Uprawnienia 3/4).

    Polityka nie zna rodzaju ``task``; ``dataset`` z właścicielem = ``actor_id`` daje w tabeli
    07 §7.1 dokładnie „właściciel albo superuser” (``permission`` nieustawione, więc członek
    zespołu nie przechodzi).
    """
    actor_id = snapshot.payload.get("actor_id")
    owner = actor_id if isinstance(actor_id, str) else None
    return can(principal, Action.READ, ResourceRef(kind="dataset", owner_id=owner))


def _stage(payload: dict[str, Any]) -> WdTaskStage | None:
    """Etap pracy z ``payload["stage"]`` (dopisują go E7-1a/E7-1b); nieznany → ``None``."""
    value = payload.get("stage")
    return cast("WdTaskStage", value) if value in _STAGES else None


def _counter(payload: dict[str, Any], key: str) -> int:
    """Licznik etapu z ``payload[key]`` (E7-1a/E7-1b); brak albo nie-liczba → 0."""
    value = payload.get(key)
    return int(value) if isinstance(value, int) else 0


def _error(snapshot: TaskSnapshot) -> TaskError | None:
    """Błąd zadania: kolumna ``error`` (``Typ: tekst``) plus slug z ``payload["error_code"]``."""
    if not snapshot.error:
        return None
    _, separator, text = snapshot.error.partition(": ")
    code = snapshot.payload.get("error_code")
    return TaskError(
        code=code if isinstance(code, str) else _DEFAULT_ERROR_CODE,
        message=text if separator else snapshot.error,
    )


def _result(snapshot: TaskSnapshot, kind: WdTaskKind) -> ExportResult | ImportResult | None:
    """Wynik zadania z ``payload["result"]`` — wyłącznie dla ``done`` (K19 §3)."""
    raw = snapshot.payload.get("result")
    if snapshot.status != "done" or not isinstance(raw, dict):
        return None
    model = ExportResult if kind == "export" else ImportResult
    return model.model_validate(raw)


def _wd_task(snapshot: TaskSnapshot) -> WdTask:
    """Wiersz zadania → koperta ``WdTask`` (K19 §3)."""
    kind = _KINDS[snapshot.task_type]
    return WdTask(
        task_id=snapshot.id,
        kind=kind,
        dataset_id=snapshot.dataset_id,
        status=cast(WdTaskStatus, _STATUSES.get(snapshot.status, snapshot.status)),
        stage=_stage(snapshot.payload),
        done=_counter(snapshot.payload, "done"),
        total=_counter(snapshot.payload, "total"),
        progress=snapshot.progress,
        message=snapshot.progress_msg,
        error=_error(snapshot),
        created_at=snapshot.created_at,
        finished_at=snapshot.finished_at,
        result=_result(snapshot, kind),
    )


async def _task(queue: TaskQueue, task_id: str, principal: Principal) -> TaskSnapshot:
    """Zadanie widoczne dla aktora; brak zadania, obcy typ albo obcy aktor → 404 (K19 §3)."""
    snapshot = await queue.snapshot(task_id)
    if snapshot is None or snapshot.task_type not in _KINDS or not _visible(principal, snapshot):
        raise NotFound(_NOT_FOUND_MESSAGE)
    return snapshot


@router.get(
    "/tasks/{task_id}",
    operation_id="wd_task_get",
    summary="Stan zadania eksportu/importu",
    status_code=status.HTTP_200_OK,
    response_model=Envelope[WdTask],
    responses=wd_responses(400, 401, 403, 404),
)
async def wd_task_get(
    request: Request, task_id: TaskIdPath, principal: PrincipalDep
) -> Envelope[WdTask]:
    """Stan zadania dla jego inicjatora albo superusera (K19 §3 trasa 3)."""
    snapshot = await _task(_queue(request), task_id, principal)
    return Envelope[WdTask](data=_wd_task(snapshot))


@router.post(
    "/tasks/{task_id}/stop",
    operation_id="wd_task_stop",
    summary="Zatrzymuje zadanie eksportu/importu",
    status_code=status.HTTP_200_OK,
    response_model=Envelope[TaskStopResult],
    responses=wd_responses(400, 401, 403, 404),
)
async def wd_task_stop(
    request: Request, task_id: TaskIdPath, principal: PrincipalDep
) -> Envelope[TaskStopResult]:
    """Prosi o zatrzymanie zadania; ``stopped: false`` dla stanu terminalnego (K19 §3 trasa 4).

    Zapisujemy wyłącznie ``cancel_requested`` — zadanie ``queued`` zamyka claim jako
    ``cancelled``, a ``running`` kończy handler po ``ctx.check_cancel()`` (kontrakt C5).
    """
    queue = _queue(request)
    snapshot = await _task(queue, task_id, principal)
    stopped = snapshot.status in _STOPPABLE and await queue.request_cancel_task(task_id)
    return Envelope[TaskStopResult](data=TaskStopResult(stopped=stopped))
