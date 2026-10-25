"""Usługa użycia datasetu przed usunięciem (K20 §4) — mały serwis dla trasy WD.

Dostęp jak ``DatasetService.delete``: brak datasetu albo brak odczytu → 404 ``not_found``
(bez ujawniania istnienia), widoczny bez prawa usunięcia (członek zespołu) → 403
``forbidden``. Zwraca ``dict`` o kształcie ``DatasetUsage`` — kopertę składa warstwa API.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import Forbidden, NotFound
from app.db.repositories import chat_datasets as chat_datasets_repo
from app.db.repositories import datasets as datasets_repo
from app.db.repositories import searches as searches_repo
from app.db.repositories.datasets import DatasetRecord
from app.db.uow import transaction
from app.domain.policy import Action, Principal, ResourceRef, can, visibility_filter

if TYPE_CHECKING:
    from app.core.container import Container

# Najwyżej 50 pozycji na listę użycia (K20 §4); nadwyżka tylko sygnalizuje ``truncated``.
USAGE_LIST_LIMIT = 50

# Komunikaty po polsku — trasa WD (K20 §5 p. 2); rozstrzyga stabilny ``code``.
MSG_USAGE_NOT_FOUND = "Nie znaleziono bazy wiedzy."
MSG_USAGE_FORBIDDEN = "Tylko właściciel bazy wiedzy może sprawdzić jej użycie."


def _ref(record: DatasetRecord) -> ResourceRef:
    """ResourceRef datasetu dla polityki (wzorzec ``app.services.datasets._ref``)."""
    return ResourceRef(
        kind="dataset", owner_id=record.tenant_id, permission=record.permission, id=record.id
    )


class DatasetUsageService:
    """Powiązania datasetu (czaty, wyszukiwarki) widziane przed jego usunięciem (K20 §4)."""

    def __init__(self, container: Container) -> None:
        self._container = container

    async def usage(self, principal: Principal, dataset_id: str) -> dict[str, Any]:
        """Użycie datasetu; tylko odczyt, bez zmiany stanu (Q52).

        Widoczne powiązania z nazwami, sortowane po name potem id; niewidoczne tylko
        liczone (``hidden_*``); ``truncated`` gdy któraś lista miała > ``USAGE_LIST_LIMIT``.
        Zakres widoczności rozstrzyga ``visibility_filter`` (C3: decyzje w polityce).
        """
        async with transaction(self._sessionmaker()) as session:
            record = await datasets_repo.get_record(session, dataset_id)
            if record is None or not can(principal, Action.READ, _ref(record)):
                raise NotFound(MSG_USAGE_NOT_FOUND)
            if not can(principal, Action.DELETE, _ref(record)):
                raise Forbidden(MSG_USAGE_FORBIDDEN)
            chats, hidden_chats, chats_cut = await chat_datasets_repo.usage(
                session,
                dataset_id,
                visibility=visibility_filter(principal, "chat"),
                limit=USAGE_LIST_LIMIT,
            )
            searches, hidden_searches, searches_cut = await searches_repo.usage(
                session,
                dataset_id,
                visibility=visibility_filter(principal, "search"),
                limit=USAGE_LIST_LIMIT,
            )
        return {
            "chats": [{"id": item_id, "name": name} for item_id, name in chats],
            "searches": [{"id": item_id, "name": name} for item_id, name in searches],
            "hidden_chats": hidden_chats,
            "hidden_searches": hidden_searches,
            "truncated": chats_cut or searches_cut,
        }

    def _sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        """Fabryka sesji z kontenera (wzorzec ``app.services.datasets``)."""
        return cast("async_sessionmaker[AsyncSession]", self._container.sessionmaker)
