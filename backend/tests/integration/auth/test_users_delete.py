"""Testy usuwania konta przez SVC (brief T4b, kontrakt C4) — tryby transfer i cascade."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import Conflict, NotFound, OperationNotAllowed, ValidationFailed
from app.core.timeutil import from_ms
from app.db.uow import transaction
from app.services.api_keys import ApiKeyService
from app.services.users import DeleteUserResult, UserService
from tests.fakes.clock import FrozenClock
from tests.fakes.ids import SeqIdGenerator

pytestmark = pytest.mark.db

PASSWORD = "Sup3r-secret-pw"  # noqa: S105 — celowa atrapa hasła w teście
TIME_MS = 1790157600000
LAST_ADMIN_MESSAGE = r"^The last active administrator cannot be deactivated or demoted\.$"

_INSERT_DATASET = text(
    "INSERT INTO datasets (id, tenant_id, created_by, name, language, embedding_model,"
    " embedding_dim, create_time, create_date, update_time, update_date)"
    " VALUES (:id, :tenant, :tenant, :name, 'Polish', 'fake-embed-1024', 1024,"
    " :time_ms, :date, :time_ms, :date)"
)
_INSERT_CHAT = text(
    "INSERT INTO chats (id, tenant_id, created_by, name, llm_id, prompt_config,"
    " create_time, create_date, update_time, update_date)"
    " VALUES (:id, :tenant, :tenant, :name, 'fake-chat', '{}', :time_ms, :date, :time_ms, :date)"
)
_INSERT_FILE = text(
    "INSERT INTO files (id, tenant_id, created_by, name, type, size,"
    " create_time, create_date, update_time, update_date)"
    " VALUES (:id, :tenant, :tenant, :name, 'doc', 0, :time_ms, :date, :time_ms, :date)"
)
_INSERT_GRANT = text(
    "INSERT INTO assistant_access (email, chat_id, created_by, created_at)"
    " VALUES (:email, :chat_id, NULL, :time_ms)"
)
_INSERT_CHAT_DATASET = text(
    "INSERT INTO chat_datasets (chat_id, dataset_id, ordinal) VALUES (:chat_id, :dataset_id, 0)"
)


def _service(settings: Settings, sm: async_sessionmaker[AsyncSession]) -> UserService:
    """Usługa na podanych ustawieniach (tryb usuwania ustawiany przez `model_copy`)."""
    return UserService(sm, settings, FrozenClock(), SeqIdGenerator())


@pytest.fixture
def svc(sm: async_sessionmaker[AsyncSession], auth_settings: Settings) -> UserService:
    return _service(auth_settings, sm)


@pytest.fixture
def keys_svc(sm: async_sessionmaker[AsyncSession], auth_settings: Settings) -> ApiKeyService:
    return ApiKeyService(sm, auth_settings, FrozenClock(), SeqIdGenerator())


async def _seed_dataset(
    sm: async_sessionmaker[AsyncSession], tenant_id: str, name: str = "Korpus"
) -> str:
    """Wstawia dataset właściciela; zwraca id."""
    dataset_id = uuid.uuid4().hex
    async with transaction(sm) as session:
        await session.execute(
            _INSERT_DATASET,
            {
                "id": dataset_id,
                "tenant": tenant_id,
                "name": name,
                "time_ms": TIME_MS,
                "date": from_ms(TIME_MS).replace(tzinfo=None),
            },
        )
    return dataset_id


async def _seed_chat(sm: async_sessionmaker[AsyncSession], tenant_id: str, name: str) -> str:
    """Wstawia czat właściciela; zwraca id."""
    chat_id = uuid.uuid4().hex
    async with transaction(sm) as session:
        await session.execute(
            _INSERT_CHAT,
            {
                "id": chat_id,
                "tenant": tenant_id,
                "name": name,
                "time_ms": TIME_MS,
                "date": from_ms(TIME_MS).replace(tzinfo=None),
            },
        )
    return chat_id


async def _seed_file(sm: async_sessionmaker[AsyncSession], tenant_id: str, name: str) -> str:
    """Wstawia plik właściciela; zwraca id."""
    file_id = uuid.uuid4().hex
    async with transaction(sm) as session:
        await session.execute(
            _INSERT_FILE,
            {
                "id": file_id,
                "tenant": tenant_id,
                "name": name,
                "time_ms": TIME_MS,
                "date": from_ms(TIME_MS).replace(tzinfo=None),
            },
        )
    return file_id


async def _link(sm: async_sessionmaker[AsyncSession], chat_id: str, dataset_id: str) -> None:
    """Wiąże czat z datasetem (FK `chat_datasets.dataset_id` jest RESTRICT)."""
    async with transaction(sm) as session:
        await session.execute(_INSERT_CHAT_DATASET, {"chat_id": chat_id, "dataset_id": dataset_id})


async def _grant(sm: async_sessionmaker[AsyncSession], email: str, chat_id: str) -> None:
    """Przyznaje e-mailowi dostęp do czatu (FK assistant_access.chat_id)."""
    async with transaction(sm) as session:
        await session.execute(
            _INSERT_GRANT, {"email": email.lower(), "chat_id": chat_id, "time_ms": TIME_MS}
        )


async def _scalar(sm: async_sessionmaker[AsyncSession], sql: str, **params: object) -> int:
    """Pojedyncza wartość liczbowa zapytania pomocniczego testu."""
    async with transaction(sm) as session:
        return int((await session.execute(text(sql), params)).scalar_one())


async def _owner_of(sm: async_sessionmaker[AsyncSession], table: str, row_id: str) -> str | None:
    """`tenant_id` wiersza w tabeli zasobów; None gdy wiersza nie ma."""
    # Nazwa tabeli pochodzi z literałów w tym pliku (bez wejścia użytkownika).
    sql = f"SELECT tenant_id FROM {table} WHERE id = :row_id"  # noqa: S608
    async with transaction(sm) as session:
        return (await session.execute(text(sql), {"row_id": row_id})).scalar_one_or_none()


async def test_delete_managed_example_from_brief(
    svc: UserService,
    keys_svc: ApiKeyService,
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """Przykład z briefu: transfer na konto serwisowe przenosi zasoby i czyści klucze/granty."""
    u1 = await svc.create_managed(
        email="u1@x.pl", password=PASSWORD, nickname="U1", is_superuser=False
    )
    s1 = await svc.create(email="svc1@x.pl", password=None, is_service=True)
    await _seed_dataset(sm, u1.id)
    chat1 = await _seed_chat(sm, u1.id, "Czat 1")
    chat2 = await _seed_chat(sm, u1.id, "Czat 2")
    await _grant(sm, "u1@x.pl", chat1)
    await keys_svc.create(svc.principal_of(u1))

    result = await svc.delete_managed("U1@X.pl")

    assert result == DeleteUserResult(
        user_id=u1.id,
        email="u1@x.pl",
        mode="transfer",
        transferred_to="svc1@x.pl",
        moved={"datasets": 1, "chats": 2, "files": 0},
        deleted={},
    )
    assert await _owner_of(sm, "chats", chat1) == s1.id
    assert await _owner_of(sm, "chats", chat2) == s1.id
    assert await _scalar(sm, "SELECT COUNT(*) FROM datasets WHERE tenant_id = :u", u=u1.id) == 0
    assert await _scalar(sm, "SELECT COUNT(*) FROM api_keys WHERE user_id = :u", u=u1.id) == 0
    assert (
        await _scalar(sm, "SELECT COUNT(*) FROM assistant_access WHERE email = :e", e="u1@x.pl")
        == 0
    )
    assert await svc.get_by_email("u1@x.pl") is None


async def test_delete_managed_transfers_files(
    svc: UserService, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Transfer obejmuje też pliki (`files.tenant_id`)."""
    u1 = await svc.create_managed(
        email="u1@x.pl", password=PASSWORD, nickname=None, is_superuser=False
    )
    s1 = await svc.create(email="svc1@x.pl", password=None, is_service=True)
    file_id = await _seed_file(sm, u1.id, "notatka.txt")

    result = await svc.delete_managed("u1@x.pl")

    assert result.moved == {"datasets": 0, "chats": 0, "files": 1}
    assert await _owner_of(sm, "files", file_id) == s1.id


async def test_delete_managed_transfer_to_from_settings(
    sm: async_sessionmaker[AsyncSession], auth_settings: Settings
) -> None:
    """Niepuste `user_delete_transfer_to` ma pierwszeństwo przed kontem serwisowym (C4)."""
    base = _service(auth_settings, sm)
    await base.create(email="svc1@x.pl", password=None, is_service=True)
    await base.create_managed(
        email="target@x.pl", password=PASSWORD, nickname="T", is_superuser=False
    )
    await base.create_managed(email="u1@x.pl", password=PASSWORD, nickname=None, is_superuser=False)
    settings = auth_settings.model_copy(update={"user_delete_transfer_to": "TARGET@x.pl"})

    result = await _service(settings, sm).delete_managed("u1@x.pl")

    assert result.transferred_to == "target@x.pl"


async def test_delete_managed_transfer_to_missing_target(
    sm: async_sessionmaker[AsyncSession], auth_settings: Settings
) -> None:
    """Wskazany cel nie istnieje → ValidationFailed i konto zostaje (C4 reguła a)."""
    base = _service(auth_settings, sm)
    await base.create_managed(email="u1@x.pl", password=PASSWORD, nickname=None, is_superuser=False)
    settings = auth_settings.model_copy(update={"user_delete_transfer_to": "brak@x.pl"})

    with pytest.raises(ValidationFailed, match=r"^Transfer target not found$"):
        await _service(settings, sm).delete_managed("u1@x.pl")
    assert await base.get_by_email("u1@x.pl") is not None


async def test_delete_managed_transfer_to_self(
    sm: async_sessionmaker[AsyncSession], auth_settings: Settings
) -> None:
    """Cel transferu wskazujący na usuwanego użytkownika jest błędem (C4 reguła a)."""
    base = _service(auth_settings, sm)
    await base.create_managed(email="u1@x.pl", password=PASSWORD, nickname=None, is_superuser=False)
    settings = auth_settings.model_copy(update={"user_delete_transfer_to": "u1@x.pl"})

    with pytest.raises(ValidationFailed, match=r"^Transfer target not found$"):
        await _service(settings, sm).delete_managed("u1@x.pl")


async def test_delete_managed_fallback_to_oldest_admin(
    svc: UserService, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Brak konta serwisowego → najstarszy aktywny admin inny niż usuwany (C4 reguła c)."""
    admin1 = await svc.create_managed(
        email="admin1@x.pl", password=PASSWORD, nickname="A1", is_superuser=True
    )
    u1 = await svc.create_managed(
        email="u1@x.pl", password=PASSWORD, nickname=None, is_superuser=False
    )
    chat_id = await _seed_chat(sm, u1.id, "Czat")

    result = await svc.delete_managed("u1@x.pl")

    assert result.transferred_to == "admin1@x.pl"
    assert await _owner_of(sm, "chats", chat_id) == admin1.id


async def test_delete_managed_no_transfer_target(svc: UserService) -> None:
    """Bez serwisu i bez innego admina nie ma na kogo przenieść zasobów (C4 reguła d)."""
    await svc.create_managed(email="u1@x.pl", password=PASSWORD, nickname=None, is_superuser=False)

    with pytest.raises(OperationNotAllowed, match=r"^No transfer target available$"):
        await svc.delete_managed("u1@x.pl")


async def test_delete_managed_name_conflict_rolls_back(
    svc: UserService, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Kolizja nazwy datasetu u celu → Conflict, cała transakcja wycofana (C4)."""
    s1 = await svc.create(email="svc1@x.pl", password=None, is_service=True)
    u1 = await svc.create_managed(
        email="u1@x.pl", password=PASSWORD, nickname=None, is_superuser=False
    )
    await _seed_dataset(sm, s1.id, name="Korpus")
    dataset_id = await _seed_dataset(sm, u1.id, name="Korpus")

    message = r"^Cannot transfer resources: name conflict with target account$"
    with pytest.raises(Conflict, match=message):
        await svc.delete_managed("u1@x.pl")

    assert await svc.get_by_email("u1@x.pl") is not None
    assert await _owner_of(sm, "datasets", dataset_id) == u1.id


async def test_delete_managed_cascade_removes_resources(
    sm: async_sessionmaker[AsyncSession], auth_settings: Settings
) -> None:
    """Tryb `cascade` usuwa datasety, czaty i pliki użytkownika (C4).

    Czat wskazuje dataset (FK RESTRICT), więc kasowanie musi iść od czatów.
    """
    svc = _service(auth_settings.model_copy(update={"user_delete_mode": "cascade"}), sm)
    u1 = await svc.create_managed(
        email="u1@x.pl", password=PASSWORD, nickname=None, is_superuser=False
    )
    dataset_id = await _seed_dataset(sm, u1.id)
    chat_id = await _seed_chat(sm, u1.id, "Czat")
    await _link(sm, chat_id, dataset_id)
    await _seed_file(sm, u1.id, "notatka.txt")

    result = await svc.delete_managed("u1@x.pl")

    assert result.mode == "cascade"
    assert result.transferred_to is None
    assert result.moved == {}
    assert result.deleted == {"chats": 1, "datasets": 1, "files": 1}
    assert await _scalar(sm, "SELECT COUNT(*) FROM datasets WHERE tenant_id = :u", u=u1.id) == 0
    assert await _scalar(sm, "SELECT COUNT(*) FROM chats WHERE tenant_id = :u", u=u1.id) == 0
    assert await _scalar(sm, "SELECT COUNT(*) FROM files WHERE tenant_id = :u", u=u1.id) == 0
    assert (
        await _scalar(sm, "SELECT COUNT(*) FROM chat_datasets WHERE chat_id = :c", c=chat_id) == 0
    )
    assert await svc.get_by_email("u1@x.pl") is None


async def test_delete_managed_cascade_keeps_other_accounts(
    sm: async_sessionmaker[AsyncSession], auth_settings: Settings
) -> None:
    """`cascade` nie rusza zasobów innych kont ani grantów innych e-maili."""
    svc = _service(auth_settings.model_copy(update={"user_delete_mode": "cascade"}), sm)
    u1 = await svc.create_managed(
        email="u1@x.pl", password=PASSWORD, nickname=None, is_superuser=False
    )
    u2 = await svc.create_managed(
        email="u2@x.pl", password=PASSWORD, nickname=None, is_superuser=False
    )
    await _seed_dataset(sm, u1.id)
    other_dataset = await _seed_dataset(sm, u2.id, name="Inny")
    other_chat = await _seed_chat(sm, u2.id, "Czat U2")
    await _grant(sm, "u2@x.pl", other_chat)

    await svc.delete_managed("u1@x.pl")

    assert await _owner_of(sm, "datasets", other_dataset) == u2.id
    assert await _scalar(sm, "SELECT COUNT(*) FROM chats WHERE tenant_id = :u", u=u2.id) == 1
    assert (
        await _scalar(sm, "SELECT COUNT(*) FROM assistant_access WHERE email = :e", e="u2@x.pl")
        == 1
    )


async def test_delete_managed_last_superuser_raises(
    svc: UserService, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Ostatni aktywny superuser nie może zostać usunięty (C4 krok 2)."""
    await svc.create_managed(
        email="root@x.pl", password=PASSWORD, nickname="Root", is_superuser=True
    )

    with pytest.raises(OperationNotAllowed, match=LAST_ADMIN_MESSAGE):
        await svc.delete_managed("root@x.pl")

    assert await svc.get_by_email("root@x.pl") is not None


async def test_delete_managed_superuser_with_other_admin(svc: UserService) -> None:
    """Superuser przechodzi, gdy zostaje inny aktywny admin (C4 krok 2)."""
    await svc.create_managed(email="a1@x.pl", password=PASSWORD, nickname="A1", is_superuser=True)
    await svc.create_managed(email="a2@x.pl", password=PASSWORD, nickname="A2", is_superuser=True)

    result = await svc.delete_managed("a2@x.pl")

    assert result.transferred_to == "a1@x.pl"
    assert await svc.get_by_email("a2@x.pl") is None


async def test_delete_managed_unknown_email(svc: UserService) -> None:
    """Nieznany e-mail → NotFound (C4 krok 1)."""
    with pytest.raises(NotFound, match=r"^User not found$"):
        await svc.delete_managed("brak@x.pl")
