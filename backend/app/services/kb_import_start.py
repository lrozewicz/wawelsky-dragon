"""Logika trasy 9 ``start`` importu paczki ``.wdkb.zip`` (K19 §3, CONTRACT E7-1b §1/§3).

``start_import`` działa w transakcji otwartej przez ``KbImportService.start`` (``kb_import.py``)
z wierszem sesji zablokowanym ``SELECT … FOR UPDATE``: waliduje nazwę i model docelowy, liczy
``reembed``, zleca zadanie ``import_dataset`` (payload z CONTRACT §3) i zapisuje stan ``started``
z ``task_id`` (``set_state`` dostaje ``summary`` jawnie — inaczej je zeruje).

Warstwy: moduł NIE importuje ``app.api`` ani ``app.services.kb_import`` — ``KbImportService.start``
tylko deleguje tu, więc zależność jest jednokierunkowa (bez cyklu importów).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import (
    EmbeddingModelRequired,
    EmbeddingModelUnknown,
    ImportNotReady,
    NameConflict,
    NotFound,
    ValidationFailed,
)
from app.core.timeutil import from_ms
from app.db.repositories import dataset_imports as imports_repo
from app.db.repositories import datasets as datasets_repo
from app.services.kb_import_summary import MAX_NAME_LEN, _suggest_name, name_key
from app.worker.queue import DbTaskQueue, NewTask

if TYPE_CHECKING:
    from app.core.container import Container
    from app.llm.registry import ModelRegistry

__all__ = ["MAX_NAME_LEN", "start_import"]


def _queue(container: Container) -> DbTaskQueue:
    """Kolejka zadań na usługach kontenera (ta sama droga co ``kb_import._queue``)."""
    sessionmaker = cast("async_sessionmaker[AsyncSession]", container.sessionmaker)
    return DbTaskQueue(sessionmaker, container.clock, container.id_gen)


async def start_import(
    container: Container,
    session: AsyncSession,
    row: dict[str, Any],
    *,
    name: str,
    embedding_model: str | None,
) -> dict[str, Any]:
    """Przejście ``ready`` → ``started`` i zlecenie zadania ``import_dataset`` (K19 §3, trasa 9).

    ``row`` to wiersz sesji (``dataset_imports``) już zweryfikowany i zablokowany ``FOR UPDATE``;
    ``session`` to transakcja trzymająca blokadę przez ``enqueue`` i ``set_state``. Wyjątek
    (``enqueue``/``set_state``) przewraca całą transakcję, więc stan wraca do ``ready``.
    Zwraca ``dict`` ``{"task_id": str, "status": "queued"}`` — ``TaskRef`` buduje trasa.
    """
    if not 1 <= len(name) <= MAX_NAME_LEN:
        raise ValidationFailed("Nazwa datasetu musi mieć od 1 do 128 znaków")
    import_id = str(row["id"])
    state, summary = str(row["state"]), row["summary"]
    if state != "ready" or summary is None:
        raise ImportNotReady("Sesja nie jest gotowa do startu", details={"state": state})
    actor_id = str(row["user_id"])
    taken = await datasets_repo.names_taken(session, actor_id)
    if name_key(name) in taken:
        date = from_ms(container.clock.now_ms()).strftime("%Y-%m-%d")
        raise NameConflict(
            "Nazwa datasetu jest już zajęta",
            details={"suggested_name": _suggest_name(name, taken, date)},
        )
    requested = embedding_model or summary["target"]["default_model"]
    if not requested:
        raise EmbeddingModelRequired("Brak modelu docelowego embeddingu")
    registry = cast("ModelRegistry", container.models)
    try:
        ref = await registry.resolve(requested, "embedding")
    except NotFound as exc:
        raise EmbeddingModelUnknown(f"Model embeddingu niedostępny: {requested}") from exc
    embedding = summary["embedding"]
    reembed = not (
        ref.name == embedding["model_name"]
        and ref.dimension == embedding["dimension"]
        and bool(embedding["included"])
    )
    payload = {
        "actor_id": actor_id,
        "import_id": import_id,
        "name": name,
        "embedding_model": ref.name,
        "dataset_id": container.id_gen.new_id(),
        "reembed": reembed,
    }
    task_id = await _queue(container).enqueue(NewTask("import_dataset", payload, max_attempts=3))
    # ``summary`` jawnie — ``set_state`` zeruje je, gdy nie podane (CONTRACT §5).
    await imports_repo.set_state(
        session,
        import_id=import_id,
        state="started",
        errors=[],
        summary=summary,
        task_id=task_id,
        now_ms=container.clock.now_ms(),
    )
    return {"task_id": task_id, "status": "queued"}
