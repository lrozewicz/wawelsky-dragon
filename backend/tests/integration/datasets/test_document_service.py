"""Testy DocumentService na prawdziwej MariaDB (brief T2a, kontrakt C2.2).

Wiersze tabeli „wejście → wyjście" z briefu mają osobne testy; komunikaty
dosłowne (weryfikacja stałych MSG_*). Alice i Bob; dataset A Alice
(permission="me"); pliki a.txt (b"hello") i b.txt wgrane przez usługę.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from sqlalchemy import text

from app.core.container import Container
from app.core.error_codes import RetCode
from app.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.db.repositories import documents as documents_repo
from app.db.uow import transaction
from app.domain.policy import Principal
from app.services.datasets import DatasetService
from app.services.documents import (
    DocumentListQuery,
    DocumentService,
    UnsupportedFileType,
)
from app.services.ingest import UploadSource
from tests.integration.datasets.conftest import count_sql, seed_default_models, seed_user

pytestmark = pytest.mark.db

TWO_DOCS = 2  # liczba dokumentów w setupie (a.txt, b.txt)
TOKEN_NUM_OVERRIDE = 128  # parser_config z briefu T2a


async def gen(data: bytes) -> AsyncIterator[bytes]:
    """Strumień bajtów dla upload (brief T2a)."""
    yield data


def _query(**kwargs: object) -> DocumentListQuery:
    """DocumentListQuery(page=1, size=30, create_time, desc) z nadpisaniami."""
    values: dict = {"page": 1, "page_size": 30, "orderby": "create_time", "desc": True}
    values.update(kwargs)
    return DocumentListQuery(**values)


@dataclass
class Setup:
    """Stan współdzielony testów (dane z tabeli briefu T2a)."""

    svc: DocumentService
    dataset_id: str
    doc_a_id: str
    doc_b_id: str
    alice: Principal


async def _setup(container: Container) -> Setup:
    """Alice + dataset A (permission=me) + dokumenty a.txt, b.txt przez usługę."""
    await seed_default_models(container.sessionmaker)
    alice_id, alice_email = await seed_user(container.sessionmaker)
    alice = Principal(
        user_id=alice_id,
        email=alice_email,
        is_superuser=False,
        is_service=False,
        auth_kind="jwt",
    )
    dataset = await DatasetService(container).create(alice, name="A")
    svc = DocumentService(container)
    docs = await svc.upload(
        alice,
        dataset.id,
        [
            UploadSource(stream=gen(b"hello"), filename="a.txt"),
            UploadSource(stream=gen(b"world"), filename="b.txt"),
        ],
    )
    return Setup(svc, dataset.id, docs[0].id, docs[1].id, alice)


async def _bob(container: Container) -> Principal:
    """Principal Boba (drugi użytkownik z briefu)."""
    bob_id, bob_email = await seed_user(container.sessionmaker, nickname="Bob")
    return Principal(
        user_id=bob_id,
        email=bob_email,
        is_superuser=False,
        is_service=False,
        auth_kind="jwt",
    )


async def _task_payload(container: Container, document_id: str) -> dict:
    """Payload_json zadania parse_document dokumentu (odczyt testowy)."""
    async with transaction(container.sessionmaker) as session:
        found = (
            (
                await session.execute(
                    text("SELECT payload FROM tasks WHERE document_id = :i"),
                    {"i": document_id},
                )
            )
            .scalars()
            .first()
        )
    assert found is not None
    return json.loads(str(found))


async def test_upload_first_document(container: Container) -> None:
    """upload a.txt → lista 1 DocumentRow, name == 'a.txt', run == '0' (brief T2a)."""
    await seed_default_models(container.sessionmaker)
    user_id, email = await seed_user(container.sessionmaker)
    user = Principal(
        user_id=user_id, email=email, is_superuser=False, is_service=False, auth_kind="jwt"
    )
    dataset = await DatasetService(container).create(user, name="A")
    rows = await DocumentService(container).upload(
        user, dataset.id, [UploadSource(stream=gen(b"hello"), filename="a.txt")]
    )
    assert len(rows) == 1
    assert rows[0].name == "a.txt"
    assert rows[0].run == "0"


async def test_upload_deduplicates_name(container: Container) -> None:
    """Drugi upload a.txt → name == 'a(1).txt' (brief T2a)."""
    setup = await _setup(container)
    rows = await setup.svc.upload(
        setup.alice, setup.dataset_id, [UploadSource(stream=gen(b"hi"), filename="a.txt")]
    )
    assert rows[0].name == "a(1).txt"


async def test_upload_unsupported_extension(container: Container) -> None:
    """upload x.exe → UnsupportedFileType, komunikat upstreamu (DOC:571, DEC-088 p. 4)."""
    setup = await _setup(container)
    with pytest.raises(UnsupportedFileType) as exc:
        await setup.svc.upload(
            setup.alice, setup.dataset_id, [UploadSource(stream=gen(b"xx"), filename="x.exe")]
        )
    assert exc.value.code == RetCode.ARGUMENT_ERROR
    assert str(exc.value) == "x.exe: This type of file has not been supported yet!"


async def test_upload_foreign_dataset(container: Container) -> None:
    """upload(bob, A) → PermissionDenied 108 (brief T2a)."""
    setup = await _setup(container)
    with pytest.raises(PermissionDenied) as exc:
        await setup.svc.upload(
            await _bob(container),
            setup.dataset_id,
            [UploadSource(stream=gen(b"xx"), filename="x.txt")],
        )
    assert exc.value.code == RetCode.PERMISSION_ERROR


async def test_list_returns_rows_with_nickname(container: Container) -> None:
    """list(page=1, size=30, create_time, desc) → ([(row, 'Alice'), …], 2) (brief T2a)."""
    setup = await _setup(container)
    rows, total = await setup.svc.list(setup.alice, setup.dataset_id, _query())
    assert total == TWO_DOCS
    assert {row.name for row, _ in rows} == {"a.txt", "b.txt"}
    assert {nickname for _, nickname in rows} == {"Alice"}


async def test_list_keywords_case_insensitive(container: Container) -> None:
    """list(keywords='A.') → tylko a.txt (LIKE bez wielkości liter) (brief T2a)."""
    setup = await _setup(container)
    rows, total = await setup.svc.list(setup.alice, setup.dataset_id, _query(keywords="A."))
    assert total == 1 and rows[0][0].name == "a.txt"


async def test_list_filter_runs_empty(container: Container) -> None:
    """list(runs=('3',)) → ([], 0) (brief T2a)."""
    setup = await _setup(container)
    assert await setup.svc.list(setup.alice, setup.dataset_id, _query(runs=("3",))) == ([], 0)


async def test_list_missing_document_id(container: Container) -> None:
    """list(document_id='nieistnieje') → Conflict "you don't own the document nieistnieje"."""
    setup = await _setup(container)
    with pytest.raises(Conflict) as exc:
        await setup.svc.list(setup.alice, setup.dataset_id, _query(document_id="nieistnieje"))
    assert exc.value.code == RetCode.DATA_ERROR
    assert str(exc.value) == "you don't own the document nieistnieje"


async def test_list_page_size_zero(container: Container) -> None:
    """list(page_size=0) → ([], 2) (brief T2a)."""
    setup = await _setup(container)
    assert await setup.svc.list(setup.alice, setup.dataset_id, _query(page_size=0)) == ([], 2)


async def test_get_own_other_dataset_and_foreign(container: Container) -> None:
    """get(alice, A, id_a) → wiersz; get(alice, B_alice, id_a) → NotFound; get(bob) → 108."""
    setup = await _setup(container)
    row = await setup.svc.get(setup.alice, setup.dataset_id, setup.doc_a_id)
    assert row.id == setup.doc_a_id
    other = await DatasetService(container).create(setup.alice, name="B")
    with pytest.raises(NotFound) as exc:
        await setup.svc.get(setup.alice, other.id, setup.doc_a_id)
    assert str(exc.value) == f"you don't own the document {setup.doc_a_id}"
    with pytest.raises(PermissionDenied) as exc:
        await setup.svc.get(await _bob(container), setup.dataset_id, setup.doc_a_id)
    assert exc.value.code == RetCode.PERMISSION_ERROR


async def test_open_file_returns_bytes(container: Container) -> None:
    """open_file → iterator; zebrane bajty == b'hello' (brief T2a)."""
    setup = await _setup(container)
    row, iterator = await setup.svc.open_file(setup.alice, setup.dataset_id, setup.doc_a_id)
    assert row.id == setup.doc_a_id
    collected = b"".join([chunk async for chunk in iterator])
    assert collected == b"hello"


async def test_update_name_and_enabled(container: Container) -> None:
    """update({'name': 'c.txt', 'enabled': False}) → name 'c.txt', enabled False (brief T2a)."""
    setup = await _setup(container)
    row = await setup.svc.update(
        setup.alice, setup.dataset_id, setup.doc_a_id, {"name": "c.txt", "enabled": False}
    )
    assert row.name == "c.txt"
    assert row.enabled is False


async def test_update_extension_change(container: Container) -> None:
    """update({'name': 'c.pdf'}) → ValidationFailed "The extension of file can't be changed"."""
    setup = await _setup(container)
    with pytest.raises(ValidationFailed) as exc:
        await setup.svc.update(setup.alice, setup.dataset_id, setup.doc_a_id, {"name": "c.pdf"})
    assert str(exc.value) == "The extension of file can't be changed"


async def test_update_unsupported_extension_name(container: Container) -> None:
    """update({'name': 'c.exe'}) → ValidationFailed(MSG_EXTENSION_CHANGE), nie komunikat suffixu."""
    setup = await _setup(container)
    with pytest.raises(ValidationFailed) as exc:
        await setup.svc.update(setup.alice, setup.dataset_id, setup.doc_a_id, {"name": "c.exe"})
    assert str(exc.value) == "The extension of file can't be changed"


async def test_update_name_taken(container: Container) -> None:
    """update({'name': 'b.txt'}) → Conflict "Duplicated document name in the same dataset."."""
    setup = await _setup(container)
    with pytest.raises(Conflict) as exc:
        await setup.svc.update(setup.alice, setup.dataset_id, setup.doc_a_id, {"name": "b.txt"})
    assert str(exc.value) == "Duplicated document name in the same dataset."


async def test_update_immutable_chunk_count(container: Container) -> None:
    """update({'chunk_count': 1}) → Conflict "can't change `chunk_count`" (brief T2a)."""
    setup = await _setup(container)
    with pytest.raises(Conflict) as exc:
        await setup.svc.update(setup.alice, setup.dataset_id, setup.doc_a_id, {"chunk_count": 1})
    assert str(exc.value) == "can't change `chunk_count`"


async def test_update_parser_config_merges(container: Container) -> None:
    """update({'parser_config': {'chunk_token_num': 128}}) → klucz nadpisany, reszta zachowana."""
    setup = await _setup(container)
    row = await setup.svc.update(
        setup.alice,
        setup.dataset_id,
        setup.doc_a_id,
        {"parser_config": {"chunk_token_num": TOKEN_NUM_OVERRIDE}},
    )
    assert row.parser_config["chunk_token_num"] == TOKEN_NUM_OVERRIDE
    assert row.parser_config["delimiter"] == "\n"  # pozostałe klucze zachowane
    assert row.parser_config["layout_recognize"] == "DeepDOC"


async def test_update_chunk_method_unsupported(container: Container) -> None:
    """update({'chunk_method': 'tag'}) → ValidationFailed z komunikatem C1.2."""
    setup = await _setup(container)
    with pytest.raises(ValidationFailed) as exc:
        await setup.svc.update(
            setup.alice, setup.dataset_id, setup.doc_a_id, {"chunk_method": "tag"}
        )
    assert str(exc.value) == "`chunk_method` tag is not supported by Wawelsky Dragon"


async def test_delete_neither(container: Container) -> None:
    """delete(None, False) → Conflict "should either provide doc ids or set delete_all(true)…"."""
    setup = await _setup(container)
    with pytest.raises(Conflict) as exc:
        await setup.svc.delete(setup.alice, setup.dataset_id, None, False)
    assert str(exc.value) == (
        f"should either provide doc ids or set delete_all(true), dataset: {setup.dataset_id}. "
    )


async def test_delete_both(container: Container) -> None:
    """delete([id_a], True) → Conflict "should not provide both doc ids and delete_all(true)…"."""
    setup = await _setup(container)
    with pytest.raises(Conflict) as exc:
        await setup.svc.delete(setup.alice, setup.dataset_id, [setup.doc_a_id], True)
    assert str(exc.value) == (
        f"should not provide both doc ids and delete_all(true), dataset: {setup.dataset_id}. "
    )


async def test_delete_foreign_id(container: Container) -> None:
    """delete([id_a, 'zzz'], False) → Conflict "…or Document not found: zzz"; nic nieusunięte."""
    setup = await _setup(container)
    with pytest.raises(Conflict) as exc:
        await setup.svc.delete(setup.alice, setup.dataset_id, [setup.doc_a_id, "zzz"], False)
    assert str(exc.value) == (
        f"These documents do not belong to dataset {setup.dataset_id} or Document not found: zzz"
    )
    # count_sql liczy WIERSZE wyniku — COUNT(*) ma zawsze 1 wiersz, więc odczyt po id.
    assert (
        await count_sql(
            container.sessionmaker,
            "SELECT id FROM documents WHERE dataset_id = :i",
            i=setup.dataset_id,
        )
        == TWO_DOCS
    )


async def test_delete_duplicate_ids(container: Container) -> None:
    """delete([id_a, id_a], False) → 1; wiersz dokumentu usunięty (brief T2a)."""
    setup = await _setup(container)
    assert (
        await setup.svc.delete(
            setup.alice, setup.dataset_id, [setup.doc_a_id, setup.doc_a_id], False
        )
        == 1
    )
    assert (
        await count_sql(
            container.sessionmaker,
            "SELECT id FROM documents WHERE id = :i",
            i=setup.doc_a_id,
        )
        == 0
    )


async def test_parse_missing_id(container: Container) -> None:
    """parse([id_a, 'zzz']) → Conflict "Documents not found: ['zzz']", id_a zlecony (DOC:1614)."""
    setup = await _setup(container)
    with pytest.raises(Conflict) as exc:
        await setup.svc.parse(setup.alice, setup.dataset_id, [setup.doc_a_id, "zzz"])
    assert str(exc.value) == "Documents not found: ['zzz']"
    async with transaction(container.sessionmaker) as session:
        row = await documents_repo.get(session, setup.doc_a_id)
    assert row is not None and row.run == "1"  # znane id parsowane mimo 102


async def test_parse_duplicate_id_reports_error(container: Container) -> None:
    """parse([id_a, id_a]) → (1, ['Duplicate document ids: <id_a>']) (DOC:1600-1602)."""
    setup = await _setup(container)
    count, errors = await setup.svc.parse(
        setup.alice, setup.dataset_id, [setup.doc_a_id, setup.doc_a_id]
    )
    assert count == 1
    assert errors == [f"Duplicate document ids: {setup.doc_a_id}"]


async def test_parse_enqueues_task(container: Container) -> None:
    """parse([id_a]) → (1, []); run == '1'; 1 wiersz w tasks dla id_a (brief T2a)."""
    setup = await _setup(container)
    assert await setup.svc.parse(setup.alice, setup.dataset_id, [setup.doc_a_id]) == (1, [])
    async with transaction(container.sessionmaker) as session:
        row = await documents_repo.get(session, setup.doc_a_id)
    assert row is not None and row.run == "1"
    assert (
        await count_sql(
            container.sessionmaker,
            "SELECT id FROM tasks WHERE document_id = :i",
            i=setup.doc_a_id,
        )
        == 1
    )
    payload = await _task_payload(container, setup.doc_a_id)
    assert payload["clear_existing"] is False  # run '0' → bez czyszczenia


async def test_parse_done_document_clears_existing(container: Container) -> None:
    """parse dokumentu z run='3' → enqueue_parse(clear_existing=True); nowe zadanie."""
    setup = await _setup(container)
    async with transaction(container.sessionmaker) as session:
        await session.execute(
            text("UPDATE documents SET run = '3' WHERE id = :i"), {"i": setup.doc_a_id}
        )
    assert await setup.svc.parse(setup.alice, setup.dataset_id, [setup.doc_a_id]) == (1, [])
    async with transaction(container.sessionmaker) as session:
        row = await documents_repo.get(session, setup.doc_a_id)
    assert row is not None and row.run == "1"
    assert (
        await count_sql(
            container.sessionmaker,
            "SELECT id FROM tasks WHERE document_id = :i",
            i=setup.doc_a_id,
        )
        == 1
    )
    payload = await _task_payload(container, setup.doc_a_id)
    assert payload["clear_existing"] is True  # DONE → z czyszczeniem istniejących chunków


async def test_stop_after_parse(container: Container) -> None:
    """stop([id_a]) po parse → (1, []) (brief T2a)."""
    setup = await _setup(container)
    await setup.svc.parse(setup.alice, setup.dataset_id, [setup.doc_a_id])
    assert await setup.svc.stop(setup.alice, setup.dataset_id, [setup.doc_a_id]) == (1, [])


async def test_stop_not_running(container: Container) -> None:
    """stop([id_b]) (run '0') → (0, [MSG_STOP_NOT_RUNNING]) (brief T2a)."""
    setup = await _setup(container)
    stopped, errors = await setup.svc.stop(setup.alice, setup.dataset_id, [setup.doc_b_id])
    assert (stopped, errors) == (
        0,
        ["Can't stop parsing document that has not started or already completed"],
    )


async def test_update_chunk_method_allowed(container: Container) -> None:
    """update({'chunk_method': 'book'}) → świeży wiersz z nową metodą (C2.2)."""
    setup = await _setup(container)
    row = await setup.svc.update(
        setup.alice, setup.dataset_id, setup.doc_a_id, {"chunk_method": "book"}
    )
    assert row.chunk_method == "book"


async def test_delete_all_documents(container: Container) -> None:
    """delete(None, True) → 2; dokumenty znikają (C2.2 delete_all)."""
    setup = await _setup(container)
    assert await setup.svc.delete(setup.alice, setup.dataset_id, None, True) == TWO_DOCS
    assert (
        await count_sql(
            container.sessionmaker,
            "SELECT id FROM documents WHERE dataset_id = :i",
            i=setup.dataset_id,
        )
        == 0
    )


async def test_delete_all_empty_dataset(container: Container) -> None:
    """delete_all przy datasecie bez dokumentów → 0 (C2.2, bez wołania ingest)."""
    await seed_default_models(container.sessionmaker)
    user_id, email = await seed_user(container.sessionmaker)
    user = Principal(
        user_id=user_id, email=email, is_superuser=False, is_service=False, auth_kind="jwt"
    )
    dataset = await DatasetService(container).create(user, name="pusty")
    assert await DocumentService(container).delete(user, dataset.id, None, True) == 0


async def test_list_missing_name(container: Container) -> None:
    """list(name='brak') → Conflict "you don't own the document brak" (C2.2)."""
    setup = await _setup(container)
    with pytest.raises(Conflict) as exc:
        await setup.svc.list(setup.alice, setup.dataset_id, _query(name="brak"))
    assert str(exc.value) == "you don't own the document brak"


async def test_concurrent_upload_recount_no_deadlock(container: Container) -> None:
    """20 równoległych uploadów do jednego datasetu → bez deadlocka 1213 (DEC-088 p. 3).

    ``documents.dataset_id`` ma FK do ``datasets`` (``fk_documents_dataset``), więc INSERT
    dokumentu bierze **S**-blokadę wiersza datasetu, a ``datasets_repo.recount`` chce na tym
    samym wierszu **X** — dwie równoległe transakcje kończyły konwersją blokad i
    ``OperationalError (1213, 'Deadlock found …')`` (przez HTTP: 6/20 uploadów `code 100`).
    """
    setup = await _setup(container)
    count = 20
    await asyncio.gather(
        *(
            setup.svc.upload(
                setup.alice,
                setup.dataset_id,
                [UploadSource(stream=gen(b"x"), filename=f"c{i}.txt")],
            )
            for i in range(count)
        )
    )
    async with transaction(container.sessionmaker) as session:
        total = (
            await session.execute(
                text("SELECT COUNT(*) FROM documents WHERE dataset_id = :i"),
                {"i": setup.dataset_id},
            )
        ).scalar_one()
        document_count = (
            await session.execute(
                text("SELECT document_count FROM datasets WHERE id = :i"),
                {"i": setup.dataset_id},
            )
        ).scalar_one()
    assert total == count + TWO_DOCS
    assert document_count == count + TWO_DOCS
