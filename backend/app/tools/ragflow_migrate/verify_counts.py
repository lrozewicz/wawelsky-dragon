"""Liczniki, osierocone wiersze, pliki, embedding i modele komendy ``verify`` (kontrakt E4-6c §5).

Podział tego modułu (m.in. ``CountsPart``) jest wewnętrzny dla T4 — kontrakt §5 ustala
sygnatury ``collect_parse``, ``run_contract_sample`` i ``run_verify``; ``collect_counts``
dostaje dodatkowo mapę modeli (``ModelMap``), bo reguła „model zmapowany” (kontrakt §3.2)
zależy od ``ctx.model_map``.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.tools.ragflow_migrate.model_map import ModelMap
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.keys import _key_id
from app.tools.ragflow_migrate.verify_types import CRITICAL_TABLES, CountEntry

#: Kolejność wpisów ``counts`` (kontrakt §3.2 — kolejność stała).
COUNT_TABLES: tuple[str, ...] = (
    "users",
    "datasets",
    "documents",
    "files",
    "chats",
    "chat_sessions",
    "assistant_access",
    "api_keys",
    "integrations",
)

#: Tabela WD → tabela źródłowa RAGFlow (kontrakt §3.2). ``assistant_access`` ma klucz złożony.
SOURCE_TABLES: dict[str, str] = {
    "users": "user",
    "datasets": "knowledgebase",
    "documents": "document",
    "files": "file",
    "chats": "dialog",
    "chat_sessions": "conversation",
    "api_keys": "api_token",
    "integrations": "ai_hub_sharepoint_integrations",
}

#: Tabela źródłowa dostępów do asystentów (klucz ``<email>:<dialog_id>``).
ACCESS_SOURCE = "ai_hub_user_assistant_access"

#: Wzorce ``documents.error`` opisujące problem z blobem (kontrakt §3.2).
BLOB_MISSING_PATTERN = "migration: blob missing%"
BLOB_SIZE_MISMATCH_PATTERN = "migration: blob size mismatch%"

_SELECT_MODEL_NAMES = text("SELECT name FROM models")
_SELECT_EMBEDDING_MISMATCH = text(
    "SELECT cd.chat_id FROM chat_datasets cd JOIN datasets d ON d.id = cd.dataset_id"
    " GROUP BY cd.chat_id HAVING COUNT(DISTINCT d.embedding_model) > 1"
)
_SELECT_SESSIONS = text("SELECT id, chat_id FROM chat_sessions")
_SELECT_ACCESS = text("SELECT email, chat_id FROM assistant_access")
_SELECT_ERROR_IDS = text("SELECT id FROM documents WHERE error LIKE :pattern")
#: ``SELECT id FROM <tabela>`` — zapytania dosłowne (żadnych nazw z danych).
_SELECT_IDS = {
    "users": text("SELECT id FROM users"),
    "datasets": text("SELECT id FROM datasets"),
    "documents": text("SELECT id FROM documents"),
    "files": text("SELECT id FROM files"),
    "chats": text("SELECT id FROM chats"),
    "api_keys": text("SELECT id FROM api_keys"),
    "integrations": text("SELECT id FROM integrations"),
}


@dataclass
class CountsPart:
    """Zbiór liczników ``verify`` wraz z sekcjami plików, modeli i osieroconych dostępów."""

    counts: list[CountEntry]
    missing_blob: list[str]
    size_mismatch: list[str]
    embedding_mismatch_chats: list[str]
    unmapped_models: list[str]
    orphan_access: list[str]


def _sorted_unique(values: Iterable[str]) -> list[str]:
    """Posortowany zbiór wartości (id) — determinizm raportu i ``missing_ids``."""
    return sorted(set(values))


def _access_key(email: object, dialog_id: object) -> str:
    """Klucz wiersza dostępu: ``<lower(email)>:<dialog_id>`` (kontrakt §3.2)."""
    return f"{str(email).lower()}:{dialog_id!s}"


def _dialog_ids(src: Source) -> set[str]:
    """Id dialogów źródła — wyznaczają wiersze osierocone (kontrakt §3.2)."""
    return {str(row["id"]) for row in src.rows("dialog")} if src.has_table("dialog") else set()


def _source_ids(src: Source, table: str, dialog_ids: set[str]) -> list[str]:
    """Posortowane id źródła dla tabeli WD; brak tabeli źródła → pusto (``source=0``).

    ``conversation`` (``chat_sessions``) pomija wiersze wskazujące dialog spoza źródła —
    osierocone nie są rozbieżnością (kontrakt §3.2).
    """
    source_table = SOURCE_TABLES[table]
    if not src.has_table(source_table):
        return []
    rows = src.rows(source_table)
    if table == "api_keys":
        return _sorted_unique(_key_id(str(row["token"])) for row in rows)
    if table == "chat_sessions":
        return _sorted_unique(str(row["id"]) for row in rows if str(row["dialog_id"]) in dialog_ids)
    return _sorted_unique(str(row["id"]) for row in rows)


def _source_access(src: Source, dialog_ids: set[str]) -> tuple[list[str], list[str]]:
    """Klucze dostępów źródła i klucze wierszy osieroconych (dialog spoza źródła).

    Brak tabeli źródłowej → ``([], [])`` (kontrakt §3.2: tabela nieobecna → ``source=0``).
    """
    if not src.has_table(ACCESS_SOURCE):
        return [], []
    keys: list[str] = []
    orphans: list[str] = []
    for row in src.rows(ACCESS_SOURCE):
        key = _access_key(row["email"], row["dialog_id"])
        if str(row["dialog_id"]) in dialog_ids:
            keys.append(key)
        else:
            orphans.append(key)
    return _sorted_unique(keys), _sorted_unique(orphans)


async def _scalar_ids(session: AsyncSession, table: str) -> set[str]:
    """Zbiór ``id`` tabeli celu."""
    result = await session.execute(_SELECT_IDS[table])
    return {str(value) for value in result.scalars().all()}


async def _target_ids(session: AsyncSession, dialog_ids: set[str]) -> dict[str, set[str]]:
    """Zbiory kluczy celu per tabela WD — te same kryteria co po stronie źródła (§3.2)."""
    sessions = (await session.execute(_SELECT_SESSIONS)).all()
    access = (await session.execute(_SELECT_ACCESS)).all()
    return {
        "users": await _scalar_ids(session, "users"),
        "datasets": await _scalar_ids(session, "datasets"),
        "documents": await _scalar_ids(session, "documents"),
        "files": await _scalar_ids(session, "files"),
        "chats": await _scalar_ids(session, "chats"),
        "chat_sessions": {str(row[0]) for row in sessions if str(row[1]) in dialog_ids},
        "assistant_access": {
            _access_key(row[0], row[1]) for row in access if str(row[1]) in dialog_ids
        },
        "api_keys": await _scalar_ids(session, "api_keys"),
        "integrations": await _scalar_ids(session, "integrations"),
    }


def _count_entry(table: str, source_ids: list[str], target_ids: set[str]) -> CountEntry:
    """Porównanie id źródła i celu dla jednej tabeli WD (kontrakt §3.2)."""
    missing = sorted(set(source_ids) - target_ids)
    return CountEntry(
        table=table,
        source=len(source_ids),
        target=len(target_ids),
        missing_ids=missing,
        critical=bool(missing) and table in CRITICAL_TABLES,
    )


async def _error_ids(session: AsyncSession, pattern: str) -> list[str]:
    """Id dokumentów celu, których ``error`` pasuje do wzorca ``LIKE`` (id posortowane)."""
    result = await session.execute(_SELECT_ERROR_IDS, {"pattern": pattern})
    return sorted(str(value) for value in result.scalars().all())


async def _embedding_mismatch_chats(session: AsyncSession) -> list[str]:
    """Id czatów celu, których datasety mają więcej niż jeden różny ``embedding_model``."""
    result = await session.execute(_SELECT_EMBEDDING_MISMATCH)
    return sorted(str(value) for value in result.scalars().all())


async def _target_model_names(session: AsyncSession) -> set[str]:
    """Nazwy modeli obecnych w tabeli ``models`` celu."""
    result = await session.execute(_SELECT_MODEL_NAMES)
    return {str(value) for value in result.scalars().all()}


def _used_model_keys(src: Source) -> list[str]:
    """Klucze ``llm_name@factory`` użyte w źródle: ``dialog`` i ``knowledgebase`` (§3.2).

    Bierzemy ``llm_id`` i ``rerank_id`` dialogów oraz ``embd_id`` baz wiedzy; puste wartości
    i brakujące tabele źródła pomijamy (jak ``stages/models.py::collect_used``).
    """
    values: list[object] = []
    if src.has_table("knowledgebase"):
        values += [row.get("embd_id") for row in src.rows("knowledgebase")]
    if src.has_table("dialog"):
        for row in src.rows("dialog"):
            values += [row.get("llm_id"), row.get("rerank_id")]
    return _sorted_unique(
        str(value).strip() for value in values if value is not None and str(value).strip()
    )


def _unmapped_models(src: Source, model_map: ModelMap, target_names: set[str]) -> list[str]:
    """Klucze użyte w źródle bez odpowiednika: nie ma ich w mapie modeli ani w ``models`` celu.

    Reguła jak w ``stages/models.py::resolve_models``: nazwa modelu WD to ``name`` z mapy,
    a bez wpisu — goła ``llm_name``.
    """
    unmapped: list[str] = []
    for key in _used_model_keys(src):
        if model_map.get(key) is not None:
            continue
        if key.partition("@")[0] in target_names:
            continue
        unmapped.append(key)
    return sorted(unmapped)


async def collect_counts(src: Source, session: AsyncSession, model_map: ModelMap) -> CountsPart:
    """Liczniki źródło→cel oraz pliki, embedding, modele i osierocone dostępy (kontrakt §3.2)."""
    dialog_ids = _dialog_ids(src)
    access_ids, orphan_access = _source_access(src, dialog_ids)
    target = await _target_ids(session, dialog_ids)
    counts = [
        _count_entry(
            table,
            access_ids if table == "assistant_access" else _source_ids(src, table, dialog_ids),
            target[table],
        )
        for table in COUNT_TABLES
    ]
    return CountsPart(
        counts=counts,
        missing_blob=await _error_ids(session, BLOB_MISSING_PATTERN),
        size_mismatch=await _error_ids(session, BLOB_SIZE_MISMATCH_PATTERN),
        embedding_mismatch_chats=await _embedding_mismatch_chats(session),
        unmapped_models=_unmapped_models(src, model_map, await _target_model_names(session)),
        orphan_access=orphan_access,
    )
