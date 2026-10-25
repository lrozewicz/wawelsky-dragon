"""Testy kontenera wg kontraktu C8 — przykłady z briefu T3; llm/models z briefu T5 (C12)."""

from pathlib import Path

from app.core.config import Settings
from app.core.container import Container
from app.core.ids import UuidV7Generator
from app.core.timeutil import SystemClock
from app.llm.openai_gateway import OpenAIGateway
from app.llm.registry import ModelRegistry
from app.services.api_keys import ApiKeyService
from app.services.auth import AuthService
from app.services.auth_ratelimit import LoginGuard
from app.services.oidc import OidcService
from app.services.users import UserService
from app.storage.filesystem import FilesystemStorage
from app.storage.keys import StorageKey
from tests.fakes.clock import FrozenClock
from tests.fakes.ids import SeqIdGenerator

_FROZEN_MS = 1790157600000
_ID_LEN = 32


def test_container_defaults() -> None:
    c = Container(Settings(env="test"))
    assert isinstance(c.clock, SystemClock)
    assert isinstance(c.id_gen, UuidV7Generator)
    assert c.started is False


def test_container_injected_clock_and_ids() -> None:
    c = Container(Settings(env="test"), clock=FrozenClock(), id_gen=SeqIdGenerator())
    assert c.clock.now_ms() == _FROZEN_MS
    assert c.id_gen.new_id() == "00000000000000000000000000000001"
    assert len(c.id_gen.new_id()) == _ID_LEN


async def test_container_start_and_aclose() -> None:
    c = Container(Settings(env="test"))
    await c.start()
    assert c.started is True
    await c.aclose()
    assert c.started is False


async def test_container_db_resources() -> None:
    """Engine i sessionmaker: None przed start(), uzupełnione po start(), None po aclose (C4)."""
    settings = Settings(env="test", db_name="wawelsky")
    c = Container(settings)
    assert c.engine is None
    assert c.sessionmaker is None
    await c.start()
    assert c.engine is not None
    assert c.sessionmaker is not None
    assert c.engine.url.database == settings.db_name
    await c.aclose()
    assert c.engine is None
    assert c.sessionmaker is None
    assert c.started is False


def test_container_storage() -> None:
    """Storage tworzony w konstruktorze z storage_root, bez I/O (C4 z E1-3)."""
    c = Container(Settings(env="test", storage_root="/x"))
    assert isinstance(c.storage, FilesystemStorage)
    assert c.storage.local_path(StorageKey("files/a")) == Path("/x/files/a")


def test_container_storage_no_io(tmp_path: Path) -> None:
    """Konstruktor kontenera nie tworzy katalogów storage."""
    root = tmp_path / "data"
    Container(Settings(env="test", storage_root=str(root)))
    assert not root.exists()


async def test_container_llm_and_models_lifecycle() -> None:
    """llm/models: None przed start(), uzupełnione po start(), oba None po aclose (C12)."""
    c = Container(Settings(env="test"))
    assert c.llm is None
    assert c.models is None
    await c.start()
    assert isinstance(c.llm, OpenAIGateway)
    assert isinstance(c.models, ModelRegistry)
    await c.aclose()
    assert c.llm is None
    assert c.models is None


async def test_container_auth_services_lifecycle() -> None:
    """login_guard po start() (potrzebuje sessionmaker); users/api_keys/auth po start() (C11)."""
    c = Container(Settings(env="test"))
    assert c.login_guard is None
    assert c.users is None
    assert c.api_keys is None
    assert c.auth is None
    await c.start()
    assert isinstance(c.login_guard, LoginGuard)
    assert isinstance(c.users, UserService)
    assert isinstance(c.api_keys, ApiKeyService)
    assert isinstance(c.auth, AuthService)
    await c.aclose()
    assert c.login_guard is None
    assert c.users is None
    assert c.api_keys is None
    assert c.auth is None


async def test_container_oidc_lifecycle() -> None:
    """oidc: None przed start(), OidcService po start(), None po aclose (C10/C11)."""
    c = Container(Settings(env="test"))
    assert c.oidc is None
    await c.start()
    assert isinstance(c.oidc, OidcService)
    await c.aclose()
    assert c.oidc is None


async def test_container_aclose_order() -> None:
    """llm.aclose() PRZED engine.dispose() (C12)."""
    c = Container(Settings(env="test"))
    await c.start()
    order: list[str] = []

    async def fake_llm_aclose() -> None:
        order.append("llm")

    class DisposeSpy:
        """AsyncEngine ma __slots__ — zamiast podmiany metody podmieniamy cały engine."""

        def __init__(self) -> None:
            pass

        async def dispose(self) -> None:
            order.append("engine")

    assert c.llm is not None
    c.llm.aclose = fake_llm_aclose  # type: ignore[method-assign]
    c.engine = DisposeSpy()  # type: ignore[assignment]
    await c.aclose()
    assert order == ["llm", "engine"]
