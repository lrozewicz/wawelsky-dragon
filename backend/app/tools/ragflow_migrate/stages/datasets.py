"""Etap ``datasets``: tabela źródłowa ``knowledgebase`` → ``datasets`` (kontrakt §3 i §4, WP E4-6a).

Rozstrzyganie ``parser_id`` → ``chunk_method`` i ``parser_config`` jest czystą funkcją
(:func:`map_chunk_method`, :func:`split_parser_config`) — testowalną bez bazy (brief T6).
"""

import json
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import from_ms
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import Issue, RunContext, StageInventory, StageResult

#: Mapowanie ``knowledgebase.parser_id`` (RAGFlow v0.24) → ``chunk_method`` WD. Źródło listy
#: obsługiwanych metod: `app/domain/chunking/presets.py::_PRESETS`; metody z
#: `app/services/datasets.py::UNSUPPORTED_CHUNK_METHODS` (tag, knowledge_graph, resume, audio)
#: nie mają wpisu → ``None``.
CHUNK_METHODS: dict[str, str] = {
    "naive": "naive",
    "email": "email",
    "manual": "manual",
    "book": "book",
    "laws": "laws",
    "paper": "paper",
    "presentation": "presentation",
    "one": "one",
    "picture": "picture",
    "qa": "qa",
    "table": "table",
}

#: Klucz, pod którym ląduje reszta ``parser_config`` źródła (kontrakt §4).
LEGACY_PARSER_CONFIG_KEY = "wd_legacy_parser_config"

#: Klucze ``parser_config`` znane WD (kontrakt §4). Źródło: `app/services/datasets.py
#: ::DEFAULT_PARSER_CONFIG` oraz pola `app/api/ragflow/normalize/parser_config.py::ParserConfig`
#: (``extra="allow"``); wszystko poza tą listą trafia pod :data:`LEGACY_PARSER_CONFIG_KEY`.
KNOWN_PARSER_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        "auto_keywords",
        "auto_questions",
        "children_delimiter",
        "chunk_token_num",
        "compilation_template_group_id",
        "delimiter",
        "enable_children",
        "filename_embd_weight",
        "graphrag",
        "html4excel",
        "image_context_size",
        "layout_recognize",
        "llm_id",
        "pages",
        "parent_child",
        "raptor",
        "table_column_mode",
        "table_column_names",
        "table_column_roles",
        "table_context_size",
        "tag_kb_ids",
        "task_page_size",
        "topn_tags",
    }
)

#: Kolumny celu pisane przez etap (kolejność = lista INSERT); ``name_ci`` jest generowana.
COLUMNS: tuple[str, ...] = (
    "id",
    "tenant_id",
    "created_by",
    "name",
    "description",
    "avatar",
    "language",
    "embedding_model",
    "embedding_dim",
    "permission",
    "chunk_method",
    "parser_config",
    "similarity_threshold",
    "vector_similarity_weight",
    "pagerank",
    "document_count",
    "chunk_count",
    "token_num",
    "status",
    "create_time",
    "create_date",
    "update_time",
    "update_date",
)

#: Domyślny język datasetu, gdy źródło nie podaje (``DatasetService.create`` WD).
DEFAULT_LANGUAGE = "English"

#: Domyślny status datasetu (schemat WD: ``status CHAR(1) NOT NULL DEFAULT '1'``).
DEFAULT_STATUS = "1"

_COLUMN_LIST = ", ".join(COLUMNS)
# Nazwy kolumn pochodzą ze stałej ``COLUMNS`` (nie z danych), więc interpolacja jest bezpieczna.
_INSERT = f"INSERT INTO datasets ({_COLUMN_LIST}) VALUES ({', '.join(':' + c for c in COLUMNS)})"  # noqa: S608
_UPDATE = f"UPDATE datasets SET {', '.join(f'{c} = :{c}' for c in COLUMNS)} WHERE id = :id"  # noqa: S608
_SELECT_EXISTING = f"SELECT {_COLUMN_LIST} FROM datasets WHERE id IN :ids"  # noqa: S608
_SELECT_IDS = "SELECT id FROM datasets WHERE id IN :ids"


def map_chunk_method(parser_id: str) -> str | None:
    """``parser_id`` źródła → ``chunk_method`` WD; ``None`` = metoda nieobsługiwana w WD."""
    return CHUNK_METHODS.get(parser_id)


def split_parser_config(raw: Mapping[str, Any]) -> dict[str, Any]:
    """``parser_config`` źródła → konfig WD: znane klucze wprost, reszta pod kluczem legacy.

    Klucz legacy dodajemy tylko wtedy, gdy są nieznane klucze (kontrakt §4).
    """
    known = {key: value for key, value in raw.items() if key in KNOWN_PARSER_CONFIG_KEYS}
    legacy = {key: value for key, value in raw.items() if key not in KNOWN_PARSER_CONFIG_KEYS}
    if legacy:
        known[LEGACY_PARSER_CONFIG_KEY] = legacy
    return known


def raw_parser_config(value: Any) -> dict[str, Any]:
    """Kolumna ``parser_config`` źródła (tekst JSON albo ``dict``) → ``dict``; NULL → pusto."""
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    parsed: dict[str, Any] = json.loads(str(value))
    return parsed


def name_collision_groups(rows: Iterable[Mapping[str, Any]]) -> list[list[str]]:
    """Grupy id źródeł o tej samej nazwie (bez wielkości liter) w tym samym tenancie."""
    by_key: dict[tuple[str, str], list[str]] = {}
    for row in rows:
        key = (str(row["tenant_id"]), str(row["name"]).lower())
        by_key.setdefault(key, []).append(str(row["id"]))
    return [sorted(ids) for ids in by_key.values() if len(set(ids)) > 1]


def resolve_datasets(
    rows: list[dict[str, Any]],
    owner_ids: set[str],
    model_names: Mapping[str, str],
    dimensions: Mapping[str, int],
    now_ms: int,
) -> tuple[list[dict[str, Any]], list[Issue]]:
    """Wiersze ``knowledgebase`` → wartości kolumn ``datasets`` oraz uwagi (czysta funkcja).

    ``owner_ids`` to id użytkowników dostępnych w celu, ``model_names`` mapuje ``embd_id`` źródła
    na nazwę modelu WD, ``dimensions`` — ``embd_id`` na wymiar embeddingu. Wiersz, dla którego
    wykryto Issue ``critical``, nie trafia na listę wynikową (kontrakt §4).
    """
    groups = name_collision_groups(rows)
    collisions = {row_id for group in groups for row_id in group}
    issues: list[Issue] = [
        Issue(
            severity="critical",
            code="dataset_name_collision",
            message=(
                "nazwa datasetu powtarza się w tym samym tenancie pod różnymi id: "
                + ", ".join(group)
            ),
            ids=group,
        )
        for group in groups
    ]
    targets: list[dict[str, Any]] = []
    for row in rows:
        target, row_issues = _resolve_row(row, owner_ids, model_names, dimensions, now_ms)
        issues.extend(row_issues)
        blocked = str(row["id"]) in collisions or any(
            issue.severity == "critical" for issue in row_issues
        )
        if not blocked:
            targets.append(target)
    return targets, issues


def _resolve_row(
    row: Mapping[str, Any],
    owner_ids: set[str],
    model_names: Mapping[str, str],
    dimensions: Mapping[str, int],
    now_ms: int,
) -> tuple[dict[str, Any], list[Issue]]:
    """Wartości kolumn celu dla jednego wiersza ``knowledgebase`` i jego uwagi."""
    dataset_id = str(row["id"])
    tenant_id = str(row["tenant_id"])
    embd_id = str(row["embd_id"])
    embedding_model = model_names.get(embd_id)
    embedding_dim = dimensions.get(embd_id)
    chunk_method = map_chunk_method(str(row["parser_id"]))
    issues: list[Issue] = []
    if tenant_id not in owner_ids:
        issues.append(
            Issue(
                severity="critical",
                code="dataset_owner_missing",
                message="tenant datasetu nie ma właściciela w tabeli users celu — dataset pomijany",
                ids=[dataset_id],
            )
        )
    if chunk_method is None:
        issues.append(
            Issue(
                severity="critical",
                code="chunk_method_unsupported",
                message=(
                    f"`parser_id` {row['parser_id']!r} nie ma odpowiednika `chunk_method` w WD"
                    " — dataset nie jest pisany"
                ),
                ids=[dataset_id],
            )
        )
    if embedding_model is None or embedding_dim is None:
        issues.append(
            Issue(
                severity="critical",
                code="embedding_dim_unknown",
                message=(
                    f"nieznany wymiar embeddingu dla {embd_id!r} (brak w --model-map"
                    " i w tabeli models) — dataset nie jest pisany"
                ),
                ids=[dataset_id],
            )
        )
    return _target_row(row, chunk_method, embedding_model, embedding_dim, now_ms), issues


def _target_row(
    row: Mapping[str, Any],
    chunk_method: str | None,
    embedding_model: str | None,
    embedding_dim: int | None,
    now_ms: int,
) -> dict[str, Any]:
    """Wiersz źródła ``knowledgebase`` → wartości kolumn ``datasets`` (kontrakt §4)."""
    create_time = int(row["create_time"]) if row["create_time"] is not None else now_ms
    update_time = int(row["update_time"]) if row["update_time"] is not None else now_ms
    tenant_id = str(row["tenant_id"])
    return {
        "id": str(row["id"]),
        "tenant_id": tenant_id,
        "created_by": str(row["created_by"] or tenant_id),
        "name": row["name"],
        "description": row["description"] or None,
        "avatar": row["avatar"] or None,
        "language": row["language"] or DEFAULT_LANGUAGE,
        "embedding_model": embedding_model,
        "embedding_dim": embedding_dim,
        "permission": row["permission"],
        "chunk_method": chunk_method,
        "parser_config": json.dumps(
            split_parser_config(raw_parser_config(row["parser_config"])), ensure_ascii=False
        ),
        "similarity_threshold": row["similarity_threshold"],
        "vector_similarity_weight": row["vector_similarity_weight"],
        "pagerank": int(row["pagerank"]),
        "document_count": int(row["doc_num"]),
        "chunk_count": int(row["chunk_num"]),
        "token_num": int(row["token_num"]),
        "status": row["status"] or DEFAULT_STATUS,
        "create_time": create_time,
        "create_date": from_ms(create_time).replace(tzinfo=None),
        "update_time": update_time,
        "update_date": from_ms(update_time).replace(tzinfo=None),
    }


def model_metadata(
    rows: list[dict[str, Any]], ctx: RunContext, stored_dimensions: Mapping[str, int]
) -> tuple[dict[str, str], dict[str, int]]:
    """Nazwy (``embd_id`` → nazwa WD) i wymiary modeli embeddingu wierszy źródła.

    Nazwa: ``ctx.shared['model_names']`` (etap ``models``), inaczej mapa modeli. Wymiar: mapa,
    inaczej ``stored_dimensions`` (``models.dimension`` celu — ``plan`` podaje pusto, kontrakt §3).
    """
    shared_names = ctx.shared.get("model_names", {})
    names: dict[str, str] = {str(key): str(value) for key, value in shared_names.items()}
    dimensions: dict[str, int] = {}
    keys = dict.fromkeys(str(row["embd_id"]) for row in rows if row["embd_id"] is not None)
    for key in keys:
        entry = ctx.model_map.get(key)
        name = names.get(key) or (entry.name if entry is not None else None)
        if name is None:
            continue
        names[key] = name
        dimension = entry.dimension if entry is not None else None
        if dimension is None:
            dimension = stored_dimensions.get(name)
        if dimension is not None:
            dimensions[key] = dimension
    return names, dimensions


async def _owner_ids(session: AsyncSession, ctx: RunContext) -> set[str]:
    """Id właścicieli: z ``ctx.shared['user_ids']``, inaczej z celu (kontrakt §4, brief pkt 3)."""
    shared = ctx.shared.get("user_ids")
    if shared is not None:
        return {str(value) for value in shared}
    result = await session.execute(text("SELECT id FROM users"))
    return {str(value) for value in result.scalars().all()}


async def _stored_dimensions(session: AsyncSession) -> dict[str, int]:
    """Wymiary modeli embeddingu z tabeli ``models`` celu (nazwa → wymiar)."""
    result = await session.execute(
        text(
            "SELECT name, dimension FROM models"
            " WHERE model_type = 'embedding' AND dimension IS NOT NULL"
        )
    )
    return {str(name): int(dimension) for name, dimension in result.all()}


def _source_users(src: Source) -> set[str]:
    """Id użytkowników źródła — właściciele bez konsultowania celu (``plan``, kontrakt §3)."""
    return {str(row["id"]) for row in src.rows("user")}


def _unchanged(existing: Mapping[str, Any], computed: Mapping[str, Any]) -> bool:
    """True, gdy każda kolumna celu w wierszu istniejącym równa się wyliczonej (idempotencja)."""
    return all(str(existing[column]) == str(computed[column]) for column in COLUMNS)


async def _fetch_existing(session: AsyncSession, ids: list[str]) -> dict[str, Mapping[str, Any]]:
    """Wiersze celu dla podanych id (klucz = id); puste ``ids`` → pusta mapa."""
    if not ids:
        return {}
    statement = text(_SELECT_EXISTING).bindparams(bindparam("ids", expanding=True))
    result = await session.execute(statement, {"ids": ids})
    return {
        str(row["id"]): {column: row[column] for column in COLUMNS}
        for row in result.mappings().all()
    }


async def _target_ids(session: AsyncSession, ids: list[str]) -> set[str]:
    """Id ze zbioru ``ids`` obecne w ``datasets`` po etapie."""
    if not ids:
        return set()
    statement = text(_SELECT_IDS).bindparams(bindparam("ids", expanding=True))
    result = await session.execute(statement, {"ids": ids})
    return {str(value) for value in result.scalars().all()}


class DatasetsStage:
    """``knowledgebase`` → ``datasets`` z ``parser_id`` → ``chunk_method`` i ``parser_config``."""

    name = "datasets"

    def plan(self, src: Source, ctx: RunContext) -> StageInventory:
        """Inwentarz: licznik ``knowledgebase`` i uwagi (bez zapisu, kontrakt §4)."""
        rows = src.rows("knowledgebase")
        names, dimensions = model_metadata(rows, ctx, {})
        _targets, issues = resolve_datasets(rows, _source_users(src), names, dimensions, 0)
        return StageInventory(
            stage=self.name,
            source_counts={"knowledgebase": len(rows)},
            issues=issues,
            not_migrated={},
        )

    async def run(self, src: Source, session: AsyncSession, ctx: RunContext) -> StageResult:
        """Zapis ``knowledgebase`` → ``datasets``; ``--since`` zawęża wiersze do upsertu (§2)."""
        rows = src.rows_changed("knowledgebase", ctx.since_ms)
        owners = await _owner_ids(session, ctx)
        names, dimensions = model_metadata(rows, ctx, await _stored_dimensions(session))
        targets, issues = resolve_datasets(rows, owners, names, dimensions, ctx.clock.now_ms())
        source_ids = [str(row["id"]) for row in rows]
        existing = await _fetch_existing(session, source_ids)
        created = updated = skipped = 0
        for target in targets:
            if target["id"] not in existing:
                await session.execute(text(_INSERT), target)
                created += 1
            elif _unchanged(existing[target["id"]], target):
                skipped += 1
            else:
                await session.execute(text(_UPDATE), target)
                updated += 1
        skipped += len(rows) - len(targets)  # wiersze świadomie pominięte (Issue critical)
        present = await _target_ids(session, source_ids)
        return StageResult(
            stage=self.name,
            source_count=len(rows),
            created=created,
            updated=updated,
            skipped=skipped,
            target_count=len(present),
            issues=issues,
        )
