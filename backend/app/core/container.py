"""Kontener aplikacji — kompozycja zależności bez I/O (C8 z E0-2, C4 z E0-6 i E1-3, C12 z E1-2)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.ids import IdGenerator, UuidV7Generator
from app.core.timeutil import Clock, SystemClock
from app.db.engine import make_engine, make_sessionmaker
from app.llm.gateway import LLMGateway
from app.llm.openai_gateway import OpenAIGateway
from app.llm.registry import ModelRegistry
from app.services.access import AccessService
from app.services.api_keys import ApiKeyService
from app.services.audit import AuditService
from app.services.auth import AuthService
from app.services.auth_ratelimit import LoginGuard
from app.services.oidc import OidcService
from app.services.users import UserService
from app.storage.base import Storage
from app.storage.filesystem import FilesystemStorage

if TYPE_CHECKING:
    from app.services.chat import DbChatService
    from app.services.ingest import DocumentIngestService
    from app.services.retrieval import DbRetrievalService


class Container:
    """Trzyma ustawienia, zegar, generator ID, storage, engine, fabrykę sesji oraz llm/models.

    Konstruktor bez I/O; storage jest polem __init__ (K5 §1.4 — api nie tworzy katalogów).
    start()/aclose() tworzą i zamykają zasoby bazy (bez łączenia z nią) oraz bramkę LLM
    i rejestr modeli; aclose() zamyka llm PRZED engine.dispose() (C12).
    """

    def __init__(
        self,
        settings: Settings,
        *,
        clock: Clock | None = None,
        id_gen: IdGenerator | None = None,
    ) -> None:
        self.settings = settings
        self.clock: Clock = clock or SystemClock()
        self.id_gen: IdGenerator = id_gen or UuidV7Generator()
        self.storage: Storage = FilesystemStorage(Path(settings.storage_root))
        self.login_guard: LoginGuard | None = None
        self.engine: AsyncEngine | None = None
        self.sessionmaker: async_sessionmaker[AsyncSession] | None = None
        self.users: UserService | None = None
        self.api_keys: ApiKeyService | None = None
        self.access: AccessService | None = None
        self.audit: AuditService | None = None
        self.auth: AuthService | None = None
        self.oidc: OidcService | None = None
        self.llm: LLMGateway | None = None
        self.models: ModelRegistry | None = None
        self._ingest: DocumentIngestService | None = None
        self._retrieval: DbRetrievalService | None = None
        self._chat: DbChatService | None = None
        self.started = False

    async def start(self) -> None:
        """Tworzy engine, sessionmaker (bez łączenia z bazą), rejestr modeli i bramkę LLM."""
        engine = make_engine(self.settings)
        sessionmaker = make_sessionmaker(engine)
        self.engine = engine
        self.sessionmaker = sessionmaker
        # Limiter logowania potrzebuje sessionmaker (stan w tabeli `login_attempts`, 0007).
        login_guard = LoginGuard(self.settings.rate_limit_login, self.clock, sessionmaker)
        self.login_guard = login_guard
        self.models = ModelRegistry(sessionmaker, self.settings, self.clock, self.id_gen)
        self.users = UserService(sessionmaker, self.settings, self.clock, self.id_gen)
        self.api_keys = ApiKeyService(sessionmaker, self.settings, self.clock, self.id_gen)
        self.access = AccessService(sessionmaker, self.settings, self.clock)
        self.audit = AuditService(sessionmaker, self.settings, self.clock)
        self.auth = AuthService(sessionmaker, self.settings, self.clock, self.id_gen, login_guard)
        self.oidc = OidcService(
            self.settings,
            self.clock,
            self.id_gen,
            httpx.AsyncClient(timeout=10.0),
            self.users,
            sessionmaker,
        )
        self.llm = OpenAIGateway(self.settings, sessionmaker=sessionmaker, clock=self.clock)
        self.started = True

    @property
    def ingest(self) -> DocumentIngestService:
        """Leniwa usługa ingestii (C4): tworzy raz i zwraca tę samą instancję, bez I/O.

        Import wewnątrz właściwości — unika cyklu importów i ciężkiego ``app.parsing``
        przy starcie API.
        """
        if self._ingest is None:
            from app.services.ingest import DocumentIngestService  # noqa: PLC0415

            self._ingest = DocumentIngestService(self)
        return self._ingest

    @property
    def retrieval(self) -> DbRetrievalService:
        """Leniwa usługa retrievalu (M8): tworzy raz i zwraca tę samą instancję, bez I/O.

        Import wewnątrz właściwości — unika cyklu importów; zależności usługa czyta
        z kontenera dopiero w chwili wywołania.
        """
        if self._retrieval is None:
            from app.services.retrieval import DbRetrievalService  # noqa: PLC0415

            self._retrieval = DbRetrievalService(self)
        return self._retrieval

    @property
    def chat(self) -> DbChatService:
        """Leniwa usługa czatu (C11): tworzy raz i zwraca tę samą instancję, bez I/O.

        Import wewnątrz właściwości — unika cyklu importów; zależności usługa czyta
        z kontenera dopiero w chwili wywołania.
        """
        if self._chat is None:
            from app.services.chat import DbChatService  # noqa: PLC0415

            self._chat = DbChatService(self)
        return self._chat

    async def aclose(self) -> None:
        """Zamyka llm i oidc, potem engine (dispose), czyści zasoby i ustawia started."""
        if self.llm is not None:
            await self.llm.aclose()
        if self.oidc is not None:
            await self.oidc.aclose()
        if self.engine is not None:
            await self.engine.dispose()
        self.engine = None
        self.sessionmaker = None
        self.login_guard = None
        self.users = None
        self.api_keys = None
        self.access = None
        self.audit = None
        self.auth = None
        self.oidc = None
        self.llm = None
        self.models = None
        self.started = False
