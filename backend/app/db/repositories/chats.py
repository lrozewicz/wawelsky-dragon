"""Repozytorium tabeli chats (kontrakt C1) — Core ``text()`` z parametrami wiązanymi.

Bez ``commit``/``rollback`` — transakcję otwiera wywołująca (``app.db.uow.transaction``).
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final, cast

from sqlalchemy import bindparam, text
from sqlalchemy.engine import CursorResult, RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import from_ms

_INSERT_SQL = text(
    "INSERT INTO chats (id, tenant_id, created_by, name, description, icon, language,"
    " llm_id, llm_setting, prompt_type, prompt_config, similarity_threshold,"
    " vector_similarity_weight, top_n, top_k, rerank_candidates_count, rerank_id, do_refer,"
    " meta_data_filter, status, create_time, create_date, update_time, update_date)"
    " VALUES (:id, :tenant_id, :created_by, :name, :description, :icon, :language, :llm_id,"
    " :llm_setting, :prompt_type, :prompt_config, :similarity_threshold,"
    " :vector_similarity_weight, :top_n, :top_k, :rerank_candidates_count, :rerank_id,"
    " :do_refer, :meta_data_filter, :status, :now, :now_date, :now, :now_date)"
)

# ``chats.id`` ma kolację `ascii_bin` (schemat WD), a parametr z żądania jest w `utf8mb4_*` —
# MySQL wywraca porównanie wartością spoza ASCII błędem 1267 („Illegal mix of collations")
# i trasa oddawała `code 100` zamiast 102 (DEC-090 p. H). Porównanie id-ów z żądania idzie
# więc przez `CAST(… AS BINARY)`; rzutowany jest parametr, więc indeks `PRIMARY` zostaje
# — kolacja: patrz ``documents_query.py::_IDS_SQL`` (DEC-087 p. 4).
_SELECT_SQL = text(
    "SELECT id, tenant_id, created_by, name, description, icon, language, llm_id, llm_setting,"
    " prompt_type, prompt_config, similarity_threshold, vector_similarity_weight, top_n, top_k,"
    " rerank_candidates_count, rerank_id, do_refer, meta_data_filter, status, create_time,"
    " update_time FROM chats WHERE id = CAST(:id AS BINARY)"
)

_DELETE_SQL = text("DELETE FROM chats WHERE id = CAST(:id AS BINARY)")

_IDS_BY_OWNER_SQL = text(
    "SELECT id FROM chats WHERE tenant_id = :owner_id ORDER BY create_time, id"
)

# Biała lista kolumn orderby — tekst od użytkownika nigdy nie trafia do SQL wprost (C1);
# nazwy kwalifikowane tabelą, bo list_page dołącza users (tej samej kolumny czasu w users).
_ORDERBY: Final[dict[str, str]] = {
    "create_time": "chats.create_time",
    "update_time": "chats.update_time",
    "name": "chats.name",
}

# Pola czatu aktualizowalne przez API (C1); nazwy kolumn w UPDATE pochodzą wyłącznie stąd.
UPDATABLE: Final[frozenset[str]] = frozenset(
    {
        "name",
        "description",
        "icon",
        "language",
        "llm_id",
        "llm_setting",
        "prompt_type",
        "prompt_config",
        "similarity_threshold",
        "vector_similarity_weight",
        "top_n",
        "top_k",
        "rerank_candidates_count",
        "rerank_id",
        "meta_data_filter",
    }
)


@dataclass(frozen=True)
class ChatRow:
    """Wiersz `chats` — pola używane przez czat (kontrakt C1)."""

    id: str
    tenant_id: str
    created_by: str
    name: str
    language: str
    llm_id: str
    llm_setting: dict[str, Any]
    prompt_config: dict[str, Any]
    similarity_threshold: float
    vector_similarity_weight: float
    top_n: int
    top_k: int
    rerank_candidates_count: int
    rerank_id: str
    meta_data_filter: dict[str, Any] | None
    status: str
    # Nowe pola (C1) na końcu; czasy „tylko odczyt” — insert ustawia z now_ms, więc
    # wyłączone z == (compare=False wg DEC-030: istniejące testy porównują cały wiersz).
    description: str = ""
    icon: str = ""  # NULL w bazie ↔ "" (insert: "" → NULL)
    prompt_type: str = "simple"
    do_refer: str = "1"
    create_time: int = field(default=0, compare=False)
    update_time: int = field(default=0, compare=False)


@dataclass(frozen=True)
class ChatOwnerRow:
    """Czat z danymi właściciela (JOIN users) — lista czatów (C1)."""

    chat: ChatRow
    nickname: str  # users.nickname właściciela (tenant_id)
    avatar: str | None  # users.avatar


def _row(row: RowMapping) -> ChatRow:
    """RowMapping → ChatRow; JSON (asyncmy: zawsze str) → dict, icon NULL → "", czasy → int."""
    meta = row["meta_data_filter"]
    icon = row["icon"]
    return ChatRow(
        id=row["id"],
        tenant_id=row["tenant_id"],
        created_by=row["created_by"],
        name=row["name"],
        language=row["language"],
        llm_id=row["llm_id"],
        llm_setting=json.loads(row["llm_setting"]),
        prompt_config=json.loads(row["prompt_config"]),
        similarity_threshold=float(row["similarity_threshold"]),
        vector_similarity_weight=float(row["vector_similarity_weight"]),
        top_n=int(row["top_n"]),
        top_k=int(row["top_k"]),
        rerank_candidates_count=int(row["rerank_candidates_count"]),
        rerank_id=row["rerank_id"],
        meta_data_filter=json.loads(meta) if meta is not None else None,
        status=row["status"],
        description=row["description"],
        icon=icon if icon is not None else "",
        prompt_type=row["prompt_type"],
        do_refer=row["do_refer"],
        create_time=int(row["create_time"]),
        update_time=int(row["update_time"]),
    )


def _like_keywords(keywords: str) -> str:
    """Wzorzec LIKE dla keywords: %…% po LOWER, znaki \\, %, _ dosłownie (C1)."""
    escaped = keywords.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped.lower()}%"


async def insert(session: AsyncSession, row: ChatRow, *, now_ms: int) -> None:
    """Wstawia czat: description/icon/prompt_type/do_refer z row, icon "" → NULL (C1).

    create_time = update_time = now_ms; daty DATETIME(3) z milisekund.
    """
    await session.execute(
        _INSERT_SQL,
        {
            "id": row.id,
            "tenant_id": row.tenant_id,
            "created_by": row.created_by,
            "name": row.name,
            "description": row.description,
            "icon": None if row.icon == "" else row.icon,
            "language": row.language,
            "llm_id": row.llm_id,
            "llm_setting": json.dumps(row.llm_setting, ensure_ascii=False),
            "prompt_type": row.prompt_type,
            "prompt_config": json.dumps(row.prompt_config, ensure_ascii=False),
            "similarity_threshold": row.similarity_threshold,
            "vector_similarity_weight": row.vector_similarity_weight,
            "top_n": row.top_n,
            "top_k": row.top_k,
            "rerank_candidates_count": row.rerank_candidates_count,
            "rerank_id": row.rerank_id,
            "do_refer": row.do_refer,
            "meta_data_filter": (
                json.dumps(row.meta_data_filter, ensure_ascii=False)
                if row.meta_data_filter is not None
                else None
            ),
            "status": row.status,
            "now": now_ms,
            "now_date": from_ms(now_ms),
        },
    )


async def get(session: AsyncSession, chat_id: str) -> ChatRow | None:
    """Czat po identyfikatorze; None gdy brak (C1)."""
    found = (await session.execute(_SELECT_SQL, {"id": chat_id})).mappings().first()
    return _row(found) if found is not None else None


async def list_page(  # noqa: PLR0913 — sygnatura z kontraktu C1
    session: AsyncSession,
    *,
    owner_ids: frozenset[str] | None,
    chat_id: str | None,
    name: str | None,
    keywords: str,
    orderby: str,
    desc: bool,
    offset: int,
    limit: int,
    granted_ids: frozenset[str] = frozenset(),
) -> tuple[list[ChatOwnerRow], int]:
    """Strona listy czatów z danymi właściciela + liczba wszystkich pasujących (C1).

    owner_ids None = bez filtra właściciela (puste owner_ids i granted_ids → ([], 0) bez SQL);
    niepuste granted_ids dołączają czaty z grantem do warunku właściciela (C6);
    chat_id/name — równość; keywords (niepuste i bez chat_id/name) — LIKE po LOWER(name);
    orderby z białej listy, kolejność stabilna po chats.id w tym samym kierunku;
    limit 0 → wszystkie wiersze (bez LIMIT/OFFSET).
    """
    if owner_ids is not None and not owner_ids and not granted_ids:
        return [], 0
    if orderby not in _ORDERBY:
        raise ValueError(f"orderby: {orderby}")
    direction = "DESC" if desc else "ASC"
    conditions: list[str] = []
    params: dict[str, Any] = {}
    if owner_ids is not None:
        if granted_ids:
            conditions.append("(chats.tenant_id IN :owner_ids OR chats.id IN :granted_ids)")
            params["granted_ids"] = list(granted_ids)
        else:
            conditions.append("chats.tenant_id IN :owner_ids")
        params["owner_ids"] = list(owner_ids)
    if chat_id is not None:
        conditions.append("chats.id = CAST(:chat_id AS BINARY)")  # kolacja: patrz „_SELECT_SQL"
        params["chat_id"] = chat_id
    if name is not None:
        conditions.append("chats.name = :name")
        params["name"] = name
    if keywords and chat_id is None and name is None:
        conditions.append("LOWER(chats.name) LIKE :kw ESCAPE '\\\\'")
        params["kw"] = _like_keywords(keywords)
    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    # Składany SQL: warunki stałe, kolumna orderby z białej listy _ORDERBY (C1).
    # COUNT(*) po tych samych warunkach — bez JOIN (warunki dotyczą tylko chats).
    count_clause = text("SELECT COUNT(*) FROM chats" + where)  # noqa: S608 — warunki stałe
    rows_sql = (
        "SELECT chats.*, users.nickname AS nickname, users.avatar AS avatar"  # noqa: S608
        " FROM chats JOIN users ON users.id = chats.tenant_id"
        + where
        + f" ORDER BY {_ORDERBY[orderby]} {direction}, chats.id {direction}"
    )
    if limit > 0:
        rows_sql += " LIMIT :limit OFFSET :offset"
        params["limit"] = limit
        params["offset"] = offset
    rows_clause = text(rows_sql)
    if owner_ids is not None:
        # IN z listą wymaga expanding (wartość nie może trafić do SQL wprost).
        count_clause = count_clause.bindparams(bindparam("owner_ids", expanding=True))
        rows_clause = rows_clause.bindparams(bindparam("owner_ids", expanding=True))
    if granted_ids:
        count_clause = count_clause.bindparams(bindparam("granted_ids", expanding=True))
        rows_clause = rows_clause.bindparams(bindparam("granted_ids", expanding=True))
    total = int((await session.execute(count_clause, params)).scalar_one())
    found = (await session.execute(rows_clause, params)).mappings().all()
    rows = [
        ChatOwnerRow(chat=_row(row), nickname=row["nickname"], avatar=row["avatar"])
        for row in found
    ]
    return rows, total


async def name_taken(
    session: AsyncSession, tenant_id: str, name: str, *, exclude_id: str | None = None
) -> bool:
    """Czy nazwa zajęta w obrębie właściciela; kolacja ai_ci — bez rozróżniania wielkości (C1)."""
    sql = "SELECT 1 FROM chats WHERE tenant_id = :tenant_id AND name = :name"
    params: dict[str, Any] = {"tenant_id": tenant_id, "name": name}
    if exclude_id is not None:
        sql += " AND id != :exclude_id"
        params["exclude_id"] = exclude_id
    found = (await session.execute(text(sql + " LIMIT 1"), params)).first()
    return found is not None


async def update(
    session: AsyncSession, chat_id: str, fields: Mapping[str, Any], *, now_ms: int
) -> None:
    """Aktualizuje pola czatu; klucze ⊆ UPDATABLE, inaczej ValueError (C1).

    dict/list → JSON (ensure_ascii=False); icon "" → NULL; zawsze update_time/update_date
    = now_ms — puste fields podbija więc tylko czasy.
    """
    unknown = sorted(set(fields) - UPDATABLE)
    if unknown:
        raise ValueError(f"fields not updatable: {unknown}")
    set_fragments: list[str] = []
    params: dict[str, Any] = {"id": chat_id, "now": now_ms, "now_date": from_ms(now_ms)}
    for key in UPDATABLE:
        if key not in fields:
            continue
        value = fields[key]
        if key == "icon" and value == "":
            value = None
        elif isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        set_fragments.append(f"{key} = :{key}")
        params[key] = value
    set_fragments.append("update_time = :now")
    set_fragments.append("update_date = :now_date")
    # Nazwy kolumn z białej listy UPDATABLE, wartości przez bindparamy — stąd f-string.
    await session.execute(
        text(f"UPDATE chats SET {', '.join(set_fragments)} WHERE id = :id"),  # noqa: S608
        params,
    )


async def delete(session: AsyncSession, chat_id: str) -> bool:
    """Usuwa czat — True gdy usunięto wiersz; kaskada FK czyści powiązane tabele (C1, R3)."""
    result = cast("CursorResult[Any]", await session.execute(_DELETE_SQL, {"id": chat_id}))
    return result.rowcount == 1


async def list_ids_by_owner(session: AsyncSession, owner_id: str) -> list[str]:
    """Id czatów właściciela, stabilnie po (create_time, id) (C1 — usuwanie masowe)."""
    rows = (await session.execute(_IDS_BY_OWNER_SQL, {"owner_id": owner_id})).all()
    return [row[0] for row in rows]
