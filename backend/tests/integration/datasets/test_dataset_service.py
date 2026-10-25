"""Testy DatasetService na prawdziwej MariaDB (brief T1a, kontrakt C1.2).

Każdy wiersz tabeli „wejście → wyjście" z briefu ma osobny test; komunikaty
dosłowne (weryfikacja stałych MSG_*).
"""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text

from app.core.container import Container
from app.core.error_codes import RetCode
from app.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.db.repositories import datasets as datasets_repo
from app.db.repositories import documents as documents_repo
from app.db.uow import transaction
from app.services.datasets import (
    DEFAULT_PARSER_CONFIG,
    DatasetListQuery,
    DatasetService,
)
from app.services.ingest import UploadSource
from app.storage.keys import dataset_prefix
from tests.integration.datasets.conftest import (
    TIME_MS,
    date_ms,
    exec_sql,
    principal,
    seed_default_models,
    seed_model,
    seed_user,
)

pytestmark = pytest.mark.db

EMBEDDING_DIM = 1024  # fake-embed-1024
OTHER_EMBEDDING_DIM = 768  # inny-embed
TOKEN_NUM_OVERRIDE = 128  # parser_config z briefu T1a
THRESHOLD_DEFAULT = 0.2  # DDL datasets.similarity_threshold DEFAULT 0.2
OWN_DATASETS = 2  # liczba datasetów Alice w testach delete_all / delete_many


def _query(**kwargs: object) -> DatasetListQuery:
    """DatasetListQuery(page=1, size=30, create_time, desc) z nadpisaniami."""
    values: dict = {"page": 1, "page_size": 30, "orderby": "create_time", "desc": True}
    values.update(kwargs)
    return DatasetListQuery(**values)


async def _record(container: Container, dataset_id: str) -> datasets_repo.DatasetRecord | None:
    """get_record w osobnej transakcji (odczyty testowe)."""
    async with transaction(container.sessionmaker) as session:
        return await datasets_repo.get_record(session, dataset_id)


async def _stream(*chunks: bytes) -> AsyncIterator[bytes]:
    """Pomocniczy strumień bajtów dla upload (wzór: tests/integration/ingest)."""
    for chunk in chunks:
        yield chunk


async def test_create_defaults_and_owner_nickname(container: Container) -> None:
    """create(" ds "): strip, defaults, domyślne modele, nickname właściciela (brief T1a)."""
    await seed_default_models(container.sessionmaker)
    user_id, email = await seed_user(container.sessionmaker)
    alice = principal(user_id, email)
    rec = await DatasetService(container).create(alice, name=" ds ")
    assert rec.name == "ds"
    assert rec.language == "English"
    assert rec.permission == "me"
    assert rec.chunk_method == "naive"
    assert rec.embedding_model == "fake-embed-1024"
    assert rec.embedding_dim == EMBEDDING_DIM
    assert rec.tenant_id == user_id
    assert rec.created_by == user_id
    assert rec.parser_config == {**DEFAULT_PARSER_CONFIG, "llm_id": "fake-chat"}
    assert rec.similarity_threshold == THRESHOLD_DEFAULT
    assert rec.owner_nickname == "Alice"
    assert rec.create_time == TIME_MS


async def test_create_deduplicates_name(container: Container) -> None:
    """create drugi raz z tą samą nazwą → ds(1) (brief T1a)."""
    await seed_default_models(container.sessionmaker)
    user_id, email = await seed_user(container.sessionmaker)
    alice = principal(user_id, email)
    svc = DatasetService(container)
    assert (await svc.create(alice, name="ds")).name == "ds"
    assert (await svc.create(alice, name="ds")).name == "ds(1)"


async def test_create_merges_parser_config(container: Container) -> None:
    """create: parser_config scalany z domyślnym (deep_merge, zagnieżdżony dict) (brief T1a)."""
    await seed_default_models(container.sessionmaker)
    user_id, email = await seed_user(container.sessionmaker)
    rec = await DatasetService(container).create(
        principal(user_id, email),
        name="p",
        parser_config={"chunk_token_num": 128, "parent_child": {"use_parent_child": True}},
    )
    assert rec.parser_config["chunk_token_num"] == TOKEN_NUM_OVERRIDE
    assert rec.parser_config["parent_child"] == {
        "children_delimiter": "\n",
        "use_parent_child": True,
    }
    assert rec.parser_config["llm_id"] == "fake-chat"  # reszta kluczy ze złota


async def test_create_unsupported_chunk_method(container: Container) -> None:
    """create(chunk_method='tag') → ValidationFailed 101 (brief T1a)."""
    await seed_default_models(container.sessionmaker)
    user_id, email = await seed_user(container.sessionmaker)
    with pytest.raises(ValidationFailed) as exc:
        await DatasetService(container).create(
            principal(user_id, email), name="t", chunk_method="tag"
        )
    assert exc.value.code == RetCode.ARGUMENT_ERROR
    assert str(exc.value) == "`chunk_method` tag is not supported by Wawelsky Dragon"


async def test_list_visibility_of_team(container: Container) -> None:
    """list(bob): prywatny dataset Alice niewidoczny; po permission='team' widoczny (brief)."""
    await seed_default_models(container.sessionmaker)
    alice_id, alice_email = await seed_user(container.sessionmaker)
    bob_id, bob_email = await seed_user(container.sessionmaker, nickname="Bob")
    alice = principal(alice_id, alice_email)
    bob = principal(bob_id, bob_email)
    rec = await DatasetService(container).create(alice, name="wspolny")
    assert await DatasetService(container).list(bob, _query()) == ([], 0)
    await exec_sql(
        container.sessionmaker,
        "UPDATE datasets SET permission = 'team' WHERE id = :id",
        id=rec.id,
    )
    rows, total = await DatasetService(container).list(bob, _query())
    assert total == 1
    assert [item.id for item in rows] == [rec.id]


async def test_list_by_name_and_missing_name(container: Container) -> None:
    """list(name='ds') → 1 rekord; name='brak' → NotFound 102 z komunikatem (brief T1a)."""
    await seed_default_models(container.sessionmaker)
    user_id, email = await seed_user(container.sessionmaker)
    alice = principal(user_id, email)
    svc = DatasetService(container)
    await svc.create(alice, name="ds")
    rows, total = await svc.list(alice, _query(name="ds"))
    assert total == 1 and rows[0].name == "ds"
    with pytest.raises(NotFound) as exc:
        await svc.list(alice, _query(name="brak"))
    assert exc.value.code == RetCode.DATA_ERROR
    assert str(exc.value) == f"User '{user_id}' lacks permission for dataset 'brak'"


async def test_get_foreign_private_dataset(container: Container) -> None:
    """get(bob, prywatny Alice) → PermissionDenied 108 'You don't own the dataset <id>.'"""
    await seed_default_models(container.sessionmaker)
    alice_id, alice_email = await seed_user(container.sessionmaker)
    bob_id, bob_email = await seed_user(container.sessionmaker, nickname="Bob")
    rec = await DatasetService(container).create(principal(alice_id, alice_email), name="ds")
    with pytest.raises(PermissionDenied) as exc:
        await DatasetService(container).get(principal(bob_id, bob_email), rec.id)
    assert exc.value.code == RetCode.PERMISSION_ERROR
    assert str(exc.value) == f"You don't own the dataset {rec.id}."


async def test_get_missing_dataset(container: Container) -> None:
    """get(alice, '0'*32) → NotFound 102 'User ... lacks permission for dataset '000…0''."""
    await seed_default_models(container.sessionmaker)
    user_id, email = await seed_user(container.sessionmaker)
    with pytest.raises(NotFound) as exc:
        await DatasetService(container).get(principal(user_id, email), "0" * 32)
    assert exc.value.code == RetCode.DATA_ERROR
    assert str(exc.value) == f"User '{user_id}' lacks permission for dataset '{'0' * 32}'"


async def test_update_empty_fields(container: Container) -> None:
    """update({}, ) → Conflict 102 'no properties were modified' (brief T1a)."""
    await seed_default_models(container.sessionmaker)
    user_id, email = await seed_user(container.sessionmaker)
    rec = await DatasetService(container).create(principal(user_id, email), name="ds")
    with pytest.raises(Conflict) as exc:
        await DatasetService(container).update(principal(user_id, email), rec.id, {})
    assert exc.value.code == RetCode.DATA_ERROR
    assert str(exc.value) == "no properties were modified"


async def test_update_name_taken_by_other(container: Container) -> None:
    """update(name='ds(1)') gdy istnieje inny ds(1) → Conflict (brief T1a)."""
    await seed_default_models(container.sessionmaker)
    user_id, email = await seed_user(container.sessionmaker)
    alice = principal(user_id, email)
    svc = DatasetService(container)
    first = await svc.create(alice, name="ds")
    await svc.create(alice, name="ds")  # → ds(1)
    with pytest.raises(Conflict) as exc:
        await svc.update(alice, first.id, {"name": "ds(1)"})
    assert str(exc.value) == "Dataset name 'ds(1)' already exists"


async def test_update_same_name_other_case(container: Container) -> None:
    """update(name='DS') tego samego datasetu (inna wielkość liter) → OK (brief T1a)."""
    await seed_default_models(container.sessionmaker)
    user_id, email = await seed_user(container.sessionmaker)
    alice = principal(user_id, email)
    rec = await DatasetService(container).create(alice, name="ds")
    fresh = await DatasetService(container).update(alice, rec.id, {"name": "DS"})
    assert fresh.name == "DS"


async def test_update_embedding_model_locked(container: Container) -> None:
    """update(embedding_model) przy chunk_count>0 → ValidationFailed 101 (brief T1a)."""
    await seed_default_models(container.sessionmaker)
    await seed_model(
        container.sessionmaker,
        "inny-embed",
        "embedding",
        dimension=OTHER_EMBEDDING_DIM,
        is_default=False,  # domyślny embedding już istnieje (uq_models_default_key)
    )
    user_id, email = await seed_user(container.sessionmaker)
    alice = principal(user_id, email)
    rec = await DatasetService(container).create(alice, name="ds")
    await exec_sql(
        container.sessionmaker,
        "UPDATE datasets SET chunk_count = 1 WHERE id = :id",
        id=rec.id,
    )
    with pytest.raises(ValidationFailed) as exc:
        await DatasetService(container).update(alice, rec.id, {"embedding_model": "inny-embed"})
    assert exc.value.code == RetCode.ARGUMENT_ERROR
    assert str(exc.value) == ("When chunk_num (1) > 0, embedding_model must remain fake-embed-1024")


async def test_update_foreign_dataset(container: Container) -> None:
    """update(bob, dataset Alice) → PermissionDenied 108 (brief T1a)."""
    await seed_default_models(container.sessionmaker)
    alice_id, alice_email = await seed_user(container.sessionmaker)
    bob_id, bob_email = await seed_user(container.sessionmaker, nickname="Bob")
    rec = await DatasetService(container).create(principal(alice_id, alice_email), name="ds")
    with pytest.raises(PermissionDenied) as exc:
        await DatasetService(container).update(principal(bob_id, bob_email), rec.id, {"name": "x"})
    assert exc.value.code == RetCode.PERMISSION_ERROR


async def test_update_chunk_method_config_and_embedding(container: Container) -> None:
    """update: dozwolony chunk_method, merge parser_config, zmiana embeddingu przy 0 chunków."""
    await seed_default_models(container.sessionmaker)
    await seed_model(
        container.sessionmaker,
        "inny-embed",
        "embedding",
        dimension=OTHER_EMBEDDING_DIM,
        is_default=False,
    )
    user_id, email = await seed_user(container.sessionmaker)
    alice = principal(user_id, email)
    rec = await DatasetService(container).create(alice, name="ds")
    fresh = await DatasetService(container).update(
        alice,
        rec.id,
        {
            "chunk_method": "book",
            "parser_config": {"chunk_token_num": TOKEN_NUM_OVERRIDE},
            "embedding_model": "inny-embed",
        },
    )
    assert fresh.chunk_method == "book"
    assert fresh.parser_config["chunk_token_num"] == TOKEN_NUM_OVERRIDE
    assert fresh.parser_config["layout_recognize"] == "DeepDOC"  # klucze bazowe nietknięte
    assert fresh.embedding_model == "inny-embed"
    assert fresh.embedding_dim == OTHER_EMBEDDING_DIM


async def test_update_unsupported_chunk_method(container: Container) -> None:
    """update(chunk_method='resume') → ValidationFailed 101 (kontrakt C1.2, obrona w głębi)."""
    await seed_default_models(container.sessionmaker)
    user_id, email = await seed_user(container.sessionmaker)
    alice = principal(user_id, email)
    rec = await DatasetService(container).create(alice, name="ds")
    with pytest.raises(ValidationFailed) as exc:
        await DatasetService(container).update(alice, rec.id, {"chunk_method": "resume"})
    assert exc.value.code == RetCode.ARGUMENT_ERROR
    assert str(exc.value) == "`chunk_method` resume is not supported by Wawelsky Dragon"


async def test_create_embedding_without_dimension(container: Container) -> None:
    """create: embedding bez dimension → sonda; model nieznany bramce → ValidationFailed (#2)."""
    await seed_model(container.sessionmaker, "bez-wymiaru", "embedding")  # dimension NULL
    user_id, email = await seed_user(container.sessionmaker)
    with pytest.raises(ValidationFailed) as exc:
        await DatasetService(container).create(principal(user_id, email), name="ds")
    assert "unavailable" in str(exc.value)
    assert "has no dimension" not in str(exc.value)


async def test_delete_empty_ids(container: Container) -> None:
    """delete(None, False) i delete([], False) → 0, nic nieusunięte (brief T1a, Q14)."""
    await seed_default_models(container.sessionmaker)
    user_id, email = await seed_user(container.sessionmaker)
    alice = principal(user_id, email)
    svc = DatasetService(container)
    rec = await svc.create(alice, name="ds")
    assert await svc.delete(alice, None, False) == 0
    assert await svc.delete(alice, [], False) == 0
    assert await _record(container, rec.id) is not None


async def test_delete_foreign_dataset(container: Container) -> None:
    """delete(bob, dataset Alice) → PermissionDenied 108; dataset istnieje (brief T1a)."""
    await seed_default_models(container.sessionmaker)
    alice_id, alice_email = await seed_user(container.sessionmaker)
    bob_id, bob_email = await seed_user(container.sessionmaker, nickname="Bob")
    rec = await DatasetService(container).create(principal(alice_id, alice_email), name="ds")
    with pytest.raises(PermissionDenied) as exc:
        await DatasetService(container).delete(principal(bob_id, bob_email), [rec.id], False)
    assert exc.value.code == RetCode.PERMISSION_ERROR
    assert await _record(container, rec.id) is not None


async def test_delete_missing_id(container: Container) -> None:
    """delete(['0'*32]) → PermissionDenied 108 'lacks permission for datasets: '000…0''."""
    await seed_default_models(container.sessionmaker)
    user_id, email = await seed_user(container.sessionmaker)
    with pytest.raises(PermissionDenied) as exc:
        await DatasetService(container).delete(principal(user_id, email), ["0" * 32], False)
    assert exc.value.code == RetCode.PERMISSION_ERROR
    assert str(exc.value) == f"User '{user_id}' lacks permission for datasets: '{'0' * 32}'"


async def test_delete_many_with_chat_link(container: Container) -> None:
    """delete([ds1, ds2]) → 2; wiersz w chat_datasets nie blokuje usunięcia (brief T1a)."""
    await seed_default_models(container.sessionmaker)
    user_id, email = await seed_user(container.sessionmaker)
    alice = principal(user_id, email)
    svc = DatasetService(container)
    ds1 = await svc.create(alice, name="ds1")
    ds2 = await svc.create(alice, name="ds2")
    async with transaction(container.sessionmaker) as session:
        await session.execute(
            text(
                "INSERT INTO chats (id, tenant_id, created_by, name, llm_id, prompt_config,"
                " create_time, create_date, update_time, update_date)"
                " VALUES (:id, :tenant, :tenant, 'Czat', '', '{}', :t, :d, :t, :d)"
            ),
            {"id": "d" * 32, "tenant": user_id, "t": TIME_MS, "d": date_ms(TIME_MS)},
        )
        await session.execute(
            text("INSERT INTO chat_datasets (chat_id, dataset_id, ordinal) VALUES (:c, :ds, 0)"),
            {"c": "d" * 32, "ds": ds1.id},
        )
    assert await svc.delete(alice, [ds1.id, ds2.id], False) == OWN_DATASETS
    assert await _record(container, ds1.id) is None
    assert await _record(container, ds2.id) is None


async def test_delete_all_only_own(container: Container) -> None:
    """delete(None, True): Alice usuwa swoje 2; dataset Boba (team) zostaje (brief T1a)."""
    await seed_default_models(container.sessionmaker)
    alice_id, alice_email = await seed_user(container.sessionmaker)
    bob_id, bob_email = await seed_user(container.sessionmaker, nickname="Bob")
    alice = principal(alice_id, alice_email)
    bob = principal(bob_id, bob_email)
    svc = DatasetService(container)
    await svc.create(alice, name="a1")
    await svc.create(alice, name="a2")
    foreign = await svc.create(bob, name="b1")
    await exec_sql(
        container.sessionmaker,
        "UPDATE datasets SET permission = 'team' WHERE id = :id",
        id=foreign.id,
    )
    assert await svc.delete(alice, None, True) == OWN_DATASETS
    assert await _record(container, foreign.id) is not None
    # Team Boba pozostaje widoczny na liście Alice (READ), ale nie został usunięty.
    rows, total = await svc.list(alice, _query())
    assert total == 1 and [item.id for item in rows] == [foreign.id]


async def test_delete_removes_documents_and_storage(container: Container) -> None:
    """delete datasetu z dokumentem: dokument i katalog files/<ds> znikają (brief T1a)."""
    await seed_default_models(container.sessionmaker)
    user_id, email = await seed_user(container.sessionmaker)
    alice = principal(user_id, email)
    svc = DatasetService(container)
    rec = await svc.create(alice, name="ds")
    doc = await container.ingest.upload(
        rec.id,
        UploadSource(stream=_stream(b"Ala ma kota.\n"), filename="notatka.txt"),
        created_by=user_id,
    )
    assert await svc.delete(alice, [rec.id], False) == 1
    async with transaction(container.sessionmaker) as session:
        assert await documents_repo.get(session, doc.id) is None
    assert await container.storage.exists(doc.location) is False
    assert not container.storage.local_path(dataset_prefix(rec.id)).exists()
