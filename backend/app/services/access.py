"""Usługa grantów dostępu do czatów (kontrakt C3) — zastępowanie, nadanie, odebranie."""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import ValidationFailed
from app.core.timeutil import Clock
from app.db.repositories import assistant_access as access_repo
from app.db.uow import transaction


@dataclass(frozen=True)
class AccessEntry:
    """Pojedynczy grant czatu dla e-maila (C3); ``created_at`` to ms epoki (E3-6a §4)."""

    dialog_id: str
    created_by: str | None
    created_at: int


def _dedupe(chat_ids: Sequence[str]) -> list[str]:
    """Usuwa duplikaty z zachowaniem kolejności wejścia (C3)."""
    return list(dict.fromkeys(chat_ids))


class AccessService:
    """Granty dostępu do czatów; brak wiersza przy `revoke` nie jest błędem (C3)."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
        clock: Clock,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings
        self._clock = clock

    async def get(self, email: str) -> list[AccessEntry]:
        """Granty e-maila; dla e-maila bez konta zwraca pustą listę (C3)."""
        async with transaction(self._sessionmaker) as session:
            rows = await access_repo.list_for_email(session, email)
        return [
            AccessEntry(dialog_id=row.chat_id, created_by=row.created_by, created_at=row.created_at)
            for row in rows
        ]

    async def replace(self, email: str, chat_ids: Sequence[str], actor: str | None) -> int:
        """Zastępuje cały zbiór grantów; zwraca liczbę unikalnych czatów (C3).

        Kolejność: deduplikacja, walidacja istniejących czatów, potem jedna transakcja
        delete_for_email + insert_many (`created_by` ustawiany także dla dotychczasowych).
        """
        unique = _dedupe(chat_ids)
        async with transaction(self._sessionmaker) as session:
            existing = await access_repo.existing_chat_ids(session, unique)
            missing = [chat_id for chat_id in unique if chat_id not in existing]
            if missing:
                raise ValidationFailed(f"Unknown dialog_ids: {', '.join(missing)}")
            await access_repo.delete_for_email(session, email)
            await access_repo.insert_many(
                session, email, unique, actor or None, self._clock.now_ms()
            )
        return len(unique)

    async def grant(self, email: str, chat_id: str, actor: str | None) -> None:
        """Nadaje grant; istniejący wiersz zostaje bez zmian (INSERT IGNORE, C3)."""
        async with transaction(self._sessionmaker) as session:
            existing = await access_repo.existing_chat_ids(session, [chat_id])
            if chat_id not in existing:
                raise ValidationFailed(f"Unknown dialog_ids: {chat_id}")
            await access_repo.insert_ignore(
                session, email, chat_id, actor or None, self._clock.now_ms()
            )

    async def revoke(self, email: str, chat_id: str) -> None:
        """Odbiera grant; brak wiersza to nie błąd (C3)."""
        async with transaction(self._sessionmaker) as session:
            await access_repo.delete_one(session, email, chat_id)
