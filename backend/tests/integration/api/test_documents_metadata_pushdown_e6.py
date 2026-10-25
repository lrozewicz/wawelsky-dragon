"""Test DB pushdownu nadzbioru filtra metadanych (DEC-300 p. 2, zadanie T6b).

Pushdown SQL w ``documents_query.meta_fields_by_document`` jest tylko NADZBIOREM kandydatów —
ostateczne dopasowanie liczy ``match_documents``. Test pilnuje, że pushdown nie gubi żadnego
trafienia: dla każdego filtra wynik na zbiorze zawężonym SQL-em musi być identyczny z wynikiem
na pełnym zbiorze dokumentów (wielkość liter, polskie znaki, ``ß``, sigma, znak Kelvina U+212A,
spacja końcowa, liczba JSON, lista, ``null``, brak klucza).
"""

import uuid
from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import datasets as datasets_repo
from app.db.repositories import documents as documents_repo
from app.db.repositories import documents_query
from app.db.uow import transaction
from app.domain.retrieval.metadata import (
    MetadataCondition,
    match_documents,
    parse_metadata_condition,
    pushdown_condition,
)
from tests.integration.datasets.conftest import TIME_MS, seed_user
from tests.integration.ingest.conftest import make_document_row

pytestmark = pytest.mark.db

# Metadane pokrywające przypadki nadzbiorowości z briefu (jeden klucz ``author`` — pushdownowalny
# dla czystego tekstu — plus lista/``null``/brak klucza).
_META: dict[str, dict[str, Any]] = {
    "a.txt": {"author": "Kowalski"},
    "b.txt": {"author": "KOWALSKI"},
    "c.txt": {"author": "Łódź"},
    "d.txt": {"author": "łÓDŹ"},
    "e.txt": {"author": "Straße"},
    "f.txt": {"author": "STRASSE"},
    "g.txt": {"author": "ΟΔΟΣ"},
    "h.txt": {"author": "οδος"},
    "i.txt": {"author": chr(0x212A)},  # ZNAK KELVINA (U+212A) - lower() Pythona → "k"
    "j.txt": {"author": "k"},
    "k.txt": {"author": "Kowalski "},  # spacja końcowa
    "l.txt": {"author": 2020},  # liczba JSON
    "m.txt": {"author": ["Kowalski", "x"]},  # lista
    "n.txt": {"author": None},  # null JSON
    "o.txt": {"other": "Kowalski"},  # brak klucza ``author``
}


def _condition(value: Any) -> MetadataCondition:
    return parse_metadata_condition(
        {"conditions": [{"name": "author", "comparison_operator": "is", "value": value}]}
    )


async def _seed(sm: async_sessionmaker[AsyncSession]) -> str:
    """Dataset + dokumenty z ``_META``; zwraca dataset_id."""
    user_id, _ = await seed_user(sm)
    dataset_id = uuid.uuid4().hex
    async with transaction(sm) as session:
        await datasets_repo.insert(
            session,
            id=dataset_id,
            tenant_id=user_id,
            created_by=user_id,
            name="wd_pushdown_e6",
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
        dataset = await datasets_repo.get(session, dataset_id)
    for ordinal, (name, meta) in enumerate(_META.items()):
        row = make_document_row(dataset, name=name, now_ms=TIME_MS + ordinal)
        async with transaction(sm) as session:
            await documents_repo.insert(session, replace(row, meta_fields=meta))
    return dataset_id


@pytest.mark.parametrize(
    "value", ["Kowalski", "kowalski", "Łódź", "łódź", "Straße", "ΟΔΟΣ", "οδος", "k", "Kowalski "]
)
async def test_pushdown_is_superset_of_matches(
    sm: async_sessionmaker[AsyncSession], value: str
) -> None:
    """Dla czystego tekstu pushdown się włącza, a wynik == dopasowaniu na pełnym zbiorze."""
    dataset_id = await _seed(sm)
    cond = _condition(value)
    assert pushdown_condition(cond) is not None  # pushdown aktywny (czysty tekst)

    async with transaction(sm) as session:
        full = await documents_query.meta_fields_by_document(session, dataset_id)
        pushed = await documents_query.meta_fields_by_document(
            session, dataset_id, pushdown=pushdown_condition(cond)
        )

    assert set(pushed) <= set(full)  # SQL tylko zawęża (nadzbiór kandydatów)
    full_match = match_documents(full, cond)
    pushed_match = match_documents(pushed, cond)
    assert pushed_match == full_match  # pushdown nie gubi trafień
    # Sanity: filtr rzeczywiście coś trafia (case-insensitive), więc to nie pusta równość.
    assert full_match


async def test_pushdown_disabled_for_number_value_matches_full(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """Wartość liczbowa (``"2020"`` parsuje literal_eval) → brak pushdownu, wynik bez zmian."""
    dataset_id = await _seed(sm)
    cond = _condition("2020")
    assert pushdown_condition(cond) is None

    async with transaction(sm) as session:
        full = await documents_query.meta_fields_by_document(session, dataset_id)
        pushed = await documents_query.meta_fields_by_document(
            session, dataset_id, pushdown=pushdown_condition(cond)
        )

    assert match_documents(pushed, cond) == match_documents(full, cond)


async def test_pushdown_or_all_pushable_is_superset(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """Logika ``or`` z wszystkimi pushowalnymi warunkami — OR w SQL nie gubi trafień."""
    dataset_id = await _seed(sm)
    cond = parse_metadata_condition(
        {
            "logic": "or",
            "conditions": [
                {"name": "author", "comparison_operator": "is", "value": "Kowalski"},
                {"name": "author", "comparison_operator": "is", "value": "łódź"},
            ],
        }
    )
    pushdown = pushdown_condition(cond)
    assert pushdown is not None and pushdown.logic == "or"

    async with transaction(sm) as session:
        full = await documents_query.meta_fields_by_document(session, dataset_id)
        pushed = await documents_query.meta_fields_by_document(
            session, dataset_id, pushdown=pushdown
        )

    assert match_documents(pushed, cond) == match_documents(full, cond)
