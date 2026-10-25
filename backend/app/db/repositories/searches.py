"""Repozytorium tabel `searches` i `search_datasets` (K15 §1, CONTRACT E4-4a §D3).

Core ``text()`` z parametrami wiązanymi, bez ``commit``/``rollback`` — transakcję otwiera
wywołująca (``app.db.uow.transaction``). ``search_config`` trzymamy bez ``kb_ids``: wiązania
datasetów żyją w ``search_datasets`` (porządek ``ordinal``).
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, cast

from sqlalchemy import bindparam, text
from sqlalchemy.engine import CursorResult, RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import from_ms
from app.domain.policy import VisibilityFilter

_INSERT_SQL = text(
    "INSERT INTO searches (id, tenant_id, created_by, name, description, avatar,"
    " search_config, status, create_time, create_date, update_time, update_date)"
    " VALUES (:id, :tenant_id, :tenant_id, :name, :description, :avatar, :search_config,"
    " '1', :now, :now_date, :now, :now_date)"
)

# ``searches.id`` ma kolację `ascii_bin` (schemat WD), a parametr z żądania jest w `utf8mb4_*` —
# MySQL wywraca porównanie wartością spoza ASCII błędem 1267 („Illegal mix of collations").
# Porównanie id-ów z żądania idzie więc przez ``CAST(… AS BINARY)`` (jak ``chats.py``).
_SELECT_SQL = text(
    "SELECT id, tenant_id, created_by, name, description, avatar, search_config, status,"
    " create_time, create_date, update_time, update_date"
    " FROM searches WHERE id = CAST(:id AS BINARY) AND status = '1'"
)

_SELECT_OWNED_SQL = text(
    "SELECT id, tenant_id, created_by, name, description, avatar, search_config, status,"
    " create_time, create_date, update_time, update_date"
    " FROM searches WHERE id = CAST(:id AS BINARY) AND created_by = :user_id AND status = '1'"
)

_DELETE_SQL = text("DELETE FROM searches WHERE id = CAST(:id AS BINARY)")

_DELETE_BINDINGS_SQL = text("DELETE FROM search_datasets WHERE search_id = :search_id")

_INSERT_BINDING_SQL = text(
    "INSERT INTO search_datasets (search_id, dataset_id, ordinal)"
    " VALUES (:search_id, :dataset_id, :ordinal)"
)

_LIST_IDS_SQL = text(
    "SELECT dataset_id FROM search_datasets WHERE search_id = :search_id"
    " ORDER BY ordinal, dataset_id"
)

_LIST_IDS_MANY_SQL = text(
    "SELECT search_id, dataset_id FROM search_datasets WHERE search_id IN :search_ids"
    " ORDER BY search_id, ordinal, dataset_id"
).bindparams(bindparam("search_ids", expanding=True))

# Użycie datasetu (K20 §4): wyszukiwarki widoczne dla aktora (name, potem id) z limitem+1 —
# nadwyżka świadczy o ucięciu; osobny COUNT wiązań niewidocznych (bez nazw i id). Predykat
# ``status = '1'`` jak na liście wyszukiwarek (§D3); zakres z ``VisibilityFilter``.
_USAGE_VISIBLE_SQL = text(
    "SELECT s.id, s.name"
    " FROM search_datasets AS sd JOIN searches AS s ON s.id = sd.search_id"
    " WHERE sd.dataset_id = :ds AND s.tenant_id IN :owners AND s.status = '1'"
    " ORDER BY s.name, s.id LIMIT :limit"
).bindparams(bindparam("owners", expanding=True))
_USAGE_VISIBLE_ALL_SQL = text(
    "SELECT s.id, s.name"
    " FROM search_datasets AS sd JOIN searches AS s ON s.id = sd.search_id"
    " WHERE sd.dataset_id = :ds AND s.status = '1'"
    " ORDER BY s.name, s.id LIMIT :limit"
)
_USAGE_HIDDEN_SQL = text(
    "SELECT COUNT(*)"
    " FROM search_datasets AS sd JOIN searches AS s ON s.id = sd.search_id"
    " WHERE sd.dataset_id = :ds AND s.tenant_id NOT IN :owners AND s.status = '1'"
).bindparams(bindparam("owners", expanding=True))

# Biała lista kolumn orderby — tekst od użytkownika nigdy nie trafia do SQL wprost (K15).
# Nazwy kwalifikowane aliasem, bo list_page dołącza users.
_ORDERBY: Final[dict[str, str]] = {
    "create_time": "s.create_time",
    "update_time": "s.update_time",
    "name": "s.name",
}
_DEFAULT_ORDERBY = "create_time"


@dataclass(frozen=True)
class SearchRow:
    """Wiersz `searches` (CONTRACT E4-4a §D3); ``search_config`` bez ``kb_ids``."""

    id: str
    tenant_id: str
    created_by: str
    name: str
    description: str | None
    avatar: str | None
    search_config: dict[str, Any]
    status: str
    create_time: int
    create_date: datetime
    update_time: int
    update_date: datetime


@dataclass(frozen=True)
class SearchListRow:
    """Wiersz listy wyszukiwarek z danymi właściciela (JOIN users, §D3)."""

    row: SearchRow
    nickname: str | None
    tenant_avatar: str | None


def _row(row: RowMapping) -> SearchRow:
    """RowMapping → SearchRow; JSON (asyncmy: str) → dict, daty zostają datetime."""
    return SearchRow(
        id=row["id"],
        tenant_id=row["tenant_id"],
        created_by=row["created_by"],
        name=row["name"],
        description=row["description"],
        avatar=row["avatar"],
        search_config=json.loads(row["search_config"]),
        status=row["status"],
        create_time=int(row["create_time"]),
        create_date=row["create_date"],
        update_time=int(row["update_time"]),
        update_date=row["update_date"],
    )


def _like_keywords(keywords: str) -> str:
    """Wzorzec LIKE dla keywords: %…% po LOWER, znaki \\, %, _ dosłownie (§D3)."""
    escaped = keywords.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped.lower()}%"


async def insert(  # noqa: PLR0913 — sygnatura z kontraktu §D3
    session: AsyncSession,
    *,
    id: str,  # nazwa pola z kontraktu §D3
    tenant_id: str,
    name: str,
    description: str | None,
    avatar: str | None,
    search_config: dict[str, Any],
    now_ms: int,
) -> None:
    """Wstawia wyszukiwarkę: created_by = tenant_id, status '1', czasy z ``now_ms`` (§D3)."""
    await session.execute(
        _INSERT_SQL,
        {
            "id": id,
            "tenant_id": tenant_id,
            "name": name,
            "description": description,
            "avatar": avatar,
            "search_config": json.dumps(search_config, ensure_ascii=False),
            "now": now_ms,
            "now_date": from_ms(now_ms),
        },
    )


async def get(session: AsyncSession, search_id: str) -> SearchRow | None:
    """Wyszukiwarka po id, tylko ``status='1'``; None gdy brak (§D3)."""
    found = (await session.execute(_SELECT_SQL, {"id": search_id})).mappings().first()
    return _row(found) if found is not None else None


async def get_owned(session: AsyncSession, search_id: str, user_id: str) -> SearchRow | None:
    """Wyszukiwarka właściciela (`created_by = user_id`) i aktywna; inaczej None (§D3)."""
    found = (
        (await session.execute(_SELECT_OWNED_SQL, {"id": search_id, "user_id": user_id}))
        .mappings()
        .first()
    )
    return _row(found) if found is not None else None


async def name_taken(
    session: AsyncSession, tenant_id: str, name: str, *, exclude_id: str | None = None
) -> bool:
    """Czy nazwa zajęta u właściciela, bez rozróżniania wielkości liter (§D3).

    ``exclude_id`` pomija wskazany wiersz (przypadek PUT własnej nazwy).
    """
    sql = (
        "SELECT 1 FROM searches WHERE tenant_id = :tenant_id AND status = '1'"
        " AND LOWER(name) = LOWER(:name)"
    )
    params: dict[str, Any] = {"tenant_id": tenant_id, "name": name}
    if exclude_id is not None:
        sql += " AND id != CAST(:exclude_id AS BINARY)"
        params["exclude_id"] = exclude_id
    found = (await session.execute(text(sql + " LIMIT 1"), params)).first()
    return found is not None


async def update(  # noqa: PLR0913 — sygnatura z kontraktu §D3
    session: AsyncSession,
    search_id: str,
    *,
    name: str,
    description: str | None,
    avatar: str | None,
    search_config: dict[str, Any],
    now_ms: int,
) -> None:
    """Podmienia nazwę, opis, avatar i `search_config`; zawsze podbija czasy (§D3)."""
    await session.execute(
        text(
            "UPDATE searches SET name = :name, description = :description, avatar = :avatar,"
            " search_config = :search_config, update_time = :now, update_date = :now_date"
            " WHERE id = CAST(:id AS BINARY)"
        ),
        {
            "id": search_id,
            "name": name,
            "description": description,
            "avatar": avatar,
            "search_config": json.dumps(search_config, ensure_ascii=False),
            "now": now_ms,
            "now_date": from_ms(now_ms),
        },
    )


async def delete(session: AsyncSession, search_id: str) -> int:
    """Usuwa wyszukiwarkę; zwraca liczbę usuniętych wierszy (kaskada FK czyści wiązania, §D3)."""
    result = await session.execute(_DELETE_SQL, {"id": search_id})
    return int(cast("CursorResult[Any]", result).rowcount)


async def list_page(  # noqa: PLR0913 — sygnatura z kontraktu §D3
    session: AsyncSession,
    tenant_id: str,
    *,
    keywords: str,
    orderby: str,
    desc: bool,
    page: int,
    page_size: int,
) -> tuple[list[SearchListRow], int]:
    """Strona wyszukiwarek właściciela (JOIN users) + liczba wszystkich pasujących (§D3).

    Zakres: ``tenant_id`` i ``status='1'``; keywords — LIKE po LOWER(name) (escape ``%``/``_``);
    orderby z białej listy (inne → create_time), kolejność stabilna po id w tym samym kierunku;
    ``page <= 0`` lub ``page_size <= 0`` → bez LIMIT/OFFSET.
    """
    column = _ORDERBY.get(orderby, _ORDERBY[_DEFAULT_ORDERBY])
    direction = "DESC" if desc else "ASC"
    conditions = ["s.tenant_id = :tenant_id", "s.status = '1'"]
    params: dict[str, Any] = {"tenant_id": tenant_id}
    if keywords:
        conditions.append("LOWER(s.name) LIKE :kw ESCAPE '\\\\'")
        params["kw"] = _like_keywords(keywords)
    filter_sql = " AND ".join(conditions)
    # Składany SQL: warunki stałe, kolumna orderby z białej listy _ORDERBY (K15).
    count_clause = text(f"SELECT COUNT(*) FROM searches AS s WHERE {filter_sql}")  # noqa: S608
    rows_sql = (
        "SELECT s.id, s.tenant_id, s.created_by, s.name, s.description, s.avatar,"  # noqa: S608
        " s.search_config, s.status, s.create_time, s.create_date, s.update_time, s.update_date,"
        " u.nickname AS nickname, u.avatar AS tenant_avatar"
        " FROM searches AS s JOIN users AS u ON u.id = s.tenant_id"
        + f" WHERE {filter_sql} ORDER BY {column} {direction}, s.id {direction}"
    )
    if page > 0 and page_size > 0:
        rows_sql += " LIMIT :limit OFFSET :offset"
        params["limit"] = page_size
        params["offset"] = (page - 1) * page_size
    total = int((await session.execute(count_clause, params)).scalar_one())
    found = (await session.execute(text(rows_sql), params)).mappings().all()
    rows = [
        SearchListRow(row=_row(row), nickname=row["nickname"], tenant_avatar=row["tenant_avatar"])
        for row in found
    ]
    return rows, total


async def set_dataset_ids(
    session: AsyncSession, search_id: str, dataset_ids: Sequence[str]
) -> None:
    """Podmienia wiązania wyszukiwarki: DELETE starych + INSERT z ``ordinal`` = indeks (§D3)."""
    await session.execute(_DELETE_BINDINGS_SQL, {"search_id": search_id})
    if not dataset_ids:
        return
    await session.execute(
        _INSERT_BINDING_SQL,
        [
            {"search_id": search_id, "dataset_id": dataset_id, "ordinal": ordinal}
            for ordinal, dataset_id in enumerate(dataset_ids)
        ],
    )


async def list_dataset_ids(session: AsyncSession, search_id: str) -> list[str]:
    """Id datasetów wyszukiwarki w kolejności ``ordinal`` (§D3)."""
    rows = (await session.execute(_LIST_IDS_SQL, {"search_id": search_id})).all()
    return [row[0] for row in rows]


async def usage(
    session: AsyncSession, dataset_id: str, *, visibility: VisibilityFilter, limit: int
) -> tuple[list[tuple[str, str]], int, bool]:
    """Wyszukiwarki powiązane z datasetem: widoczne (id, name), ukryte wiązania, ucięcie (K20 §4).

    Zakres widoczności z ``VisibilityFilter``: ``all`` = superuser (widzi wszystkie wiązania,
    ukryte = 0); inaczej widoczne są tylko wyszukiwarki ``tenant_id`` z ``owner_ids``.
    Pobiera ``limit + 1`` wierszy — pozycja nad limit świadczy o ucięciu i jest odrzucana.
    Niewidoczne wiązania zlicza osobnym COUNT-em, bez ujawniania nazw i id.
    """
    if not visibility.all and not visibility.owner_ids:
        return [], 0, False
    params: dict[str, Any] = {"ds": dataset_id, "limit": limit + 1}
    if visibility.all:
        stmt = _USAGE_VISIBLE_ALL_SQL
        hidden = 0
    else:
        stmt = _USAGE_VISIBLE_SQL
        params["owners"] = sorted(visibility.owner_ids)
        hidden = int((await session.execute(_USAGE_HIDDEN_SQL, params)).scalar_one())
    rows = (await session.execute(stmt, params)).all()
    truncated = len(rows) > limit
    return [(row[0], row[1]) for row in rows[:limit]], hidden, truncated


async def list_dataset_ids_many(
    session: AsyncSession, search_ids: Sequence[str]
) -> dict[str, list[str]]:
    """search_id → id datasetów po ``ordinal``; wyszukiwarki bez wiązań → brak klucza (§D3).

    ``[]`` → ``{}`` bez SQL.
    """
    if not search_ids:
        return {}
    rows = (await session.execute(_LIST_IDS_MANY_SQL, {"search_ids": list(search_ids)})).all()
    bindings: dict[str, list[str]] = {}
    for search_id, dataset_id in rows:
        bindings.setdefault(search_id, []).append(dataset_id)
    return bindings
