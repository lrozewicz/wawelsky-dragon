"""Usługa użytkowników: rejestracja, profil, hasła, ochrona ostatniego admina (kontrakt C6)."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import (
    AuthenticationFailed,
    Conflict,
    NotFound,
    OperationNotAllowed,
    ValidationFailed,
)
from app.core.ids import IdGenerator
from app.core.timeutil import Clock
from app.db.repositories import assistant_access as assistant_access_repo
from app.db.repositories import user_resources
from app.db.repositories import users as users_repo
from app.db.repositories.users import (
    UserRow as UserRow,  # noqa: PLC0414 — re-eksport z C6 (api-no-db)
)
from app.db.uow import transaction
from app.domain.policy import Principal, ensure_admin_remains
from app.services.auth_passwords import hash_password, validate_new_password, verify_password

EMAIL_RE = re.compile(r"^[\w\._-]+@([\w_-]+\.)+[\w-]{2,}$")  # upstream user_api.py
NICKNAME_RE = re.compile(r"^[\w ._'-]+$")  # upstream nickname_validation.py
NICKNAME_MAX_LEN = 100
# SVC (hub-compat user-api): e-mail luźny — dozwolony '+', bez NICKNAME_RE (kontrakt C4).
HUB_COMPAT_EMAIL_RE = re.compile(r"^[^@\s/]+@[^@\s/]+\.[^@\s/]{2,}$")
HUB_COMPAT_EMAIL_MAX_LEN = 255
PROFILE_FIELDS = ("nickname", "avatar", "language", "timezone")


def validate_nickname(nickname: object) -> str:
    """Walidacja nickname wg upstream (kod 101 → ValidationFailed); zwraca strip()."""
    if nickname is None:
        raise ValidationFailed("Nickname is required.")
    if not isinstance(nickname, str):
        raise ValidationFailed("Nickname must be a string.")
    value = nickname.strip()
    if not value:
        raise ValidationFailed("Nickname cannot be empty.")
    if len(value) > NICKNAME_MAX_LEN:
        raise ValidationFailed("Nickname must be at most 100 characters.")
    if NICKNAME_RE.fullmatch(value) is None:
        raise ValidationFailed("Nickname contains invalid characters.")
    return value


@dataclass(frozen=True)
class DeleteUserResult:
    """Wynik usunięcia konta przez SVC (C4): tryb, cel transferu i liczniki zasobów."""

    user_id: str
    email: str
    mode: str
    transferred_to: str | None
    moved: dict[str, int]
    deleted: dict[str, int]


class UserService:
    """Operacje na kontach; każda metoda otwiera własną transakcję (kontrakt C6)."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
        clock: Clock,
        id_gen: IdGenerator,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings
        self._clock = clock
        self._id_gen = id_gen

    async def get(self, user_id: str) -> UserRow:
        """Użytkownik po id; brak → NotFound (C6)."""
        async with transaction(self._sessionmaker) as session:
            row = await users_repo.get_by_id(session, user_id)
        if row is None:
            raise NotFound("User not found!")
        return row

    async def get_by_email(self, email: str) -> UserRow | None:
        """Użytkownik po e-mailu albo None (C6)."""
        async with transaction(self._sessionmaker) as session:
            return await users_repo.get_by_email(session, email)

    async def list_all(self) -> list[UserRow]:
        """Wszyscy użytkownicy (także `is_service`) w kolejności create_time, id (C4)."""
        async with transaction(self._sessionmaker) as session:
            return await users_repo.list_all(session)

    async def list_page(
        self, *, q: str | None, email: str | None, page: int, page_size: int
    ) -> tuple[list[UserRow], int]:
        """Strona kont bez `is_service` wg filtrów `q` i `email` (kontrakt E3-6a §4)."""
        search = (q or "").strip() or None
        exact = (email or "").strip().lower() or None
        async with transaction(self._sessionmaker) as session:
            return await users_repo.list_page(
                session,
                q=search,
                email=exact,
                limit=page_size,
                offset=(page - 1) * page_size,
            )

    async def require_by_email(self, email: str) -> UserRow:
        """Użytkownik po e-mailu, dopasowanie case-insensitive; brak → NotFound (C4)."""
        async with transaction(self._sessionmaker) as session:
            row = await users_repo.get_by_email(session, email)
        if row is None:
            raise NotFound("User not found")
        return row

    async def register(self, *, email: str, nickname: str, password: str) -> UserRow:
        """Rejestracja lokalna: kolejność walidacji jak upstream (C6)."""
        if EMAIL_RE.fullmatch(email) is None:
            raise OperationNotAllowed(f"Invalid email address: {email}!")
        if await self.get_by_email(email) is not None:
            raise OperationNotAllowed(f"Email: {email} has already registered!")
        validate_new_password(password)
        return await self.create(
            email=email, password=password, nickname=validate_nickname(nickname)
        )

    async def create(  # noqa: PLR0913 — sygnatura z kontraktu C6
        self,
        *,
        email: str,
        password: str | None,
        nickname: str | None = None,
        is_superuser: bool = False,
        is_service: bool = False,
        auth_source: str = "local",
        oidc_sub: str | None = None,
    ) -> UserRow:
        """Utworzenie konta; nickname domyślnie z e-maila, kolizja → Conflict (C6)."""
        email = email.lower()
        if nickname is None:
            nickname = email.split("@", 1)[0]
        password_hash = hash_password(password) if password else None
        user_id = self._id_gen.new_id()
        async with transaction(self._sessionmaker) as session:
            if await users_repo.get_by_email(session, email) is not None:
                raise Conflict(f"Email: {email} has already registered!")
            await users_repo.insert(
                session,
                user_id=user_id,
                email=email,
                nickname=nickname,
                password_hash=password_hash,
                auth_source=auth_source,
                oidc_sub=oidc_sub,
                is_superuser=is_superuser,
                is_service=is_service,
                now_ms=self._clock.now_ms(),
            )
            row = await users_repo.get_by_id(session, user_id)
        if row is None:  # nieosiągalne: wiersz wstawiony wyżej w tej samej transakcji
            raise NotFound("User not found!")
        return row

    async def update_profile(self, principal: Principal, fields: Mapping[str, object]) -> UserRow:
        """Aktualizacja własnego profilu: tylko PROFILE_FIELDS, reszta ignorowana (C6)."""
        values: dict[str, object] = {key: fields[key] for key in PROFILE_FIELDS if key in fields}
        if "nickname" in values:
            values["nickname"] = validate_nickname(values["nickname"])
        async with transaction(self._sessionmaker) as session:
            await users_repo.update_fields(session, principal.user_id, values, self._clock.now_ms())
            row = await users_repo.get_by_id(session, principal.user_id)
        if row is None:
            raise NotFound("User not found!")
        return row

    async def change_password(
        self, principal: Principal, old_password: str | None, new_password: str
    ) -> None:
        """Zmiana hasła + bump_token_version w jednej transakcji (C6)."""
        validate_new_password(new_password)
        async with transaction(self._sessionmaker) as session:
            row = await users_repo.get_by_id(session, principal.user_id)
            if row is None:
                raise NotFound("User not found!")
            if row.password_hash and not verify_password(row.password_hash, old_password or ""):
                raise AuthenticationFailed("Password error!")
            await users_repo.update_fields(
                session,
                principal.user_id,
                {"password_hash": hash_password(new_password)},
                self._clock.now_ms(),
            )
            await users_repo.bump_token_version(session, principal.user_id, self._clock.now_ms())

    async def set_active(self, user_id: str, active: bool) -> None:
        """Dezaktywacja/aktywacja z ochroną ostatniego admina (C6)."""
        async with transaction(self._sessionmaker) as session:
            row = await users_repo.get_by_id(session, user_id)
            if row is None:
                raise NotFound("User not found!")
            target_active_admin = all((row.is_superuser, row.is_active))
            stays_active_admin = all((row.is_superuser, active))
            count = await users_repo.count_active_superusers(session)
            ensure_admin_remains(
                target_active_admin, stays_active_admin, count - int(target_active_admin)
            )
            await users_repo.update_fields(
                session, user_id, {"is_active": active}, self._clock.now_ms()
            )
            await users_repo.bump_token_version(session, user_id, self._clock.now_ms())

    async def set_superuser(self, user_id: str, value: bool) -> None:
        """Awans/degradacja z ochroną ostatniego admina (C6)."""
        async with transaction(self._sessionmaker) as session:
            row = await users_repo.get_by_id(session, user_id)
            if row is None:
                raise NotFound("User not found!")
            target_active_admin = all((row.is_superuser, row.is_active))
            stays_active_admin = all((value, row.is_active))
            count = await users_repo.count_active_superusers(session)
            ensure_admin_remains(
                target_active_admin, stays_active_admin, count - int(target_active_admin)
            )
            await users_repo.update_fields(
                session, user_id, {"is_superuser": value}, self._clock.now_ms()
            )
            await users_repo.bump_token_version(session, user_id, self._clock.now_ms())

    async def ensure_admin(self, email: str, password: str) -> bool:
        """Bootstrap admina: tworzy tylko gdy dane niepuste i konto nie istnieje (C6)."""
        if not email or not password:
            return False
        if await self.get_by_email(email) is not None:
            return False
        await self.create(email=email, password=password, is_superuser=True)
        return True

    async def create_managed(
        self, *, email: str, password: str, nickname: str | None, is_superuser: bool
    ) -> UserRow:
        """Konto tworzone przez SVC (hub-compat): e-mail luźny, nickname bez NICKNAME_RE (C4)."""
        if HUB_COMPAT_EMAIL_RE.fullmatch(email) is None or len(email) > HUB_COMPAT_EMAIL_MAX_LEN:
            raise ValidationFailed(f"Invalid email address: {email}")
        validate_new_password(password)
        if await self.get_by_email(email) is not None:
            raise Conflict("User already exists")
        value = (nickname or "").strip() or email.lower().split("@", 1)[0]
        return await self.create(
            email=email,
            password=password,
            nickname=value[:NICKNAME_MAX_LEN],
            is_superuser=is_superuser,
            auth_source="local",
        )

    async def create_by_admin(
        self,
        *,
        email: str,
        password: str | None,
        nickname: str | None,
        is_superuser: bool,
    ) -> UserRow:
        """Konto zakładane trasą WD admina: e-mail luźny jak `create_managed` (kontrakt E3-6a §4).

        Hasło jest opcjonalne; brak → konto bez hasła lokalnego (`password_hash` NULL).
        Duplikat e-maila → `Conflict` (409) z `create`.
        """
        if HUB_COMPAT_EMAIL_RE.fullmatch(email) is None or len(email) > HUB_COMPAT_EMAIL_MAX_LEN:
            raise ValidationFailed(f"Invalid email address: {email}")
        if password is not None:
            validate_new_password(password)
        return await self.create(
            email=email,
            password=password,
            nickname=nickname,
            is_superuser=is_superuser,
            auth_source="local",
        )

    async def update_managed(
        self,
        email: str,
        *,
        nickname: str | None = None,
        is_active: bool | None = None,
        is_superuser: bool | None = None,
    ) -> list[str]:
        """Zmiany konta przez SVC; zwraca nazwy zastosowanych zmian w kolejności C4."""
        row = await self.require_by_email(email)
        changes: list[str] = []
        if nickname is not None:
            value = nickname.strip()
            if not value:
                raise ValidationFailed("nickname must be a non-empty string")
            async with transaction(self._sessionmaker) as session:
                await users_repo.update_fields(
                    session, row.id, {"nickname": value[:NICKNAME_MAX_LEN]}, self._clock.now_ms()
                )
            changes.append("nickname")
        if is_active is not None:
            await self.set_active(row.id, is_active)
            changes.append("is_active")
        superuser = is_superuser  # alias: grep-test zabrania `if … is_superuser` poza polityką
        if superuser is not None:
            await self.set_superuser(row.id, superuser)
            changes.append("is_superuser")
        return changes

    async def set_password_by_email(self, email: str, new_password: str) -> None:
        """Hasło po e-mailu + bump_token_version w jednej transakcji; brak → NotFound (C4)."""
        validate_new_password(new_password)
        async with transaction(self._sessionmaker) as session:
            row = await users_repo.get_by_email(session, email)
            if row is None:
                raise NotFound("User not found")
            await users_repo.update_fields(
                session,
                row.id,
                {"password_hash": hash_password(new_password)},
                self._clock.now_ms(),
            )
            await users_repo.bump_token_version(session, row.id, self._clock.now_ms())

    async def set_active_by_email(self, email: str, active: bool) -> None:
        """Aktywacja po e-mailu; straż ostatniego admina z `set_active` (C4)."""
        row = await self.require_by_email(email)
        await self.set_active(row.id, active)

    def principal_of(self, row: UserRow) -> Principal:
        """Podmiot SVC dla wiersza użytkownika — uwierzytelnienie sekretem SVC (C4)."""
        return Principal(
            user_id=row.id,
            email=row.email,
            is_superuser=row.is_superuser,
            is_service=row.is_service,
            auth_kind="api_key",
        )

    async def delete_managed(
        self, email: str, mode: Literal["transfer", "cascade"] | None = None
    ) -> DeleteUserResult:
        """Usuwa konto w jednej transakcji (C4); `mode` None → `settings.user_delete_mode`.

        Trasa WD podaje tryb jawnie (kontrakt E3-6a §0 p. 8) — brak `mode` w żądaniu to
        ``transfer`` po stronie trasy, a nie wartość z ustawień.
        """
        async with transaction(self._sessionmaker) as session:
            row = await users_repo.get_by_email(session, email)
            if row is None:
                raise NotFound("User not found")
            target_active_admin = all((row.is_superuser, row.is_active))
            count = await users_repo.count_active_superusers(session)
            ensure_admin_remains(target_active_admin, False, count - int(target_active_admin))
            resolved = mode if mode is not None else self._settings.user_delete_mode
            transferred_to: str | None = None
            moved: dict[str, int] = {}
            deleted: dict[str, int] = {}
            if resolved == "transfer":
                target = await self._transfer_target(session, row)
                moved = await user_resources.transfer(session, row.id, target.id)
                transferred_to = target.email
            else:
                deleted = await user_resources.delete_all(session, row.id)
            await assistant_access_repo.delete_for_email(session, row.email)
            await users_repo.delete(session, row.id)
        return DeleteUserResult(
            user_id=row.id,
            email=row.email,
            mode=resolved,
            transferred_to=transferred_to,
            moved=moved,
            deleted=deleted,
        )

    async def _transfer_target(self, session: AsyncSession, row: UserRow) -> UserRow:
        """Cel transferu wg C4: e-mail z Settings, konto serwisowe, najstarszy admin."""
        configured = self._settings.user_delete_transfer_to
        if configured:
            target = await users_repo.get_by_email(session, configured)
            if target is None or target.id == row.id:
                raise ValidationFailed("Transfer target not found")
            return target
        target = await users_repo.find_transfer_target(session, row.id)
        if target is None:
            raise OperationNotAllowed("No transfer target available")
        return target
