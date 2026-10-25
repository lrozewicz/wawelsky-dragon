"""Testy serwisu wyszukiwarek na prawdziwej MariaDB (brief T2a, CONTRACT E4-4a §D4).

Każdy wiersz tabeli „wejście → wyjście" z briefu ma osobny test; komunikaty błędów
porównywane dosłownie.
"""

import re
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.core.errors import PermissionDenied, ValidationFailed
from app.db.uow import transaction
from app.domain.search.config import default_config
from app.services.searches import SearchesService, SearchView
from tests.integration.chat.conftest import seed_user
from tests.integration.ingest.conftest import TIME, TIME_MS
from tests.integration.ingest.pipeline_helpers import make_container
from tests.integration.retrieval.conftest import principal_for

pytestmark = pytest.mark.db

NAME_LIMIT_MESSAGE = "Search name length is {length} which is large than 255."
OWN_SEARCHES = 2  # liczba wyszukiwarek Alice w teście listy


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener testowy (wzór tests/integration/api/test_chats_routes.py)."""
    instance = await make_container(migrated_db, tmp_path)
    yield instance
    await instance.aclose()


def _svc(container: Container) -> SearchesService:
    """Serwis na kontenerze testowym."""
    return SearchesService(container)


async def _seed_dataset(
    sm: async_sessionmaker[AsyncSession],
    tenant_id: str,
    *,
    name: str = "Korpus",
    permission: str = "me",
) -> str:
    """Wstawia dataset właściciela; zwraca id (FK datasets.tenant_id → users)."""
    dataset_id = uuid.uuid4().hex
    async with transaction(sm) as session:
        await session.execute(
            text(
                "INSERT INTO datasets (id, tenant_id, created_by, name, permission,"
                " embedding_model, embedding_dim, create_time, create_date, update_time,"
                " update_date)"
                " VALUES (:id, :tenant, :tenant, :name, :permission, 'fake-embed-1024', 1024,"
                " :time_ms, :time, :time_ms, :time)"
            ),
            {
                "id": dataset_id,
                "tenant": tenant_id,
                "name": name,
                "permission": permission,
                "time_ms": TIME_MS,
                "time": TIME,
            },
        )
    return dataset_id


async def _exec(sm: async_sessionmaker[AsyncSession], sql: str, **params: object) -> None:
    """Surowy zapis w transakcji (testowe kasowanie datasetu)."""
    async with transaction(sm) as session:
        await session.execute(text(sql), params)


async def _create(
    container: Container,
    principal: object,
    name: str = "wd",
    **kwargs: object,
) -> str:
    """Tworzy wyszukiwarkę z domyślnymi polami; zwraca search_id."""
    values: dict = {
        "description": "opis",
        "avatar": None,
        "search_config": None,
        "kb_ids": None,
    }
    values.update(kwargs)
    return await _svc(container).create(principal, name=name, **values)  # type: ignore[arg-type]


async def test_create_then_get_returns_kb_ids_in_order(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """create→get: nazwa po strip, ``kb_ids`` w kolejności żądania, config bez kb_ids (§D1)."""
    alice_id = await seed_user(sm)
    alice = principal_for(alice_id)
    first = await _seed_dataset(sm, alice_id, name="Pierwszy")
    second = await _seed_dataset(sm, alice_id, name="Drugi")
    config = {"chat_id": "c" * 32, "kb_ids": [second, first], "top_k": 4}
    search_id = await _create(container, alice, name=" wyszukiwarka ", search_config=config)
    view = await _svc(container).get(alice, search_id)
    assert view.row.name == "wyszukiwarka"
    assert view.row.tenant_id == alice_id
    assert view.row.created_by == alice_id
    assert view.row.description == "opis"
    assert view.row.search_config == {"chat_id": "c" * 32, "top_k": 4}
    assert view.kb_ids == [second, first]


async def test_create_without_search_config_stores_defaults_minus_kb_ids(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """``search_config=None`` → domyślny config (bez ``kb_ids``; wiązania w search_datasets)."""
    alice = principal_for(await seed_user(sm))
    search_id = await _create(container, alice, search_config=None)
    view = await _svc(container).get(alice, search_id)
    expected = default_config()
    del expected["kb_ids"]
    assert view.row.search_config == expected
    assert view.kb_ids == []


async def test_create_duplicate_name_gets_counter(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """POST dwa razy „ a " → drugi wiersz ma nazwę ``a(1)`` (przykład z briefu)."""
    alice = principal_for(await seed_user(sm))
    first_id = await _create(container, alice, name=" a ")
    second_id = await _create(container, alice, name=" a ")
    service = _svc(container)
    assert (await service.get(alice, first_id)).row.name == "a"
    assert (await service.get(alice, second_id)).row.name == "a(1)"


async def test_create_rejects_invalid_names(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Nazwa nie-string / pusta / dłuższa niż limit → 102 z komunikatem dosłownym (§D4)."""
    alice = principal_for(await seed_user(sm))
    service = _svc(container)
    with pytest.raises(ValidationFailed, match=re.escape("Search name must be string.")):
        await service.create(
            alice,
            name=123,  # type: ignore[arg-type]
            description="",
            avatar=None,
            search_config=None,
            kb_ids=None,
        )
    for empty in ("", "   "):
        with pytest.raises(ValidationFailed, match=re.escape("Search name can't be empty.")):
            await _create(container, alice, name=empty)
    with pytest.raises(ValidationFailed) as error:
        await _create(container, alice, name="x" * 256)
    assert str(error.value) == NAME_LIMIT_MESSAGE.format(length=256)
    with pytest.raises(ValidationFailed) as error:
        await _create(container, alice, name="x" * 129)
    assert str(error.value) == NAME_LIMIT_MESSAGE.format(length=129)
    assert (await service.get(alice, await _create(container, alice, name="x" * 128))).row.name


async def test_create_rejects_foreign_or_missing_dataset(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """``kb_ids`` cudzego lub nieistniejącego datasetu → 102 „You don't own the dataset” (§D4)."""
    alice = principal_for(await seed_user(sm))
    bob_id = await seed_user(sm)
    bob_dataset = await _seed_dataset(sm, bob_id, name="Boba")
    with pytest.raises(ValidationFailed, match=f"You don't own the dataset {bob_dataset}"):
        await _create(container, alice, search_config={"kb_ids": [bob_dataset]})
    missing = uuid.uuid4().hex
    with pytest.raises(ValidationFailed, match=f"You don't own the dataset {missing}"):
        await _create(container, alice, search_config={"kb_ids": [missing]})


async def test_get_missing_or_foreign_denied(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """GET brakującej i cudzej wyszukiwarki → ``PermissionDenied`` („Has no permission…")."""
    alice = principal_for(await seed_user(sm))
    bob = principal_for(await seed_user(sm))
    service = _svc(container)
    with pytest.raises(PermissionDenied, match=re.escape("Has no permission for this operation.")):
        await service.get(alice, uuid.uuid4().hex)
    search_id = await _create(container, alice)
    with pytest.raises(PermissionDenied, match=re.escape("Has no permission for this operation.")):
        await service.get(bob, search_id)


async def test_update_merges_config_and_keeps_untouched_fields(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """PUT scala config, ``description``/``avatar`` None → bez zmiany, ``kb_ids`` bez zmian."""
    alice_id = await seed_user(sm)
    alice = principal_for(alice_id)
    dataset_id = await _seed_dataset(sm, alice_id)
    search_id = await _create(
        container,
        alice,
        name="stara",
        avatar="ikona",
        search_config={"kb_ids": [dataset_id], "top_k": 1024, "chat_id": "c" * 32},
    )
    view = await _svc(container).update(
        alice,
        search_id,
        name=" nowa ",
        search_config={"top_k": 8, "summary": True},
        description=None,
        avatar=None,
    )
    assert view.row.name == "nowa"
    assert view.row.description == "opis"
    assert view.row.avatar == "ikona"
    assert view.row.search_config == {"top_k": 8, "summary": True, "chat_id": "c" * 32}
    assert view.kb_ids == [dataset_id]
    assert view.row.update_time >= view.row.create_time


async def test_update_replaces_and_keeps_kb_ids(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """``kb_ids`` w PUT zastępuje wiązania; brak klucza → wiązania bez zmian (§D1)."""
    alice_id = await seed_user(sm)
    alice = principal_for(alice_id)
    first = await _seed_dataset(sm, alice_id, name="Pierwszy")
    second = await _seed_dataset(sm, alice_id, name="Drugi")
    search_id = await _create(container, alice, search_config={"kb_ids": [first]})
    service = _svc(container)
    replaced = await service.update(
        alice,
        search_id,
        name="wd",
        search_config={"kb_ids": [second]},
        description=None,
        avatar=None,
    )
    assert replaced.kb_ids == [second]
    kept = await service.update(
        alice, search_id, name="wd", search_config={"top_k": 7}, description=None, avatar=None
    )
    assert kept.kb_ids == [second]


async def test_update_duplicate_name_rejected(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """PUT na nazwę zajętą przez inny wiersz tenanta → 102 „Duplicated search name.” (§D4)."""
    alice = principal_for(await seed_user(sm))
    await _create(container, alice, name="zajęta")
    second_id = await _create(container, alice, name="inna")
    with pytest.raises(ValidationFailed, match=re.escape("Duplicated search name.")):
        await _svc(container).update(
            alice, second_id, name="ZAJĘTA", search_config={}, description=None, avatar=None
        )
    same = await _svc(container).update(
        alice, second_id, name="inna", search_config={}, description=None, avatar=None
    )
    assert same.row.name == "inna"


async def test_update_rejects_non_object_config(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """PUT z ``search_config`` nie-obiektem → 102 „search_config must be a JSON object”."""
    alice = principal_for(await seed_user(sm))
    search_id = await _create(container, alice)
    with pytest.raises(ValidationFailed, match=re.escape("search_config must be a JSON object")):
        await _svc(container).update(
            alice,
            search_id,
            name="wd",
            search_config="nie obiekt",  # type: ignore[arg-type]
            description=None,
            avatar=None,
        )


async def test_update_missing_or_foreign_denied(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """PUT cudzej i brakującej wyszukiwarki → ``PermissionDenied("no authorization")`` (§D4)."""
    alice = principal_for(await seed_user(sm))
    bob = principal_for(await seed_user(sm))
    service = _svc(container)
    search_id = await _create(container, alice)
    for principal, target in ((bob, search_id), (alice, uuid.uuid4().hex)):
        with pytest.raises(PermissionDenied, match=re.escape("no authorization")):
            await service.update(
                principal, target, name="wd", search_config={}, description="x", avatar="y"
            )
    unchanged = await service.get(alice, search_id)
    assert (unchanged.row.name, unchanged.row.description) == ("wd", "opis")


async def test_update_foreign_does_not_bind_datasets(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Odmowa PUT nie zmienia wiązań (§D4: własność przed walidacją datasetów)."""
    alice_id = await seed_user(sm)
    alice = principal_for(alice_id)
    bob_id = await seed_user(sm)
    bob = principal_for(bob_id)
    dataset_id = await _seed_dataset(sm, alice_id)
    search_id = await _create(container, alice, search_config={"kb_ids": [dataset_id]})
    bob_dataset = await _seed_dataset(sm, bob_id, name="Boba")
    with pytest.raises(PermissionDenied, match=re.escape("no authorization")):
        await _svc(container).update(
            bob,
            search_id,
            name="wd",
            search_config={"kb_ids": [bob_dataset]},
            description=None,
            avatar=None,
        )
    assert (await _svc(container).get(alice, search_id)).kb_ids == [dataset_id]


async def test_delete_own_and_foreign(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """DELETE cudzej → ``PermissionDenied`` i wiersz zostaje; własnej → wiersz znika (§D4)."""
    alice = principal_for(await seed_user(sm))
    bob = principal_for(await seed_user(sm))
    service = _svc(container)
    search_id = await _create(container, alice)
    with pytest.raises(PermissionDenied, match=re.escape("no authorization")):
        await service.delete(bob, search_id)
    assert (await service.get(alice, search_id)).row.id == search_id
    with pytest.raises(PermissionDenied, match=re.escape("no authorization")):
        await service.delete(alice, uuid.uuid4().hex)
    await service.delete(alice, search_id)
    with pytest.raises(PermissionDenied):
        await service.get(alice, search_id)


async def test_delete_dataset_removes_binding(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Usunięcie datasetu kaskadą czyści ``search_datasets`` → ``kb_ids`` bez niego (§D1)."""
    alice_id = await seed_user(sm)
    alice = principal_for(alice_id)
    kept = await _seed_dataset(sm, alice_id, name="Zostaje")
    dropped = await _seed_dataset(sm, alice_id, name="Znika")
    search_id = await _create(container, alice, search_config={"kb_ids": [kept, dropped]})
    await _exec(sm, "DELETE FROM datasets WHERE id = :id", id=dropped)
    assert (await _svc(container).get(alice, search_id)).kb_ids == [kept]


async def test_list_scope_and_owner_ids(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Lista widzi tylko wiersze principala; ``owner_ids`` bez właściciela → ``([], 0)`` (§D5)."""
    alice_id = await seed_user(sm)
    alice = principal_for(alice_id)
    bob_id = await seed_user(sm)
    bob = principal_for(bob_id)
    await _create(container, alice, name="pierwsza")
    await _create(container, alice, name="druga")
    await _create(container, bob, name="boba")
    service = _svc(container)

    async def listing(principal: object, owner_ids: list[str]) -> tuple[list[SearchView], int]:
        return await service.list(
            principal,  # type: ignore[arg-type]
            keywords="",
            orderby="create_time",
            desc=True,
            page=1,
            page_size=30,
            owner_ids=owner_ids,
        )

    views, total = await listing(alice, [])
    assert total == OWN_SEARCHES
    assert {view.row.name for view in views} == {"pierwsza", "druga"}
    assert {view.owner_nickname for view in views} == {"seed"}
    assert all(view.kb_ids == [] for view in views)
    assert await listing(alice, [bob_id]) == ([], 0)
    assert (await listing(alice, [alice_id]))[1] == OWN_SEARCHES
    assert (await listing(alice, [alice_id, bob_id]))[1] == OWN_SEARCHES
    filtered, filtered_total = await listing(alice, [])
    assert filtered_total == len(filtered) == OWN_SEARCHES
