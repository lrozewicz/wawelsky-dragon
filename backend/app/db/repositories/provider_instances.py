"""Repozytorium tabeli `provider_instances` (kontrakt K13 §1, CONTRACT E3-6b §T1).

SQL przez ``text()``, bez commit/rollback — commituje ``app.db.uow.transaction``.
``id`` i ``created_by`` mają kolację `ascii_bin`, a parametry z żądania są w `utf8mb4_*`:
porównania parametru z kolumną `CHAR(32)` idą przez ``CAST(:x AS BINARY)`` (DEC-087/090).
"""

from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import bindparam, text
from sqlalchemy.engine import CursorResult, RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import from_ms

_COLUMNS = "id, provider, name, base_url, api_key_enc, created_by, create_time"

_GET_BY_ID_SQL = text(
    f"SELECT {_COLUMNS} FROM provider_instances WHERE id = CAST(:instance_id AS BINARY)"  # noqa: S608
)

# `name` w tabeli ma kolację `uca1400_ai_ci` → porównanie bez rozróżniania wielkości liter (K13 §1).
_GET_BY_NAME_SQL = text(
    f"SELECT {_COLUMNS} FROM provider_instances"  # noqa: S608
    " WHERE provider = :provider AND name = :name"
)

# Kolejność odpowiedzi GET /providers/{name}/instances: najnowsze pierwsze (K13 §3, CONTRACT §T1).
_LIST_BY_PROVIDER_SQL = text(
    f"SELECT {_COLUMNS} FROM provider_instances"  # noqa: S608
    " WHERE provider = :provider ORDER BY create_time DESC, id"
)

_INSERT_SQL = text(
    "INSERT INTO provider_instances (id, provider, name, base_url, api_key_enc, created_by,"
    " create_time, create_date, update_time, update_date)"
    " VALUES (:id, :provider, :name, :base_url, :api_key_enc, :created_by,"
    " :now_ms, :date, :now_ms, :date)"
)

_UPDATE_SQL = text(
    "UPDATE provider_instances SET name = :name, base_url = :base_url,"
    " update_time = :now_ms, update_date = :date"
    " WHERE id = CAST(:instance_id AS BINARY)"
)

_UPDATE_KEY_SQL = text(
    "UPDATE provider_instances SET api_key_enc = :api_key_enc,"
    " update_time = :now_ms, update_date = :date"
    " WHERE id = CAST(:instance_id AS BINARY)"
)

# Lista `IN` rzutowana po stronie kolumny (cast elementu listy nie wchodzi w `text()` z expanding,
# DEC-087).
_DELETE_SQL = text("DELETE FROM provider_instances WHERE CAST(id AS BINARY) IN :ids").bindparams(
    bindparam("ids", expanding=True)
)


@dataclass(frozen=True)
class InstanceRow:
    """Wiersz `provider_instances` bez mixinu czasu (K13 §1, CONTRACT §T1)."""

    id: str
    provider: str
    name: str
    base_url: str
    api_key_enc: bytes | None
    created_by: str | None
    create_time: int


def _row(row: RowMapping) -> InstanceRow:
    """RowMapping → InstanceRow."""
    return InstanceRow(
        id=row["id"],
        provider=row["provider"],
        name=row["name"],
        base_url=row["base_url"],
        api_key_enc=row["api_key_enc"],
        created_by=row["created_by"],
        create_time=row["create_time"],
    )


async def insert(  # noqa: PLR0913 — sygnatura z CONTRACT E3-6b §T1
    session: AsyncSession,
    *,
    id: str,
    provider: str,
    name: str,
    base_url: str,
    api_key_enc: bytes | None,
    created_by: str | None,
    now_ms: int,
) -> None:
    """Wstawia instancję; `create_time`/`update_time` z zegara wołającego."""
    date = from_ms(now_ms).replace(tzinfo=None)
    await session.execute(
        _INSERT_SQL,
        {
            "id": id,
            "provider": provider,
            "name": name,
            "base_url": base_url,
            "api_key_enc": api_key_enc,
            "created_by": created_by,
            "now_ms": now_ms,
            "date": date,
        },
    )


async def get_by_id(session: AsyncSession, instance_id: str) -> InstanceRow | None:
    """Instancja po identyfikatorze; None gdy brak."""
    found = (await session.execute(_GET_BY_ID_SQL, {"instance_id": instance_id})).mappings().first()
    return _row(found) if found is not None else None


async def get_by_name(session: AsyncSession, provider: str, name: str) -> InstanceRow | None:
    """Instancja po dostawcy i nazwie — kolacja `ai_ci`, bez rozróżniania wielkości liter."""
    found = (
        (await session.execute(_GET_BY_NAME_SQL, {"provider": provider, "name": name}))
        .mappings()
        .first()
    )
    return _row(found) if found is not None else None


async def list_by_provider(session: AsyncSession, provider: str) -> list[InstanceRow]:
    """Instancje dostawcy, najnowsze pierwsze (K13 §3 — wiersze tabeli wg create_time malejąco)."""
    rows = (await session.execute(_LIST_BY_PROVIDER_SQL, {"provider": provider})).mappings().all()
    return [_row(row) for row in rows]


async def update(  # noqa: PLR0913 — sygnatura z CONTRACT E3-6b §T1
    session: AsyncSession,
    *,
    instance_id: str,
    name: str,
    base_url: str,
    api_key_enc: bytes | None,
    set_key: bool,
    now_ms: int,
) -> None:
    """Zapisuje nazwę i `base_url`; klucz tylko gdy `set_key` (inaczej bez zmiany)."""
    date = from_ms(now_ms).replace(tzinfo=None)
    await session.execute(
        _UPDATE_SQL,
        {
            "instance_id": instance_id,
            "name": name,
            "base_url": base_url,
            "now_ms": now_ms,
            "date": date,
        },
    )
    if set_key:
        await session.execute(
            _UPDATE_KEY_SQL,
            {
                "instance_id": instance_id,
                "api_key_enc": api_key_enc,
                "now_ms": now_ms,
                "date": date,
            },
        )


async def delete_by_ids(session: AsyncSession, ids: list[str]) -> int:
    """Usuwa instancje o podanych id; zwraca liczbę usuniętych wierszy."""
    result = await session.execute(_DELETE_SQL, {"ids": ids})
    return int(cast("CursorResult[Any]", result).rowcount)
