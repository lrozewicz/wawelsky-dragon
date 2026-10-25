"""Testy ChunkService na prawdziwej MariaDB + fake-llm (brief T3b, kontrakt C3.2).

Wiersze tabeli „wejście → wyjście" z briefu mają osobne testy; komunikaty dosłowne.
Alice i Bob; dataset A Alice (permission="me", model fake-embed-1024); dokument
wgrany przez DocumentService.upload — bez parsowania, więc 0 chunków.
"""

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import text

from app.core.container import Container
from app.core.error_codes import RetCode
from app.core.errors import Conflict, NotFound, PermissionDenied
from app.db.repositories import chunk_vectors
from app.db.repositories import chunks as chunks_repo
from app.db.repositories import datasets as datasets_repo
from app.db.repositories import documents as documents_repo
from app.db.repositories.chunks import ChunkRecord
from app.db.uow import transaction
from app.domain.policy import Principal
from app.services.chunks import ChunkService
from app.services.datasets import DatasetService
from app.services.documents import DocumentService
from app.services.ingest import UploadSource
from tests.integration.datasets.conftest import count_sql, seed_default_models, seed_user

pytestmark = [
    pytest.mark.db,
    pytest.mark.fakellm,
    pytest.mark.skipif(
        not os.environ.get("WD_LLM_BASE_URL"),
        reason="fakellm: brak WD_LLM_BASE_URL (eksportuje verify.sh)",
    ),
]

DIM = 1024  # tabela wektorów fake-embed-1024 (seed_default_models)
ID_LEN = 16  # długość id chunka ręcznego (new_chunk_id)
TWO_CHUNKS = 2  # liczba chunków w setupach list/switch/delete


@dataclass
class Setup:
    """Stan współdzielony testów (dane z tabeli briefu T3b)."""

    svc: ChunkService
    dataset_id: str
    doc_id: str
    alice: Principal


async def gen(data: bytes) -> AsyncIterator[bytes]:
    """Strumień bajtów dla upload (wzór: test_document_service.py)."""
    yield data


async def _setup(container: Container) -> Setup:
    """Alice + dataset A (permission=me) + dokument plik.txt przez usługę."""
    await seed_default_models(container.sessionmaker)
    alice_id, alice_email = await seed_user(container.sessionmaker)
    alice = Principal(
        user_id=alice_id, email=alice_email, is_superuser=False, is_service=False, auth_kind="jwt"
    )
    dataset = await DatasetService(container).create(alice, name="A")
    docs = await DocumentService(container).upload(
        alice, dataset.id, [UploadSource(stream=gen(b"hello"), filename="plik.txt")]
    )
    return Setup(ChunkService(container), dataset.id, docs[0].id, alice)


async def _bob(container: Container) -> Principal:
    """Principal Boba (drugi użytkownik z briefu)."""
    bob_id, bob_email = await seed_user(container.sessionmaker, nickname="Bob")
    return Principal(
        user_id=bob_id, email=bob_email, is_superuser=False, is_service=False, auth_kind="jwt"
    )


async def _create(
    setup: Setup,
    content: str,
    *,
    important_keywords: list[str] | None = None,
    questions: list[str] | None = None,
    tag_kwd: list[str] | None = None,
) -> ChunkRecord:
    """Ręczny chunk z domyślnie pustymi keywordami/pytaniami/tagami."""
    return await setup.svc.create(
        setup.alice,
        setup.dataset_id,
        setup.doc_id,
        content=content,
        important_keywords=important_keywords or [],
        questions=questions or [],
        tag_kwd=tag_kwd or [],
    )


async def _list(setup: Setup, *, keywords: str | None = None, chunk_id: str | None = None) -> Any:
    """list(page=1, page_size=30) z opcjonalnymi filtrami (wiersz briefu T3b)."""
    return await setup.svc.list(
        setup.alice,
        setup.dataset_id,
        setup.doc_id,
        page=1,
        page_size=30,
        keywords=keywords,
        chunk_id=chunk_id,
    )


async def _update(setup: Setup, chunk_id: str, fields: dict[str, Any]) -> None:
    """update od Alice (pomocnik skracający wywołania testowe)."""
    await setup.svc.update(setup.alice, setup.dataset_id, setup.doc_id, chunk_id, fields)


async def _scalar(container: Container, sql: str, **params: object) -> object:
    """Pojedyncza wartość z SQL (odczyty testowe: liczniki, wektory)."""
    async with transaction(container.sessionmaker) as session:
        return (await session.execute(text(sql), params)).scalar_one()


async def _counter(container: Container, table: str, row_id: str) -> int:
    """chunk_count z tabeli documents/datasets dla wiersza (odczyt testowy)."""
    return int(
        await _scalar(container, f"SELECT chunk_count FROM {table} WHERE id = :i", i=row_id)  # noqa: S608
    )


async def _vector_of(container: Container, chunk_id: str) -> str:
    """Tekstowa postać wektora chunka (VEC_ToText) z tabeli d1024."""
    table = chunk_vectors.table_name(DIM)
    return str(
        await _scalar(
            container,
            f"SELECT VEC_ToText(embedding) FROM {table} WHERE chunk_id = :i",  # noqa: S608
            i=chunk_id,
        )
    )


async def test_create_first_chunk(container: Container) -> None:
    """create → ChunkRecord z id 16 hex, licznikami 1 i wierszem wektora (brief T3b)."""
    setup = await _setup(container)
    chunk = await _create(setup, "Ala ma kota", important_keywords=["kot"], tag_kwd=["t1"])
    assert len(chunk.id) == ID_LEN
    assert chunk.content == "Ala ma kota"
    assert chunk.keywords == ["kot"]
    assert chunk.tags == ["t1"]
    assert chunk.available is True
    assert chunk.ordinal == 0
    assert await _counter(container, "documents", setup.doc_id) == 1
    assert await _counter(container, "datasets", setup.dataset_id) == 1
    assert (
        await count_sql(
            container.sessionmaker,
            f"SELECT chunk_id FROM {chunk_vectors.table_name(DIM)} WHERE chunk_id = :i",  # noqa: S608
            i=chunk.id,
        )
        == 1
    )


async def test_create_second_chunk_ordinal(container: Container) -> None:
    """Drugi create (inna treść) → ordinal 1 i chunk_count 2 (brief T3b)."""
    setup = await _setup(container)
    await _create(setup, "Ala ma kota")
    chunk = await _create(setup, "Inna treść")
    assert chunk.ordinal == 1
    assert await _counter(container, "documents", setup.doc_id) == TWO_CHUNKS


async def test_create_empty_content(container: Container) -> None:
    """create content="   " → Conflict "`content` is required" (brief T3b)."""
    setup = await _setup(container)
    with pytest.raises(Conflict) as exc:
        await _create(setup, "   ")
    assert str(exc.value) == "`content` is required"


async def test_create_foreign_user(container: Container) -> None:
    """create(bob, A, d) → PermissionDenied 108 (brief T3b)."""
    setup = await _setup(container)
    svc = ChunkService(container)
    with pytest.raises(PermissionDenied) as exc:
        await svc.create(
            await _bob(container),
            setup.dataset_id,
            setup.doc_id,
            content="x",
            important_keywords=[],
            questions=[],
            tag_kwd=[],
        )
    assert exc.value.code == RetCode.PERMISSION_ERROR


async def test_create_missing_document(container: Container) -> None:
    """create(alice, A, "nieistnieje") → NotFound "you don't own the document …" (brief)."""
    setup = await _setup(container)
    with pytest.raises(NotFound) as exc:
        await setup.svc.create(
            setup.alice,
            setup.dataset_id,
            "nieistnieje",
            content="x",
            important_keywords=[],
            questions=[],
            tag_kwd=[],
        )
    assert str(exc.value) == "you don't own the document nieistnieje"


async def test_list_returns_page(container: Container) -> None:
    """list → ChunkPage(total=2), kolejność po ordinal, doc.id == d (brief T3b)."""
    setup = await _setup(container)
    first = await _create(setup, "Ala ma kota")
    second = await _create(setup, "Inna treść")
    page = await _list(setup)
    assert page.total == TWO_CHUNKS
    assert len(page.chunks) == TWO_CHUNKS
    assert [c.id for c in page.chunks] == [first.id, second.id]
    assert page.doc.id == setup.doc_id


async def test_list_keywords_filter(container: Container) -> None:
    """list(keywords="kota") → 1 chunk (brief T3b)."""
    setup = await _setup(container)
    await _create(setup, "Ala ma kota")
    await _create(setup, "Inna treść")
    page = await _list(setup, keywords="kota")
    assert page.total == 1
    assert page.chunks[0].content == "Ala ma kota"


async def test_list_unknown_chunk_id(container: Container) -> None:
    """list(chunk_id="0000000000000000") → NotFound "Chunk not found: <A>/…" (brief)."""
    setup = await _setup(container)
    await _create(setup, "Ala ma kota")
    with pytest.raises(NotFound) as exc:
        await _list(setup, chunk_id="0000000000000000")
    assert str(exc.value) == f"Chunk not found: {setup.dataset_id}/0000000000000000"


async def test_get_existing_and_missing(container: Container) -> None:
    """get id1 → ChunkRecord; get "zzz" → NotFound "Chunk not found!" (brief T3b)."""
    setup = await _setup(container)
    first = await _create(setup, "Ala ma kota")
    chunk = await setup.svc.get(setup.alice, setup.dataset_id, setup.doc_id, first.id)
    assert chunk.id == first.id
    with pytest.raises(NotFound) as exc:
        await setup.svc.get(setup.alice, setup.dataset_id, setup.doc_id, "zzz")
    assert str(exc.value) == "Chunk not found!"


async def test_update_content_reembeds(container: Container) -> None:
    """update content → nowa treść i zmieniony wektor w chunk_vec_d1024 (brief T3b)."""
    setup = await _setup(container)
    first = await _create(setup, "Ala ma kota")
    before = await _vector_of(container, first.id)
    await _update(setup, first.id, {"content": "Nowa treść"})
    fresh = await setup.svc.get(setup.alice, setup.dataset_id, setup.doc_id, first.id)
    assert fresh.content == "Nowa treść"
    assert await _vector_of(container, first.id) != before


async def test_update_available_keeps_vector(container: Container) -> None:
    """update available → available False, wektor bez zmian (brief T3b)."""
    setup = await _setup(container)
    first = await _create(setup, "Ala ma kota")
    before = await _vector_of(container, first.id)
    await _update(setup, first.id, {"available": False})
    fresh = await setup.svc.get(setup.alice, setup.dataset_id, setup.doc_id, first.id)
    assert fresh.available is False
    assert await _vector_of(container, first.id) == before


async def test_update_blank_content(container: Container) -> None:
    """update content=" " → Conflict "`content` is required" (brief T3b)."""
    setup = await _setup(container)
    first = await _create(setup, "Ala ma kota")
    with pytest.raises(Conflict) as exc:
        await _update(setup, first.id, {"content": " "})
    assert str(exc.value) == "`content` is required"


async def test_update_missing_chunk(container: Container) -> None:
    """update "zzz" → NotFound "Can't find this chunk zzz" (brief T3b)."""
    setup = await _setup(container)
    await _create(setup, "Ala ma kota")
    with pytest.raises(NotFound) as exc:
        await _update(setup, "zzz", {})
    assert str(exc.value) == "Can't find this chunk zzz"


async def test_update_keywords_questions_tags(container: Container) -> None:
    """update keywords/questions/tag_kwd → kolumny keywords, questions, tags, embed_source."""
    setup = await _setup(container)
    first = await _create(setup, "Ala ma kota")
    await _update(
        setup,
        first.id,
        {"important_keywords": ["pies"], "questions": ["Kim jest Ala?"], "tag_kwd": ["t2"]},
    )
    fresh = await setup.svc.get(setup.alice, setup.dataset_id, setup.doc_id, first.id)
    assert fresh.keywords == ["pies"]
    assert fresh.questions == ["Kim jest Ala?"]
    assert fresh.tags == ["t2"]
    assert (
        await _scalar(container, "SELECT embed_source FROM chunks WHERE id = :i", i=first.id)
        == "questions"
    )


async def test_update_questions_only_embed_source(container: Container) -> None:
    """update questions=[] → embed_source wraca na "content" i pytań brak (C3.2)."""
    setup = await _setup(container)
    first = await _create(setup, "Ala ma kota", questions=["Cztery?"])
    await _update(setup, first.id, {"questions": []})
    assert (
        await _scalar(container, "SELECT embed_source FROM chunks WHERE id = :i", i=first.id)
        == "content"
    )
    fresh = await setup.svc.get(setup.alice, setup.dataset_id, setup.doc_id, first.id)
    assert fresh.questions == []


async def test_switch_sets_available(container: Container) -> None:
    """switch([id1, id2], True) → oba available True (brief T3b)."""
    setup = await _setup(container)
    first = await _create(setup, "Ala ma kota")
    second = await _create(setup, "Inna treść")
    await _update(setup, first.id, {"available": False})
    await setup.svc.switch(setup.alice, setup.dataset_id, setup.doc_id, [first.id, second.id], True)
    page = await _list(setup)
    assert all(chunk.available for chunk in page.chunks)


async def test_delete_partial_mismatch(container: Container) -> None:
    """delete([id1, "zzz"]) → Conflict „deleted chunks 1, expect 2”; id1 usunięty (brief)."""
    setup = await _setup(container)
    first = await _create(setup, "Ala ma kota")
    await _create(setup, "Inna treść")
    with pytest.raises(Conflict) as exc:
        await setup.svc.delete(
            setup.alice, setup.dataset_id, setup.doc_id, [first.id, "zzz"], False
        )
    assert str(exc.value) == "rm_chunk deleted chunks 1, expect 2"
    assert await _counter(container, "documents", setup.doc_id) == 1
    async with transaction(container.sessionmaker) as session:
        assert await chunks_repo.get_record(session, first.id) is None


async def test_delete_all(container: Container) -> None:
    """delete(None, True) → 1; chunk_count dokumentu i datasetu 0 (brief T3b)."""
    setup = await _setup(container)
    await _create(setup, "Ala ma kota")
    assert await setup.svc.delete(setup.alice, setup.dataset_id, setup.doc_id, None, True) == 1
    assert await _counter(container, "documents", setup.doc_id) == 0
    assert await _counter(container, "datasets", setup.dataset_id) == 0


async def test_delete_without_targets(container: Container) -> None:
    """delete(None, False) → 0 bez SQL (brief T3b, CHK:1199-1210)."""
    setup = await _setup(container)
    assert await setup.svc.delete(setup.alice, setup.dataset_id, setup.doc_id, None, False) == 0


async def test_delete_duplicate_ids_counted_once(container: Container) -> None:
    """delete([id1, id1]) → 1, oczekiwana liczba = liczba unikalnych id (C3.2)."""
    setup = await _setup(container)
    first = await _create(setup, "Ala ma kota")
    assert (
        await setup.svc.delete(
            setup.alice, setup.dataset_id, setup.doc_id, [first.id, first.id], False
        )
        == 1
    )


async def test_create_counters_via_repos(container: Container) -> None:
    """Po create świeży odczyt repozytoriami: documents i datasets zbieżne (C3.2)."""
    setup = await _setup(container)
    chunk = await _create(setup, "Ala ma kota")
    async with transaction(container.sessionmaker) as session:
        doc = await documents_repo.get(session, setup.doc_id)
        dataset = await datasets_repo.get_record(session, setup.dataset_id)
    assert doc is not None and doc.chunk_count == 1
    assert dataset is not None and dataset.chunk_count == 1
    assert chunk.token_count > 0
