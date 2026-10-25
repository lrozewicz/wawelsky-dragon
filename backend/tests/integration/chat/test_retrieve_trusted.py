"""Testy retrieve_trusted na MariaDB + fake-llm (brief T3, kontrakt C10)."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.container import Container
from app.core.errors import PermissionDenied
from app.db.uow import transaction
from app.services.retrieval import RetrievalQuery
from tests.integration.ingest.conftest import seed_dataset
from tests.integration.retrieval.conftest import ingest_text, principal_for

pytestmark = [
    pytest.mark.db,
    pytest.mark.fakellm,
]

# Tekst o umowie najmu (wzorzec tests/integration/retrieval/test_service.py).
_UMOWA = (
    "Umowa najmu lokalu użytkowego w Krakowie. Wynajmujący oddaje najemcy lokal przy ulicy "
    "Grodeckiej 7. Najemca płaci czynsz dziesiątego dnia każdego miesiąca. Umowa najmu może "
    "zostać wypowiedziana z zachowaniem trzymiesięcznego okresu wypowiedzenia. Wypowiedzenie "
    "umowy najmu lokalu wymaga formy pisemnej. Po zakończeniu umowy najemca zwraca lokal."
) * 2

_QUESTION = "Jak wypowiedzieć umowę najmu lokalu?"


async def _set_permission(
    sm: async_sessionmaker[AsyncSession], dataset_id: str, permission: str
) -> None:
    """UPDATE datasets.permission w osobnej transakcji (jak tests/integration/retrieval)."""
    async with transaction(sm) as session:
        await session.execute(
            text("UPDATE datasets SET permission = :p WHERE id = :id"),
            {"id": dataset_id, "p": permission},
        )


async def test_retrieve_trusted_bypasses_read_permission(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """C10: dataset 'me' użytkownika A; B bez READ → PermissionDenied; trusted działa jak A."""
    ds = await seed_dataset(sm)
    await _set_permission(sm, ds.id, "me")
    await ingest_text(container, ds, "umowa.txt", _UMOWA)
    owner = principal_for(ds.tenant_id)
    stranger = principal_for(uuid.uuid4().hex)
    query = RetrievalQuery(question=_QUESTION, dataset_ids=(ds.id,), similarity_threshold=0.0)
    with pytest.raises(PermissionDenied):
        await container.retrieval.retrieve(stranger, query)
    trusted = await container.retrieval.retrieve_trusted(query)
    own = await container.retrieval.retrieve(owner, query)
    assert trusted.total >= 1
    assert [chunk.chunk_id for chunk in trusted.chunks] == [chunk.chunk_id for chunk in own.chunks]
