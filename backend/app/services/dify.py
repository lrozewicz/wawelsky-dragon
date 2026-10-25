"""Usługa Dify external knowledge API (brief OD p. 1; port ``dify_retrieval_api.py`` v0.27.2).

Trasa dostaje ``DifyQuery`` po normalizacji (``app/api/ragflow/normalize/dify.py``),
a zwraca ``RetrievalResult`` z istniejącej usługi retrievalu (M6) — sygnatur tej usługi
nie zmieniamy (kontrakt E2-1 C4); dokładamy tylko własną kontrolę bazy wiedzy, bo Dify
odróżnia brak bazy (404 ``Knowledgebase not found!``) od bazy cudzej (kod 109 ``no authorization``),
czego ``RetrievalService.retrieve`` nie robi (tam oba to 102 ``You don't own the dataset …``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AuthenticationFailed, ResourceNotFound
from app.db.repositories import datasets as datasets_repo
from app.db.uow import transaction
from app.domain.policy import Action, Principal, ResourceRef, can
from app.domain.retrieval.metadata import MetadataCondition
from app.domain.retrieval.types import RetrievalResult
from app.services.retrieval import RetrievalQuery

if TYPE_CHECKING:
    from app.core.container import Container

# Wartości dosłownie z upstreamu: ``page_size=top``, waga 0.3, próg z ``retrieval_setting``.
VECTOR_SIMILARITY_WEIGHT = 0.3
MSG_KNOWLEDGEBASE_NOT_FOUND = "Knowledgebase not found!"
MSG_NO_AUTHORIZATION = "no authorization"


@dataclass(frozen=True)
class DifyQuery:
    """Żądanie ``/dify/retrieval`` (POST z ciała, GET z parametrów — upstream :30-91)."""

    knowledge_id: str
    query: str
    top_k: int
    score_threshold: float
    metadata_condition: MetadataCondition | None = None


class DifyService:
    """Retrieval Dify: baza wiedzy + polityka READ, potem ``RetrievalService.retrieve_trusted``."""

    def __init__(self, container: Container) -> None:
        """Zapamiętuje kontener; bez I/O — usługa może powstać przed ``start()``."""
        self._container = container

    async def retrieve(self, principal: Principal, q: DifyQuery) -> RetrievalResult:
        """Rekordy dla pytania; brak bazy → 404, baza cudza → 109 (upstream :246-258)."""
        await self._authorize(principal, q.knowledge_id)
        return await self._container.retrieval.retrieve_trusted(
            RetrievalQuery(
                question=q.query,
                dataset_ids=(q.knowledge_id,),
                page=1,
                page_size=q.top_k,
                similarity_threshold=q.score_threshold,
                vector_similarity_weight=VECTOR_SIMILARITY_WEIGHT,
                top_k=q.top_k,
                metadata_condition=q.metadata_condition,
                aggs=False,
            )
        )

    async def _authorize(self, principal: Principal, knowledge_id: str) -> None:
        """Istnienie i dostęp do bazy wiedzy: 404 dla braku, 109 dla cudzej (upstream :246-258)."""
        async with transaction(self._sessionmaker()) as session:
            record = await datasets_repo.get_record(session, knowledge_id)
        if record is None:
            raise ResourceNotFound(MSG_KNOWLEDGEBASE_NOT_FOUND)
        if not can(
            principal,
            Action.READ,
            ResourceRef(
                kind="dataset",
                owner_id=record.tenant_id,
                permission=record.permission,
                id=record.id,
            ),
        ):
            raise AuthenticationFailed(MSG_NO_AUTHORIZATION)

    def _sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        """Fabryka sesji z kontenera; brak startu → RuntimeError (wzorzec ``services/chat.py``)."""
        sessionmaker: async_sessionmaker[AsyncSession] | None = self._container.sessionmaker
        if sessionmaker is None:
            raise RuntimeError("container not started")
        return sessionmaker
