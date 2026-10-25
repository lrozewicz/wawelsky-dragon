"""Repozytorium tabeli `web_search_providers` (CONTRACT E6-3f §C2, K2 §6, K18 §5).

SQL przez ``text()``, bez ``commit``/``rollback`` — transakcję otwiera ``app.db.uow.transaction``.
``id`` i ``created_by`` mają kolację `ascii_bin`, a parametry z żądania są w `utf8mb4_*`:
porównania parametru z kolumną ``CHAR(32)`` idą przez ``CAST(:x AS BINARY)`` (DEC-087/090).
``config`` trzymamy jako JSON: MariaDB zwraca go jako ``str``, dekodujemy przy odczycie.
Klucz dostawcy (``api_key_enc``) jest wyłączony z ``repr`` wiersza (``field(repr=False)``) —
nigdy nie wycieka przez logi ani diagnostykę.
"""

import json
from dataclasses import dataclass, field
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import from_ms

_COLUMNS = "id, provider, name, config, api_key_enc, is_default, created_by, create_time"

_GET_BY_ID_SQL = text(
    f"SELECT {_COLUMNS} FROM web_search_providers WHERE id = CAST(:provider_id AS BINARY)"  # noqa: S608
)

# `name` ma kolację `uca1400_ai_ci` → porównanie bez rozróżniania wielkości liter (K2 §6).
_GET_BY_NAME_SQL = text(
    f"SELECT {_COLUMNS} FROM web_search_providers WHERE name = :name"  # noqa: S608
)

_GET_DEFAULT_SQL = text(
    f"SELECT {_COLUMNS} FROM web_search_providers"  # noqa: S608
    " WHERE is_default = 1 ORDER BY create_time ASC, id LIMIT 1"
)

_LIST_ALL_SQL = text(
    f"SELECT {_COLUMNS} FROM web_search_providers ORDER BY create_time ASC, id"  # noqa: S608
)

_INSERT_SQL = text(
    "INSERT INTO web_search_providers (id, provider, name, config, api_key_enc, is_default,"
    " created_by, create_time, create_date, update_time, update_date)"
    " VALUES (:id, :provider, :name, :config, :api_key_enc, :is_default,"
    " :created_by, :now_ms, :date, :now_ms, :date)"
)

_UPDATE_SQL = text(
    "UPDATE web_search_providers SET name = :name, config = :config, is_default = :is_default,"
    " update_time = :now_ms, update_date = :date"
    " WHERE id = CAST(:provider_id AS BINARY)"
)

_UPDATE_KEY_SQL = text(
    "UPDATE web_search_providers SET api_key_enc = :api_key_enc,"
    " update_time = :now_ms, update_date = :date"
    " WHERE id = CAST(:provider_id AS BINARY)"
)

_DELETE_SQL = text("DELETE FROM web_search_providers WHERE id = CAST(:provider_id AS BINARY)")


@dataclass(frozen=True)
class WebSearchProviderRow:
    """Wiersz `web_search_providers`; `config` zdekodowany, klucz poza `repr` (CONTRACT §C2)."""

    id: str
    provider: str
    name: str
    config: dict[str, Any]
    api_key_enc: bytes | None = field(repr=False)
    is_default: bool
    created_by: str | None
    create_time: int


def _row(row: Any) -> WebSearchProviderRow:
    """RowMapping → WebSearchProviderRow; JSON (asyncmy: str) → dict."""
    return WebSearchProviderRow(
        id=row["id"],
        provider=row["provider"],
        name=row["name"],
        config=json.loads(row["config"]),
        api_key_enc=row["api_key_enc"],
        is_default=bool(row["is_default"]),
        created_by=row["created_by"],
        create_time=int(row["create_time"]),
    )


async def insert(  # noqa: PLR0913 — sygnatura z CONTRACT §C2
    session: AsyncSession,
    *,
    id: str,  # nazwa pola z kontraktu §C2
    provider: str,
    name: str,
    config: dict[str, Any],
    api_key_enc: bytes | None,
    is_default: bool,
    created_by: str | None,
    now_ms: int,
) -> None:
    """Wstawia dostawcę; czasy z zegara wołającego (§C2)."""
    date = from_ms(now_ms)
    await session.execute(
        _INSERT_SQL,
        {
            "id": id,
            "provider": provider,
            "name": name,
            "config": json.dumps(config, ensure_ascii=False),
            "api_key_enc": api_key_enc,
            "is_default": int(is_default),
            "created_by": created_by,
            "now_ms": now_ms,
            "date": date,
        },
    )


async def get_by_id(session: AsyncSession, provider_id: str) -> WebSearchProviderRow | None:
    """Dostawca po identyfikatorze; None gdy brak."""
    found = (await session.execute(_GET_BY_ID_SQL, {"provider_id": provider_id})).mappings().first()
    return _row(found) if found is not None else None


async def get_by_name(session: AsyncSession, name: str) -> WebSearchProviderRow | None:
    """Dostawca po nazwie — kolacja `ai_ci`, bez rozróżniania wielkości liter."""
    found = (await session.execute(_GET_BY_NAME_SQL, {"name": name})).mappings().first()
    return _row(found) if found is not None else None


async def get_default(session: AsyncSession) -> WebSearchProviderRow | None:
    """Domyślny dostawca (`is_default = 1`), najstarszy po ``create_time`` (§C2)."""
    found = (await session.execute(_GET_DEFAULT_SQL)).mappings().first()
    return _row(found) if found is not None else None


async def list_all(session: AsyncSession) -> list[WebSearchProviderRow]:
    """Wszyscy dostawcy, kolejność ``create_time`` ASC, id (§C2)."""
    rows = (await session.execute(_LIST_ALL_SQL)).mappings().all()
    return [_row(row) for row in rows]


async def update(  # noqa: PLR0913 — sygnatura z CONTRACT §C2
    session: AsyncSession,
    *,
    provider_id: str,
    name: str,
    config: dict[str, Any],
    is_default: bool,
    api_key_enc: bytes | None,
    set_key: bool,
    now_ms: int,
) -> None:
    """Zapisuje nazwę, `config` i `is_default`; klucz tylko gdy `set_key` (§C2)."""
    date = from_ms(now_ms)
    await session.execute(
        _UPDATE_SQL,
        {
            "provider_id": provider_id,
            "name": name,
            "config": json.dumps(config, ensure_ascii=False),
            "is_default": int(is_default),
            "now_ms": now_ms,
            "date": date,
        },
    )
    if set_key:
        await session.execute(
            _UPDATE_KEY_SQL,
            {
                "provider_id": provider_id,
                "api_key_enc": api_key_enc,
                "now_ms": now_ms,
                "date": date,
            },
        )


async def delete_by_id(session: AsyncSession, provider_id: str) -> int:
    """Usuwa dostawcę; zwraca liczbę usuniętych wierszy (§C2)."""
    result = await session.execute(_DELETE_SQL, {"provider_id": provider_id})
    return int(cast("CursorResult[Any]", result).rowcount)
