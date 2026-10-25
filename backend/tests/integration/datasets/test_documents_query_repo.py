"""Testy documents_query na prawdziwej MariaDB (brief T2a, kontrakt C2.1).

Wiersze tabeli „wejście → wyjście" z briefu dotyczące repozytorium mają
osobne testy; komunikaty dosłowne.
"""

import uuid
from dataclasses import replace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import datasets as datasets_repo
from app.db.repositories import documents as documents_repo
from app.db.repositories import documents_query
from app.db.repositories.documents_query import DocumentListQuery
from app.db.uow import transaction
from tests.integration.datasets.conftest import TIME_MS, exec_sql, seed_user
from tests.integration.ingest.conftest import make_document_row

pytestmark = pytest.mark.db

TWO_DOCS = 2  # dwa dokumenty a.txt, b.txt
THREE_DOCS = 3  # a.txt, b.txt, c.txt


def _query(**kwargs: object) -> DocumentListQuery:
    """DocumentListQuery(page=1, size=30, create_time, desc) z nadpisaniami."""
    values: dict = {"page": 1, "page_size": 30, "orderby": "create_time", "desc": True}
    values.update(kwargs)
    return DocumentListQuery(**values)


async def _seed_dataset(
    sm: async_sessionmaker[AsyncSession], tenant_id: str
) -> datasets_repo.DatasetRow:
    """Wstawia dataset i zwraca wiersz (dla make_document_row)."""
    dataset_id = uuid.uuid4().hex
    async with transaction(sm) as session:
        await datasets_repo.insert(
            session,
            id=dataset_id,
            tenant_id=tenant_id,
            created_by=tenant_id,
            name="A",
            description=None,
            avatar=None,
            language="English",
            embedding_model="fake-embed-1024",
            embedding_dim=1024,
            permission="me",
            chunk_method="naive",
            parser_config={"chunk_token_num": 512},
            now_ms=TIME_MS,
        )
        return await datasets_repo.get(session, dataset_id)


async def _seed_documents(
    sm: async_sessionmaker[AsyncSession],
    tenant_id: str,
    names: list[str],
    *,
    run: str = "0",
) -> tuple[str, list[str]]:
    """Wstawia dataset z dokumentami o podanych nazwach; zwraca (dataset_id, doc_ids)."""
    dataset = await _seed_dataset(sm, tenant_id)
    doc_ids: list[str] = []
    for ordinal, name in enumerate(names):
        row = make_document_row(dataset, name=name, now_ms=TIME_MS + ordinal)
        async with transaction(sm) as session:
            await documents_repo.insert(session, replace(row, run=run))
        doc_ids.append(row.id)
    return dataset.id, doc_ids


async def test_list_page_returns_rows_with_nickname(sm: async_sessionmaker[AsyncSession]) -> None:
    """list_page: (wiersz, nickname twórcy) + total; JOIN users po created_by."""
    user_id, _ = await seed_user(sm, nickname="Alice")
    dataset_id, _doc_ids = await _seed_documents(sm, user_id, ["a.txt", "b.txt"])
    async with transaction(sm) as session:
        rows, total = await documents_query.list_page(session, dataset_id, _query())
    assert total == TWO_DOCS
    assert [row.name for row, _ in rows] == ["b.txt", "a.txt"]  # desc po czasie (TIME_MS+ordinal)
    assert {nickname for _, nickname in rows} == {"Alice"}


async def test_list_page_missing_user_gives_empty_nickname(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """LEFT JOIN users: brak użytkownika → nickname ""."""
    user_id, _ = await seed_user(sm)
    dataset_id, _doc_ids = await _seed_documents(sm, user_id, ["a.txt"])
    await exec_sql(sm, "UPDATE documents SET created_by = :cb", cb="0" * 32)
    async with transaction(sm) as session:
        rows, _total = await documents_query.list_page(session, dataset_id, _query())
    assert [nickname for _, nickname in rows] == [""]


async def test_list_page_filters_document_id_name_keywords(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """Filtry: document_id (id =), name (=), keywords (LIKE bez wielkości liter)."""
    user_id, _ = await seed_user(sm)
    dataset_id, doc_ids = await _seed_documents(sm, user_id, ["a.txt", "b.txt"])
    async with transaction(sm) as session:
        rows, total = await documents_query.list_page(
            session, dataset_id, _query(document_id=doc_ids[0])
        )
        assert total == 1 and rows[0][0].id == doc_ids[0]
        rows, total = await documents_query.list_page(session, dataset_id, _query(name="b.txt"))
        assert total == 1 and rows[0][0].name == "b.txt"
        rows, total = await documents_query.list_page(session, dataset_id, _query(keywords="A."))
        assert total == 1 and rows[0][0].name == "a.txt"


async def test_list_page_filters_ids_runs_suffixes(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """Filtry listowe: ids/runs/suffixes — IN expanding; niepusty tylko gdy podany."""
    user_id, _ = await seed_user(sm)
    dataset_id, doc_ids = await _seed_documents(sm, user_id, ["a.txt", "b.txt"])
    async with transaction(sm) as session:
        rows, total = await documents_query.list_page(
            session, dataset_id, _query(ids=(doc_ids[0], "zzz"))
        )
        assert total == 1 and rows[0][0].id == doc_ids[0]
        rows, total = await documents_query.list_page(session, dataset_id, _query(runs=("3",)))
        assert (rows, total) == ([], 0)
        rows, total = await documents_query.list_page(session, dataset_id, _query(runs=("0",)))
        assert total == TWO_DOCS
        rows, total = await documents_query.list_page(
            session, dataset_id, _query(suffixes=("txt",))
        )
        assert total == TWO_DOCS


async def test_list_page_pagination_and_page_size_zero(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """Strona 2 (page_size=1) → najstarszy wiersz; page_size=0 → ([], total)."""
    user_id, _ = await seed_user(sm)
    dataset_id, _doc_ids = await _seed_documents(sm, user_id, ["a.txt", "b.txt", "c.txt"])
    async with transaction(sm) as session:
        rows, total = await documents_query.list_page(
            session, dataset_id, _query(page=2, page_size=1)
        )
        assert total == THREE_DOCS and rows[0][0].name == "b.txt"
        rows, total = await documents_query.list_page(session, dataset_id, _query(page_size=0))
        assert (rows, total) == ([], THREE_DOCS)


async def test_list_page_orderby_name(sm: async_sessionmaker[AsyncSession]) -> None:
    """orderby=name: kolejność wg kolacji kolumny; desc=true odwraca nazwy (T3 briefu)."""
    user_id, _ = await seed_user(sm)
    dataset_id, _doc_ids = await _seed_documents(sm, user_id, ["b", "A", "c"])
    async with transaction(sm) as session:
        rows, total = await documents_query.list_page(
            session, dataset_id, _query(orderby="name", desc=False)
        )
        assert total == THREE_DOCS
        assert [row.name for row, _ in rows] == ["A", "b", "c"]
        rows, _total = await documents_query.list_page(
            session, dataset_id, _query(orderby="name", desc=True)
        )
        assert [row.name for row, _ in rows] == ["c", "b", "A"]


async def test_list_page_orderby_name_ties_by_id(sm: async_sessionmaker[AsyncSession]) -> None:
    """Nazwy równe w kolacji kolumny ('A' i 'a' w ai_ci) → remis rozstrzyga id rosnąco."""
    user_id, _ = await seed_user(sm)
    dataset_id, doc_ids = await _seed_documents(sm, user_id, ["A", "a"])
    async with transaction(sm) as session:
        rows, _total = await documents_query.list_page(
            session, dataset_id, _query(orderby="name", desc=False)
        )
    assert [row.id for row, _ in rows] == sorted(doc_ids)


async def test_list_page_invalid_orderby(sm: async_sessionmaker[AsyncSession]) -> None:
    """orderby spoza białej listy → ValueError."""
    user_id, _ = await seed_user(sm)
    dataset_id, _doc_ids = await _seed_documents(sm, user_id, ["a.txt"])
    async with transaction(sm) as session:
        try:
            await documents_query.list_page(session, dataset_id, _query(orderby="zzz"))
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError")


async def test_ids_in_dataset(sm: async_sessionmaker[AsyncSession]) -> None:
    """ids_in_dataset(s, A, [id_a, 'zzz']) → {id_a} (brief T2a)."""
    user_id, _ = await seed_user(sm)
    dataset_id, doc_ids = await _seed_documents(sm, user_id, ["a.txt", "b.txt"])
    async with transaction(sm) as session:
        present = await documents_query.ids_in_dataset(session, dataset_id, [doc_ids[0], "zzz"])
    assert present == {doc_ids[0]}
    async with transaction(sm) as session:
        assert await documents_query.ids_in_dataset(session, dataset_id, []) == set()


async def test_names_in_dataset(sm: async_sessionmaker[AsyncSession]) -> None:
    """names_in_dataset(s, A) → {'a.txt', 'b.txt'} (brief T2a)."""
    user_id, _ = await seed_user(sm)
    dataset_id, _doc_ids = await _seed_documents(sm, user_id, ["a.txt", "b.txt"])
    async with transaction(sm) as session:
        assert await documents_query.names_in_dataset(session, dataset_id) == {
            "a.txt",
            "b.txt",
        }


async def test_update_meta_updates_whitelisted_columns(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """update_meta: name, chunk_method, parser_config (JSON), enabled (0/1), meta_fields."""
    user_id, _ = await seed_user(sm)
    _dataset_id, doc_ids = await _seed_documents(sm, user_id, ["a.txt"])
    now = TIME_MS + 5000
    async with transaction(sm) as session:
        await documents_query.update_meta(
            session,
            doc_ids[0],
            {
                "name": "c.txt",
                "chunk_method": "book",
                "parser_config": {"chunk_token_num": 128},
                "enabled": False,
                "meta_fields": {"k": "v"},
            },
            now_ms=now,
        )
        row = await documents_repo.get(session, doc_ids[0])
    assert row is not None
    assert row.name == "c.txt"
    assert row.chunk_method == "book"
    assert row.parser_config == {"chunk_token_num": 128}
    assert row.enabled is False
    assert row.meta_fields == {"k": "v"}
    assert row.update_time == now


async def test_update_meta_unknown_column(sm: async_sessionmaker[AsyncSession]) -> None:
    """update_meta(s, id_a, {'size': 1}) → ValueError (brief T2a)."""
    user_id, _ = await seed_user(sm)
    _dataset_id, doc_ids = await _seed_documents(sm, user_id, ["a.txt"])
    async with transaction(sm) as session:
        try:
            await documents_query.update_meta(session, doc_ids[0], {"size": 1}, now_ms=TIME_MS)
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError")


async def test_update_meta_empty_fields_touches_times_only(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """Pusty fields → tylko update_time/update_date."""
    user_id, _ = await seed_user(sm)
    _dataset_id, doc_ids = await _seed_documents(sm, user_id, ["a.txt"])
    now = TIME_MS + 5000
    async with transaction(sm) as session:
        await documents_query.update_meta(session, doc_ids[0], {}, now_ms=now)
        row = await documents_repo.get(session, doc_ids[0])
    assert row is not None
    assert row.update_time == now
    assert row.name == "a.txt"
