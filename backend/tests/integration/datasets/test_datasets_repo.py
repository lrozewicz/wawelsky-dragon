"""Testy repozytorium datasets na prawdziwej MariaDB (brief T1a, kontrakt C1.1)."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import datasets as datasets_repo
from app.db.repositories import documents as documents_repo
from app.db.uow import transaction
from app.domain.policy import VisibilityFilter
from tests.integration.datasets.conftest import TIME_MS, date_ms, seed_user
from tests.integration.ingest.conftest import make_document_row

pytestmark = pytest.mark.db

EMBED_DIM = 1024
OTHER_EMBED_DIM = 768
SIM_THRESHOLD_DEFAULT = 0.2  # DDL datasets.similarity_threshold DEFAULT
VEC_WEIGHT_DEFAULT = 0.3  # DDL datasets.vector_similarity_weight DEFAULT
SIM_UPDATED = 0.123457  # round(0.1234567891, 6)
VEC_UPDATED = 0.987654  # round(0.9876543210, 6)
SIM_THRESHOLD_UPDATED = 0.5
VEC_WEIGHT_UPDATED = 0.25
PAGERANK = 7

CONFIG: dict = {"chunk_token_num": 512, "parent_child": {"use_parent_child": False}}


async def _insert(  # noqa: PLR0913 — parametry wstawianego wiersza
    sm: async_sessionmaker[AsyncSession],
    tenant_id: str,
    *,
    name: str,
    permission: str = "me",
    language: str = "English",
    now_ms: int = TIME_MS,
    dataset_id: str | None = None,
) -> str:
    """Wstawia dataset przez datasets_repo.insert; zwraca id (brief T1a)."""
    final_id = dataset_id or uuid.uuid4().hex
    async with transaction(sm) as session:
        await datasets_repo.insert(
            session,
            id=final_id,
            tenant_id=tenant_id,
            created_by=tenant_id,
            name=name,
            description=None,
            avatar=None,
            language=language,
            embedding_model="fake-embed-1024",
            embedding_dim=EMBED_DIM,
            permission=permission,
            chunk_method="naive",
            parser_config=CONFIG,
            now_ms=now_ms,
        )
    return final_id


async def _get_row(
    sm: async_sessionmaker[AsyncSession], dataset_id: str
) -> datasets_repo.DatasetRecord | None:
    """get_record w osobnej transakcji (odczyty testowe)."""
    async with transaction(sm) as session:
        return await datasets_repo.get_record(session, dataset_id)


def _filters(all_: bool, owners: frozenset[str], team: bool) -> VisibilityFilter:
    """VisibilityFilter bez grantów (pole granted_ids domyślne)."""
    return VisibilityFilter(all_, owners, team)


async def _list(  # noqa: PLR0913 — parametry zapytania
    sm: async_sessionmaker[AsyncSession],
    visibility: VisibilityFilter,
    *,
    limit: int = 30,
    offset: int = 0,
    orderby: str = "create_time",
    desc: bool = True,
    **filters: str,
) -> tuple[list[datasets_repo.DatasetRecord], int]:
    """list_records z domyślnymi parametrami strony (odczyty testowe)."""
    async with transaction(sm) as session:
        return await datasets_repo.list_records(
            session,
            visibility=visibility,
            offset=offset,
            limit=limit,
            orderby=orderby,
            desc=desc,
            **filters,
        )


async def test_insert_and_get_record_roundtrip(sm: async_sessionmaker[AsyncSession]) -> None:
    """insert + get_record: wszystkie kolumny, nickname właściciela, JSON jako dict (C1.1)."""
    user_id, _email = await seed_user(sm)
    dataset_id = await _insert(sm, user_id, name="Korpus", permission="team", language="Polish")
    rec = await _get_row(sm, dataset_id)
    assert rec is not None
    assert rec.id == dataset_id
    assert rec.tenant_id == user_id
    assert rec.created_by == user_id
    assert rec.name == "Korpus"
    assert rec.description is None
    assert rec.avatar is None
    assert rec.language == "Polish"
    assert rec.embedding_model == "fake-embed-1024"
    assert rec.embedding_dim == EMBED_DIM
    assert rec.permission == "team"
    assert rec.chunk_method == "naive"
    assert rec.parser_config == CONFIG
    assert rec.similarity_threshold == SIM_THRESHOLD_DEFAULT
    assert rec.vector_similarity_weight == VEC_WEIGHT_DEFAULT
    assert rec.pagerank == 0
    assert rec.document_count == 0
    assert rec.chunk_count == 0
    assert rec.token_num == 0
    assert rec.status == "1"
    assert rec.create_time == TIME_MS
    assert rec.update_time == TIME_MS
    assert rec.owner_nickname == "Alice"


async def test_get_record_missing_returns_none(sm: async_sessionmaker[AsyncSession]) -> None:
    """get_record nieistniejącego id → None (C1.1)."""
    assert await _get_row(sm, "0" * 32) is None


async def test_float_columns_rounded_to_six(sm: async_sessionmaker[AsyncSession]) -> None:
    """FLOAT MariaDB (0.2 → 0.200000003) zwracany jako round(x, 6) (brief T1a pkt 3)."""
    user_id, _email = await seed_user(sm)
    dataset_id = await _insert(sm, user_id, name="Korpus")
    async with transaction(sm) as session:
        await session.execute(
            text(
                "UPDATE datasets SET similarity_threshold = 0.1234567891,"
                " vector_similarity_weight = 0.9876543210 WHERE id = :id"
            ),
            {"id": dataset_id},
        )
    rec = await _get_row(sm, dataset_id)
    assert rec is not None
    assert rec.similarity_threshold == SIM_UPDATED
    assert rec.vector_similarity_weight == VEC_UPDATED


async def test_list_records_visibility_variants(sm: async_sessionmaker[AsyncSession]) -> None:
    """Filtr widoczności: all, właściciel+team, cudzy właściciel, pusty, sami team (C1.1)."""
    alice_id, _ = await seed_user(sm, nickname="A")
    bob_id, _ = await seed_user(sm, nickname="B")
    own = await _insert(sm, alice_id, name="own")
    shared = await _insert(sm, alice_id, name="shared", permission="team")
    foreign = await _insert(sm, bob_id, name="bobs")

    everything, everything_total = await _list(sm, _filters(True, frozenset(), False))
    assert everything_total == len({own, shared, foreign})
    assert {rec.id for rec in everything} == {own, shared, foreign}

    alice_view, alice_total = await _list(sm, _filters(False, frozenset({alice_id}), True))
    assert alice_total == len({own, shared})
    assert {rec.id for rec in alice_view} == {own, shared}

    # Bob: własny + udostępniony zespołowi; prywatny Alice niewidoczny (C0 p. 3).
    bob_view, bob_total = await _list(sm, _filters(False, frozenset({bob_id}), True))
    assert bob_total == len({foreign, shared})
    assert {rec.id for rec in bob_view} == {foreign, shared}

    bob_private, bob_private_total = await _list(sm, _filters(False, frozenset({bob_id}), False))
    assert bob_private_total == 1
    assert {rec.id for rec in bob_private} == {foreign}

    nobody, nobody_total = await _list(sm, _filters(False, frozenset(), False))
    assert (nobody, nobody_total) == ([], 0)

    # Pusty owner_ids z include_team — pusty IN rozwijany jako warunek fałszywy (C1.1).
    team_only, team_total = await _list(sm, _filters(False, frozenset(), True))
    assert team_total == 1
    assert {rec.id for rec in team_only} == {shared}


async def test_list_records_filters(sm: async_sessionmaker[AsyncSession]) -> None:
    """Filtry: dataset_id, name (bez wielkości liter), keywords LIKE (C1.1)."""
    alice_id, _ = await seed_user(sm)
    target = await _insert(sm, alice_id, name="Raporty")
    await _insert(sm, alice_id, name="Notatki")

    rows, total = await _list(sm, _filters(True, frozenset(), False), dataset_id=target)
    assert total == 1 and rows[0].id == target

    rows, total = await _list(sm, _filters(True, frozenset(), False), name="RAPORTY")
    assert total == 1 and rows[0].name == "Raporty"

    rows, total = await _list(sm, _filters(True, frozenset(), False), keywords="APO")
    assert total == 1 and rows[0].id == target

    assert (await _list(sm, _filters(True, frozenset(), False), name="brak"))[1] == 0
    assert (await _list(sm, _filters(True, frozenset(), False), dataset_id="0" * 32))[1] == 0


async def test_list_records_order_and_pagination(sm: async_sessionmaker[AsyncSession]) -> None:
    """ORDER BY kolumna/kierunek z remisem po id; LIMIT/OFFSET; limit=0; kolumna poza listą."""
    alice_id, _ = await seed_user(sm)
    old = await _insert(sm, alice_id, name="old", now_ms=TIME_MS)
    tie_low = await _insert(sm, alice_id, name="tie_a", now_ms=TIME_MS + 1, dataset_id="a" * 32)
    tie_high = await _insert(sm, alice_id, name="tie_b", now_ms=TIME_MS + 1, dataset_id="b" * 32)
    new = await _insert(sm, alice_id, name="new", now_ms=TIME_MS + 2)
    visibility = _filters(False, frozenset({alice_id}), False)

    page, total = await _list(sm, visibility, limit=2)
    assert total == len({old, tie_low, tie_high, new})
    assert [rec.id for rec in page] == [new, tie_low]  # remis po id rosnąco

    tail, _ = await _list(sm, visibility, limit=2, offset=2)
    assert [rec.id for rec in tail] == [tie_high, old]

    asc, _ = await _list(sm, visibility, limit=10, desc=False)
    assert [rec.id for rec in asc] == [old, tie_low, tie_high, new]

    empty, counted = await _list(sm, visibility, limit=0)
    assert empty == [] and counted == len([old, tie_low, tie_high, new])

    with pytest.raises(ValueError, match="orderby"):
        await _list(sm, _filters(True, frozenset(), False), orderby="name; DROP TABLE datasets")


async def test_names_taken_lowercase(sm: async_sessionmaker[AsyncSession]) -> None:
    """names_taken: zbiór nazw MAŁYMI literami dla danego tenanta (C1.1)."""
    alice_id, _ = await seed_user(sm)
    await _insert(sm, alice_id, name="Korpus")
    await _insert(sm, alice_id, name="Raporty")
    async with transaction(sm) as session:
        taken = await datasets_repo.names_taken(session, alice_id)
    assert taken == {"korpus", "raporty"}


async def test_update_fields_whitelist(sm: async_sessionmaker[AsyncSession]) -> None:
    """update_fields: wszystkie kolumny białej listy + update_time; parser_config JSON (C1.1)."""
    alice_id, _ = await seed_user(sm)
    dataset_id = await _insert(sm, alice_id, name="Korpus")
    fields = {
        "name": "Nowa nazwa",
        "description": "opis",
        "avatar": "avatar.png",
        "language": "Chinese",
        "embedding_model": "inny-embed",
        "embedding_dim": 768,
        "permission": "team",
        "chunk_method": "book",
        "parser_config": {"chunk_token_num": 128, "nested": {"a": 1}},
        "similarity_threshold": 0.5,
        "vector_similarity_weight": 0.25,
        "pagerank": 7,
    }
    async with transaction(sm) as session:
        await datasets_repo.update_fields(session, dataset_id, fields, now_ms=TIME_MS + 99)
    rec = await _get_row(sm, dataset_id)
    assert rec is not None
    assert rec.name == "Nowa nazwa"
    assert rec.description == "opis"
    assert rec.avatar == "avatar.png"
    assert rec.language == "Chinese"
    assert rec.embedding_model == "inny-embed"
    assert rec.embedding_dim == OTHER_EMBED_DIM
    assert rec.permission == "team"
    assert rec.chunk_method == "book"
    assert rec.parser_config == {"chunk_token_num": 128, "nested": {"a": 1}}
    assert rec.similarity_threshold == SIM_THRESHOLD_UPDATED
    assert rec.vector_similarity_weight == VEC_WEIGHT_UPDATED
    assert rec.pagerank == PAGERANK
    assert rec.update_time == TIME_MS + 99


async def test_update_fields_partial_and_unknown(sm: async_sessionmaker[AsyncSession]) -> None:
    """update_fields: tylko podane klucze; obca kolumna → ValueError (C1.1)."""
    alice_id, _ = await seed_user(sm)
    dataset_id = await _insert(sm, alice_id, name="Korpus")
    async with transaction(sm) as session:
        await datasets_repo.update_fields(
            session, dataset_id, {"description": "kot"}, now_ms=TIME_MS
        )
    rec = await _get_row(sm, dataset_id)
    assert rec is not None
    assert rec.description == "kot"
    assert rec.language == "English"  # nietknięte
    async with transaction(sm) as session:
        with pytest.raises(ValueError, match="tenant_id"):
            await datasets_repo.update_fields(
                session, dataset_id, {"tenant_id": "x"}, now_ms=TIME_MS
            )


async def _link_chat(
    sm: async_sessionmaker[AsyncSession], chat_id: str, tenant_id: str, dataset_id: str
) -> None:
    """Wstawia czat tenanta i powiązanie chat_datasets (SQL testowy)."""
    async with transaction(sm) as session:
        await session.execute(
            text(
                "INSERT INTO chats (id, tenant_id, created_by, name, llm_id, prompt_config,"
                " create_time, create_date, update_time, update_date)"
                " VALUES (:id, :tenant, :tenant, 'Czat', '', '{}', :t, :d, :t, :d)"
            ),
            {"id": chat_id, "tenant": tenant_id, "t": TIME_MS, "d": date_ms(TIME_MS)},
        )
        await session.execute(
            text("INSERT INTO chat_datasets (chat_id, dataset_id, ordinal) VALUES (:c, :ds, 0)"),
            {"c": chat_id, "ds": dataset_id},
        )


async def test_delete_removes_links_first(sm: async_sessionmaker[AsyncSession]) -> None:
    """delete: czyści chat_datasets (FK RESTRICT), usuwa dataset; rowcount; powtórka → 0."""
    alice_id, _ = await seed_user(sm)
    dataset_id = await _insert(sm, alice_id, name="Korpus")
    await _link_chat(sm, "c" * 32, alice_id, dataset_id)
    async with transaction(sm) as session:
        deleted = await datasets_repo.delete(session, dataset_id)
    assert deleted == 1
    assert await _get_row(sm, dataset_id) is None
    async with transaction(sm) as session:
        links = (
            await session.execute(
                text("SELECT COUNT(*) FROM chat_datasets WHERE dataset_id = :id"),
                {"id": dataset_id},
            )
        ).scalar_one()
    assert links == 0
    async with transaction(sm) as session:
        assert await datasets_repo.delete(session, dataset_id) == 0


async def test_list_document_ids(sm: async_sessionmaker[AsyncSession]) -> None:
    """list_document_ids: id dokumentów datasetu; pusty dataset → [] (C1.1)."""
    alice_id, _ = await seed_user(sm)
    dataset_id = await _insert(sm, alice_id, name="Korpus")
    async with transaction(sm) as session:
        row = await datasets_repo.get(session, dataset_id)
    assert row is not None
    docs = []
    async with transaction(sm) as session:
        for name in ("a.txt", "b.txt"):
            doc = make_document_row(row, name=name)
            await documents_repo.insert(session, doc)
            docs.append(doc.id)
    async with transaction(sm) as session:
        found = await datasets_repo.list_document_ids(session, dataset_id)
    assert sorted(found) == sorted(docs)
    empty = await _insert(sm, alice_id, name="Pusty")
    async with transaction(sm) as session:
        assert await datasets_repo.list_document_ids(session, empty) == []
