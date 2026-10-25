"""Repozytorium tabeli `dataset_imports` (CONTRACT E7-1f §5, K19 §4).

SQL przez ``text()``, bez ``commit``/``rollback`` — transakcję otwiera ``app.db.uow.transaction``.
``id``/``user_id``/``task_id`` mają kolację `ascii_bin`, a parametry z żądania są w `utf8mb4_*`:
porównania parametru z kolumną ``CHAR(32)`` idą przez ``CAST(:x AS BINARY)`` (DEC-087/090).
``errors``/``summary`` to JSON — dekodowane przy odczycie (kontrakt: „RowMapping-like dict”).
"""

import json
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.engine import CursorResult, RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import from_ms

_GET_SQL = text(
    "SELECT id, user_id, file_name, size_bytes, received_bytes, state, errors, summary,"
    " task_id, expires_at, create_time, create_date, update_time, update_date"
    " FROM dataset_imports WHERE id = CAST(:import_id AS BINARY)"
)

_INSERT_SQL = text(
    "INSERT INTO dataset_imports (id, user_id, file_name, size_bytes, received_bytes, state,"
    " errors, summary, task_id, expires_at, create_time, create_date, update_time, update_date)"
    " VALUES (:id, :user_id, :file_name, :size_bytes, 0, 'uploading', '[]', NULL, NULL,"
    " :expires_at, :now_ms, :date, :now_ms, :date)"
)

# Porcja dolicza się do `received_bytes` (wznowienie uploadu od `received_bytes`, K19 §3 trasa 7)
# i przedłuża `expires_at` o kolejne 24 h (K19 §4).
_ADD_RECEIVED_SQL = text(
    "UPDATE dataset_imports SET received_bytes = received_bytes + :received_bytes,"
    " expires_at = :expires_at, update_time = :now_ms, update_date = :date"
    " WHERE id = CAST(:import_id AS BINARY)"
)

_DELETE_SQL = text("DELETE FROM dataset_imports WHERE id = CAST(:import_id AS BINARY)")

_EXPIRE_OLDER_SQL = text(
    "UPDATE dataset_imports SET state = 'expired', update_time = :now_ms, update_date = :date"
    " WHERE expires_at < :before_ms AND state != 'expired'"
)

# Kandydaci blokowani ``FOR UPDATE`` do końca transakcji — brak okna między wyborem id a `UPDATE`
# (CONTRACT E7-1z §4). MariaDB nie ma ``UPDATE … RETURNING``, więc wybieramy wariant z blokadą.
_SELECT_OLDER_SQL = text(
    "SELECT id FROM dataset_imports WHERE expires_at < :before_ms AND state != 'expired' FOR UPDATE"
)

# Domknięcie sesji po porcji kończącej (CONTRACT E7-1z §6, transakcja 2): warunkowo, by nie
# nadpisać stanu, gdy wiersz zmienił się między zapisem porcji a walidacją (rowcount 0 ⇒ 409).
_FINALIZE_SQL = text(
    "UPDATE dataset_imports SET state = :state, errors = :errors, summary = :summary,"
    " update_time = :now_ms, update_date = :date"
    " WHERE id = CAST(:import_id AS BINARY) AND state = 'uploading'"
    " AND received_bytes = size_bytes"
)


def _row(row: RowMapping) -> dict[str, Any]:
    """RowMapping → dict z zdekodowanym JSON-em `errors`/`summary` (CONTRACT §5)."""
    data = dict(row)
    raw_errors = data["errors"]
    data["errors"] = json.loads(raw_errors) if raw_errors is not None else []
    raw_summary = data["summary"]
    data["summary"] = json.loads(raw_summary) if raw_summary is not None else None
    return data


async def insert(  # noqa: PLR0913 — kolumny tabeli z K19 §4
    session: AsyncSession,
    *,
    id: str,  # nazwa pola z kontraktu §5
    user_id: str,
    file_name: str,
    size_bytes: int,
    expires_at: int,
    now_ms: int,
) -> None:
    """Wstawia sesję importu w stanie `uploading`; czasy z zegara wołającego (§5)."""
    await session.execute(
        _INSERT_SQL,
        {
            "id": id,
            "user_id": user_id,
            "file_name": file_name,
            "size_bytes": size_bytes,
            "expires_at": expires_at,
            "now_ms": now_ms,
            "date": from_ms(now_ms),
        },
    )


async def get(session: AsyncSession, import_id: str) -> dict[str, Any] | None:
    """Sesja importu po identyfikatorze (JSON zdekodowany); None gdy brak (§5)."""
    found = (await session.execute(_GET_SQL, {"import_id": import_id})).mappings().first()
    return _row(found) if found is not None else None


async def add_received(
    session: AsyncSession, *, import_id: str, received_bytes: int, expires_at: int, now_ms: int
) -> None:
    """Dolicza przyjętą porcję, przedłuża `expires_at` i podbija czasy (§5)."""
    await session.execute(
        _ADD_RECEIVED_SQL,
        {
            "import_id": import_id,
            "received_bytes": received_bytes,
            "expires_at": expires_at,
            "now_ms": now_ms,
            "date": from_ms(now_ms),
        },
    )


async def set_state(  # noqa: PLR0913 — pola stanu z kontraktu §5
    session: AsyncSession,
    *,
    import_id: str,
    state: str,
    errors: list[dict[str, Any]] | None = None,
    summary: dict[str, Any] | None = None,
    task_id: str | None = None,
    now_ms: int,
) -> None:
    """Ustawia stan sesji wraz z `errors`/`summary` (JSON) i `task_id` (§5).

    Pominięte `errors` zostawiają poprzednią wartość; `summary`/`task_id` bez wartości czyszczą.
    """
    await session.execute(
        text(
            "UPDATE dataset_imports SET state = :state,"
            " errors = COALESCE(:errors, errors), summary = :summary, task_id = :task_id,"
            " update_time = :now_ms, update_date = :date"
            " WHERE id = CAST(:import_id AS BINARY)"
        ),
        {
            "import_id": import_id,
            "state": state,
            "errors": (json.dumps(errors, ensure_ascii=False) if errors is not None else None),
            "summary": json.dumps(summary, ensure_ascii=False) if summary is not None else None,
            "task_id": task_id,
            "now_ms": now_ms,
            "date": from_ms(now_ms),
        },
    )


async def set_final_state(  # noqa: PLR0913 — pola stanu z kontraktu §5/§6
    session: AsyncSession,
    *,
    import_id: str,
    state: str,
    errors: list[dict[str, Any]],
    summary: dict[str, Any] | None,
    now_ms: int,
) -> bool:
    """Domknięcie sesji po porcji kończącej — warunkowo (CONTRACT E7-1z §6, transakcja 2).

    Ustawia stan tylko, gdy wiersz jest wciąż ``uploading`` i ``received_bytes == size_bytes``.
    Zwraca ``True``, gdy warunek zaszedł (rowcount 1); ``False``, gdy wiersz zmienił się między
    transakcją zapisu porcji a domknięciem (albo zniknął) — wołający odpowiada 409.
    """
    result = await session.execute(
        _FINALIZE_SQL,
        {
            "import_id": import_id,
            "state": state,
            "errors": json.dumps(errors, ensure_ascii=False),
            "summary": json.dumps(summary, ensure_ascii=False) if summary is not None else None,
            "now_ms": now_ms,
            "date": from_ms(now_ms),
        },
    )
    return int(cast("CursorResult[Any]", result).rowcount) > 0


async def delete(session: AsyncSession, import_id: str) -> bool:
    """Usuwa sesję importu; True, gdy wiersz istniał (§5)."""
    result = await session.execute(_DELETE_SQL, {"import_id": import_id})
    return int(cast("CursorResult[Any]", result).rowcount) > 0


async def expire_older(session: AsyncSession, *, before_ms: int, now_ms: int) -> list[str]:
    """Przestawia wygasłe nie-`expired` wiersze na `expired`; zwraca ich id (§5).

    Atomowo: ``SELECT … FOR UPDATE`` blokuje wiersze-kandydatów do końca transakcji (CONTRACT
    E7-1z §4), więc między wyborem id a ``UPDATE`` (ta sama transakcja) nie wśliznie się zmiana
    stanu/``expires_at`` — zwrócone id to dokładnie wiersze przestawione na ``expired``.
    Wołający usuwa pliki wg zwróconej listy (sprzątanie 24 h, K19 §5). MariaDB nie ma
    ``UPDATE … RETURNING``; wariant z blokadą jest prostszy niż marker ``update_time``.
    """
    ids = [
        str(row[0])
        for row in (await session.execute(_SELECT_OLDER_SQL, {"before_ms": before_ms})).all()
    ]
    if not ids:
        return []
    await session.execute(
        _EXPIRE_OLDER_SQL,
        {"before_ms": before_ms, "now_ms": now_ms, "date": from_ms(now_ms)},
    )
    return ids
