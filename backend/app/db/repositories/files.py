"""Repozytorium tabel `files` i `file2document` (K16 §1, CONTRACT E4-5a §D2).

Core ``text()`` z parametrami wiązanymi, bez ``commit``/``rollback`` — transakcję otwiera
wywołująca (``app.db.uow.transaction``). Wiersze ``source_type='knowledgebase'`` (wizualizacje
dokumentów datasetów z migracji RAGFlow) są niewidoczne dla operacji menedżera plików;
jedyny wyjątek to ``get_root``, gdzie filtr jest zbędny (root ma ``source_type='local'``).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, cast

from sqlalchemy import bindparam, text
from sqlalchemy.engine import CursorResult, RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import from_ms

# ``files.id``/``files.parent_id`` mają kolację `ascii_bin`, a parametr z żądania jest w
# `utf8mb4_*` — wartość spoza ASCII wywraca porównanie błędem 1267 („Illegal mix of
# collations"). Id-y z żądania porównujemy więc przez ``CAST(… AS BINARY)`` (jak `searches.py`).
# `tenant_id` pochodzi z tokenu (hex ASCII), więc CAST nie jest potrzebny.

_LOCK_USER_SQL = text("SELECT id FROM users WHERE id = CAST(:tenant_id AS BINARY) FOR UPDATE")

_GET_ROOT_SQL = text(
    "SELECT id, tenant_id, created_by, parent_id, name, type, size, location, source_type,"
    " create_time, create_date, update_time, update_date FROM files"
    " WHERE parent_id IS NULL AND name = '/' AND tenant_id = CAST(:tenant_id AS BINARY)"
)

_GET_SQL = text(
    "SELECT id, tenant_id, created_by, parent_id, name, type, size, location, source_type,"
    " create_time, create_date, update_time, update_date FROM files"
    " WHERE id = CAST(:file_id AS BINARY) AND source_type <> 'knowledgebase'"
)

_GET_MANY_SQL = text(
    "SELECT id, tenant_id, created_by, parent_id, name, type, size, location, source_type,"
    " create_time, create_date, update_time, update_date FROM files"
    " WHERE CAST(id AS BINARY) IN :file_ids AND source_type <> 'knowledgebase'"
).bindparams(bindparam("file_ids", expanding=True))

_INSERT_SQL = text(
    "INSERT INTO files (id, tenant_id, created_by, parent_id, name, type, size, location,"
    " source_type, create_time, create_date, update_time, update_date)"
    " VALUES (:id, :tenant_id, :created_by, :parent_id, :name, :type, :size, :location,"
    " :source_type, :create_time, :create_date, :update_time, :update_date)"
)

_FIND_CHILD_SQL = text(
    "SELECT id, tenant_id, created_by, parent_id, name, type, size, location, source_type,"
    " create_time, create_date, update_time, update_date FROM files"
    " WHERE tenant_id = :tenant_id AND parent_id = CAST(:parent_id AS BINARY) AND name = :name"
    " AND source_type <> 'knowledgebase'"
)

# Rekurencyjne CTE (MariaDB >= 10.2): wszystkie widoczne potomki folderu, dowolnie głęboko.
_LIST_ALL_CHILDREN_SQL = text(
    "WITH RECURSIVE tree (id) AS ("
    " SELECT id FROM files WHERE parent_id = CAST(:parent_id AS BINARY)"
    " AND source_type <> 'knowledgebase'"
    " UNION ALL"
    " SELECT f.id FROM files AS f JOIN tree AS t ON f.parent_id = t.id"
    " WHERE f.source_type <> 'knowledgebase'"
    ")"
    " SELECT f.id, f.tenant_id, f.created_by, f.parent_id, f.name, f.type, f.size, f.location,"
    " f.source_type, f.create_time, f.create_date, f.update_time, f.update_date"
    " FROM files AS f JOIN tree AS t ON f.id = t.id ORDER BY f.create_time, f.id"
)

# Zasięg `keywords`: folder i widoczni potomkowie (upstream `get_subtree_ids`), bez niego samego.
_KEYWORDS_SUBTREE_PREFIX = (
    "WITH RECURSIVE tree (id) AS ("
    " SELECT CAST(:parent_id AS BINARY) AS id"
    " UNION ALL"
    " SELECT f.id FROM files AS f JOIN tree AS t ON f.parent_id = t.id"
    " WHERE f.source_type <> 'knowledgebase'"
    ")"
)

_FOLDERS_WITH_CHILD_FOLDER_SQL = text(
    "SELECT DISTINCT parent_id FROM files WHERE CAST(parent_id AS BINARY) IN :folder_ids"
    " AND type = 'folder' AND id <> parent_id AND source_type <> 'knowledgebase'"
).bindparams(bindparam("folder_ids", expanding=True))

_SET_PARENT_SQL = text(
    "UPDATE files SET parent_id = CAST(:parent_id AS BINARY), update_time = :now,"
    " update_date = :now_date WHERE id = CAST(:file_id AS BINARY)"
)

_SET_NAME_SQL = text(
    "UPDATE files SET name = :name, update_time = :now, update_date = :now_date"
    " WHERE id = CAST(:file_id AS BINARY)"
)

_DELETE_SQL = text("DELETE FROM files WHERE id = CAST(:file_id AS BINARY)")

_INSERT_LINK_SQL = text(
    "INSERT INTO file2document (id, file_id, document_id, create_time, create_date,"
    " update_time, update_date)"
    " VALUES (:id, :file_id, :document_id, :now, :now_date, :now, :now_date)"
)

_LIST_LINKS_SQL = text(
    "SELECT id, file_id, document_id FROM file2document"
    " WHERE file_id = CAST(:file_id AS BINARY) ORDER BY create_time, id"
)

# Upstream (`FileService.get_kb_id_by_file_id`) zwraca na każdy wiersz `file2document`
# element `{kb_id, kb_name, document_id}` (bez deduplikacji po datasecie); bez ORDER BY —
# WD sortuje deterministycznie po czasie i id wiązania (DEC-178).
_KBS_INFO_SQL = text(
    "SELECT l.file_id AS file_id, d.id AS kb_id, d.name AS kb_name, l.document_id AS document_id"
    " FROM file2document AS l"
    " JOIN documents AS doc ON doc.id = l.document_id"
    " JOIN datasets AS d ON d.id = doc.dataset_id"
    " WHERE CAST(l.file_id AS BINARY) IN :file_ids ORDER BY l.create_time, l.id"
).bindparams(bindparam("file_ids", expanding=True))

_DELETE_LINKS_BY_DOCUMENT_SQL = text(
    "DELETE FROM file2document WHERE document_id = CAST(:document_id AS BINARY)"
)

# Biała lista kolumn orderby — tekst od użytkownika nigdy nie trafia do SQL wprost (K16).
_ORDERBY: Final[dict[str, str]] = {
    "create_time": "create_time",
    "update_time": "update_time",
    "name": "name",
    "size": "size",
    "type": "type",
}
_DEFAULT_ORDERBY = "create_time"


@dataclass(frozen=True)
class FileRow:
    """Wiersz `files` (CONTRACT §D2)."""

    id: str
    tenant_id: str
    created_by: str
    parent_id: str | None
    name: str
    type: str
    size: int
    location: str | None
    source_type: str
    create_time: int
    create_date: datetime
    update_time: int
    update_date: datetime


@dataclass(frozen=True)
class LinkRow:
    """Wiersz `file2document` (CONTRACT §D2)."""

    id: str
    file_id: str
    document_id: str


def _row(row: RowMapping) -> FileRow:
    """RowMapping → FileRow (daty zostają datetime)."""
    return FileRow(
        id=row["id"],
        tenant_id=row["tenant_id"],
        created_by=row["created_by"],
        parent_id=row["parent_id"],
        name=row["name"],
        type=row["type"],
        size=int(row["size"]),
        location=row["location"],
        source_type=row["source_type"],
        create_time=int(row["create_time"]),
        create_date=row["create_date"],
        update_time=int(row["update_time"]),
        update_date=row["update_date"],
    )


def _like_keywords(keywords: str) -> str:
    """Wzorzec LIKE dla keywords: %…% po LOWER, znaki \\, %, _ dosłownie (§D2)."""
    escaped = keywords.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped.lower()}%"


async def lock_user(session: AsyncSession, tenant_id: str) -> None:
    """X-blokada wiersza użytkownika — serializuje leniwe tworzenie roota (§D1.2)."""
    await session.execute(_LOCK_USER_SQL, {"tenant_id": tenant_id})


async def get_root(session: AsyncSession, tenant_id: str) -> FileRow | None:
    """Root użytkownika (`parent_id NULL`, `name '/'`); None gdy nie ma (§D1.2)."""
    found = (await session.execute(_GET_ROOT_SQL, {"tenant_id": tenant_id})).mappings().first()
    return _row(found) if found is not None else None


async def get(session: AsyncSession, file_id: str) -> FileRow | None:
    """Widoczny plik/folder po id; None gdy brak lub `knowledgebase` (§D2)."""
    found = (await session.execute(_GET_SQL, {"file_id": file_id})).mappings().first()
    return _row(found) if found is not None else None


async def parent_of(session: AsyncSession, row: FileRow) -> FileRow:
    """Rodzic wiersza listingu; root wskazuje na siebie (upstream ``get_parent_folder``, §D1.2)."""
    parent = row if row.parent_id is None else await get(session, row.parent_id)
    if parent is None:
        raise LookupError(f"parent row not found: {row.parent_id}")
    return parent


async def get_many(session: AsyncSession, file_ids: Sequence[str]) -> list[FileRow]:
    """Widoczne wiersze dla id-ów, bez gwarancji kolejności; ``[]`` → ``[]`` (§D2)."""
    if not file_ids:
        return []
    found = (await session.execute(_GET_MANY_SQL, {"file_ids": list(file_ids)})).mappings().all()
    return [_row(row) for row in found]


async def insert(session: AsyncSession, row: FileRow) -> None:
    """Wstawia wiersz `files` — wszystkie kolumny z ``row`` (§D2)."""
    await session.execute(
        _INSERT_SQL,
        {
            "id": row.id,
            "tenant_id": row.tenant_id,
            "created_by": row.created_by,
            "parent_id": row.parent_id,
            "name": row.name,
            "type": row.type,
            "size": row.size,
            "location": row.location,
            "source_type": row.source_type,
            "create_time": row.create_time,
            "create_date": row.create_date,
            "update_time": row.update_time,
            "update_date": row.update_date,
        },
    )


async def find_child(
    session: AsyncSession, tenant_id: str, parent_id: str, name: str
) -> FileRow | None:
    """Widoczne dziecko o nazwie ``name`` w folderze ``parent_id`` (tenant); inaczej None."""
    found = (
        (
            await session.execute(
                _FIND_CHILD_SQL,
                {"tenant_id": tenant_id, "parent_id": parent_id, "name": name},
            )
        )
        .mappings()
        .first()
    )
    return _row(found) if found is not None else None


async def list_children(  # noqa: PLR0913 — sygnatura z kontraktu §D2
    session: AsyncSession,
    parent_id: str,
    tenant_id: str,
    *,
    keywords: str | None,
    orderby: str,
    desc: bool,
    page: int,
    page_size: int,
) -> tuple[list[FileRow], int]:
    """Strona widocznych dzieci folderu + liczba pasujących; ``keywords`` — całego poddrzewa (§D2).

    Port upstream ``get_by_pf_id``: ``keywords`` szuka w folderze i widocznych potomkach
    (CTE ``_KEYWORDS_SUBTREE_PREFIX``), LIKE po LOWER(name) z escape ``%``/``_``; ``orderby``
    z białej listy (inne → create_time), stabilnie po id; ``page``/``page_size`` <= 0 bez LIMIT.
    """
    column = _ORDERBY.get(orderby, _ORDERBY[_DEFAULT_ORDERBY])
    direction = "DESC" if desc else "ASC"
    params: dict[str, Any] = {"parent_id": parent_id, "tenant_id": tenant_id}
    if keywords:
        prefix = _KEYWORDS_SUBTREE_PREFIX
        params["kw"] = _like_keywords(keywords)
        conditions = (
            "tenant_id = :tenant_id AND source_type <> 'knowledgebase'"
            " AND parent_id IN (SELECT id FROM tree)"
            " AND LOWER(name) LIKE :kw ESCAPE '\\\\'"
        )
    else:
        prefix = ""
        conditions = (
            "parent_id = CAST(:parent_id AS BINARY) AND tenant_id = :tenant_id"
            " AND source_type <> 'knowledgebase'"
        )
    count_clause = text(f"{prefix} SELECT COUNT(*) FROM files WHERE {conditions}")  # noqa: S608
    rows_sql = (
        f"{prefix} SELECT id, tenant_id, created_by, parent_id, name, type, size, location,"  # noqa: S608
        " source_type, create_time, create_date, update_time, update_date"
        f" FROM files WHERE {conditions}"
        f" ORDER BY {column} {direction}, id {direction}"
    )
    if page > 0 and page_size > 0:
        rows_sql += " LIMIT :limit OFFSET :offset"
        params["limit"] = page_size
        params["offset"] = (page - 1) * page_size
    total = int((await session.execute(count_clause, params)).scalar_one())
    found = (await session.execute(text(rows_sql), params)).mappings().all()
    return [_row(row) for row in found], total


async def list_all_children(session: AsyncSession, parent_id: str) -> list[FileRow]:
    """Wszystkie widoczne potomki folderu, rekurencyjnie (kolejność: czas, id; §D2)."""
    found = (
        (await session.execute(_LIST_ALL_CHILDREN_SQL, {"parent_id": parent_id})).mappings().all()
    )
    return [_row(row) for row in found]


async def folders_with_child_folder(session: AsyncSession, folder_ids: Sequence[str]) -> set[str]:
    """Podzbiór ``folder_ids``, które mają widoczne dziecko typu ``folder`` (§D2)."""
    if not folder_ids:
        return set()
    found = (
        await session.execute(_FOLDERS_WITH_CHILD_FOLDER_SQL, {"folder_ids": list(folder_ids)})
    ).all()
    return {row[0] for row in found}


async def set_parent(session: AsyncSession, file_id: str, parent_id: str, now_ms: int) -> None:
    """Przenosi wiersz do folderu ``parent_id`` i podbija czasy (§D2)."""
    await session.execute(
        _SET_PARENT_SQL,
        {"file_id": file_id, "parent_id": parent_id, "now": now_ms, "now_date": from_ms(now_ms)},
    )


async def set_name(session: AsyncSession, file_id: str, name: str, now_ms: int) -> None:
    """Zmienia nazwę wiersza i podbija czasy (§D2)."""
    await session.execute(
        _SET_NAME_SQL,
        {"file_id": file_id, "name": name, "now": now_ms, "now_date": from_ms(now_ms)},
    )


async def delete(session: AsyncSession, file_id: str) -> int:
    """Twardo usuwa wiersz; zwraca liczbę usuniętych wierszy (FK kasuje dzieci/wiązania, §D2)."""
    result = await session.execute(_DELETE_SQL, {"file_id": file_id})
    return int(cast("CursorResult[Any]", result).rowcount)


async def insert_link(
    session: AsyncSession, *, id: str, file_id: str, document_id: str, now_ms: int
) -> None:
    """Wstawia wiązanie `file2document` plik↔dokument (§D2)."""
    await session.execute(
        _INSERT_LINK_SQL,
        {
            "id": id,
            "file_id": file_id,
            "document_id": document_id,
            "now": now_ms,
            "now_date": from_ms(now_ms),
        },
    )


async def list_links(session: AsyncSession, file_id: str) -> list[LinkRow]:
    """Wiązania pliku, w kolejności czasu i id (§D2)."""
    found = (await session.execute(_LIST_LINKS_SQL, {"file_id": file_id})).mappings().all()
    return [
        LinkRow(id=row["id"], file_id=row["file_id"], document_id=row["document_id"])
        for row in found
    ]


async def kbs_info(
    session: AsyncSession, file_ids: Sequence[str]
) -> dict[str, list[dict[str, str]]]:
    """file_id → lista datasetów zlinkowanych dokumentów (§D2, DEC-178).

    Element ma klucze ``kb_id`` (id datasetu), ``kb_name`` (nazwa datasetu) i ``document_id``
    — dosłownie upstream ``FileService.get_kb_id_by_file_id``. Plik bez wiązań nie dostaje
    klucza (``.get(file_id, [])`` po stronie wywołującego); ``[]`` → ``{}`` bez SQL.
    """
    if not file_ids:
        return {}
    rows = (await session.execute(_KBS_INFO_SQL, {"file_ids": list(file_ids)})).all()
    info: dict[str, list[dict[str, str]]] = {}
    for file_id, kb_id, kb_name, document_id in rows:
        info.setdefault(file_id, []).append(
            {"kb_id": kb_id, "kb_name": kb_name, "document_id": document_id}
        )
    return info


async def delete_links_by_document(session: AsyncSession, document_id: str) -> int:
    """Usuwa wiązania wskazujące dokument; zwraca liczbę usuniętych wierszy (§D2)."""
    result = await session.execute(_DELETE_LINKS_BY_DOCUMENT_SQL, {"document_id": document_id})
    return int(cast("CursorResult[Any]", result).rowcount)
