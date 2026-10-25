"""Zapytania i aktualizacje dokumentów dla API (kontrakt E1-9a C2.1) — Core ``text()``.

Bez ``commit``/``rollback`` — transakcję otwiera wywołująca (``app.db.uow.transaction``).
Nowy plik poza K11 §1 (decyzja TL, C0 p. 9) — ``documents.py`` pozostaje bez zmian.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import from_ms
from app.db.repositories.documents import DocumentRow, _json_column, _row
from app.domain.policy import VisibilityFilter
from app.domain.retrieval.metadata import MetadataCondition, MetadataPushdown

__all__ = [
    "META_COLUMNS",
    "DocumentListQuery",
    "exists",
    "ids_in_dataset",
    "list_page",
    "meta_fields_by_document",
    "names_in_dataset",
    "run_counts",
    "thumbnails",
    "update_meta",
]


@dataclass(frozen=True)
class DocumentListQuery:
    """Parametry GET /datasets/{id}/documents po przepisaniu przez normalize (C2.1)."""

    page: int
    page_size: int
    orderby: str
    desc: bool
    document_id: str | None = None
    name: str | None = None
    keywords: str | None = None
    ids: tuple[str, ...] = ()  # runs jako kody '0'..'5'
    runs: tuple[str, ...] = ()
    suffixes: tuple[str, ...] = ()
    # Zakres czasu tworzenia (ms); 0 = brak granicy — filtr PO stronie wyniku, jak upstream
    # ``document_api.py:972-975`` (lista dokumentów filtra czasu nie zawiera w ``total``).
    create_time_from: int = 0
    create_time_to: int = 0
    # Warunek ``metadata_condition`` z query (K11 §10f p. 1): usługa wylicza z niego zbiór
    # pasujących id i przekazuje do ``list_page`` (zawęża ``total`` i stronę).
    meta_condition: MetadataCondition | None = None


# Zbiór kolumn jak _SELECT_SQL w documents.py (prefiks d.) + nickname twórcy (C2.1);
# IFNULL — brak użytkownika → nickname "".
_PAGE_COLUMNS = (
    "SELECT d.id, d.dataset_id, d.created_by, d.name, d.suffix, d.type, d.size, d.location,"
    " d.content_hash, d.source_type, d.source_ref, d.chunk_method, d.parser_config, d.run,"
    " d.progress, d.progress_msg, d.error, d.process_begin_at, d.process_duration,"
    " d.chunk_count, d.token_count, d.enabled, d.meta_fields, d.thumbnail, d.create_time,"
    " d.create_date, d.update_time, d.update_date, IFNULL(u.nickname, '') AS nickname"
    " FROM documents d LEFT JOIN users u ON u.id = d.created_by"
)

# ORDER BY: wyłącznie te kolumny (kontrakt C2.1, T3: + name); inna → ValueError.
_ORDER_COLUMNS = frozenset({"create_time", "update_time", "name"})

# Biała lista kolumn update_meta (kontrakt C2.1); inna → ValueError. Publiczna —
# usługa filtruje fields do tej listy (C2.2).
META_COLUMNS = frozenset({"name", "chunk_method", "parser_config", "enabled", "meta_fields"})

# ``documents.id`` ma kolację `ascii_bin` (schemat WD), a parametr z żądania jest
# w `utf8mb4_*` — MySQL wywraca porównanie wartością spoza ASCII błędem 1267/1270
# („Illegal mix of collations") i API oddawało `code 100` zamiast 102. Porównania po
# `id` idą więc przez `CAST(… AS BINARY)` (porównanie bajtowe, bez kolacji); dla
# parametru zostaje przy tym indeks `PRIMARY` (sprawdzone `EXPLAIN`-em na MariaDB
# stosu testowego), dla listy `IN` rzutujemy kolumnę (cast elementu listy nie da się
# wyrazić w `text()` z `expanding=True`).
_IDS_SQL = text(
    "SELECT id FROM documents WHERE dataset_id = :dataset_id AND CAST(id AS BINARY) IN :ids"
).bindparams(bindparam("ids", expanding=True))

_NAMES_SQL = text("SELECT name FROM documents WHERE dataset_id = :dataset_id")

_RUN_COUNTS_SQL = text(
    "SELECT run, COUNT(*) AS cnt FROM documents WHERE dataset_id = :dataset_id GROUP BY run"
)

# Thumbnails (E2-1 DOC2): wiersz dokumentu + filtr widoczności jego datasetu (07 §7).
_THUMBNAILS_SQL = (
    "SELECT d.id, d.dataset_id, d.thumbnail FROM documents d JOIN datasets k ON k.id = d.dataset_id"
    " WHERE CAST(d.id AS BINARY) IN :ids"  # kolacja: patrz „_IDS_SQL"
)

# Miniatura już wbudowana w base64 — upstream nie dokleja do niej ścieżki (DOC:1329).
_BASE64_THUMBNAIL_PREFIX = "data:image/png;base64,"
_THUMBNAILS_VISIBLE = " AND (k.tenant_id IN :owners OR (:team AND k.permission = 'team'))"

# Metadane dokumentów datasetu (DS3); ORDER BY id jak upstream get_flatted_meta_by_kbs.
_META_SELECT = "SELECT id, meta_fields FROM documents"


async def list_page(
    session: AsyncSession,
    dataset_id: str,
    q: DocumentListQuery,
    *,
    allowed_ids: frozenset[str] | None = None,
) -> tuple[list[tuple[DocumentRow, str]], int]:
    """Strona listy dokumentów datasetu + total; wiersz z nickname twórcy (C2.1).

    Filtry: document_id → id =; name → name =; keywords → LIKE %LOWER%; ids/runs/
    suffixes → IN. orderby ∈ {create_time, update_time, name} (biała lista), kierunek wg
    ``desc``, remis po id. ``name`` sortuje wg kolacji kolumny (utf8mb4_uca1400_ai_ci —
    bez wielkości liter; remis rozstrzyga ``d.id``). page_size == 0 → pusta lista, total liczony.

    ``allowed_ids`` (z ``metadata_condition``): zbiór dopuszczonych identyfikatorów dokładany
    jako ``CAST(d.id AS BINARY) IN …`` do zapytania i licznika; pusty zbiór → brak wierszy
    (``IN ()`` byłoby błędem SQL). Zawęża więc i ``total``, i stronę.
    """
    if q.orderby not in _ORDER_COLUMNS:
        raise ValueError(f"invalid orderby: {q.orderby!r}")
    if allowed_ids is not None and not allowed_ids:
        return [], 0
    conditions = ["d.dataset_id = :dataset_id"]
    params: dict[str, Any] = {"dataset_id": dataset_id}
    if q.document_id is not None:
        conditions.append("d.id = CAST(:document_id AS BINARY)")  # kolacja: patrz „_IDS_SQL"
        params["document_id"] = q.document_id
    if q.name is not None:
        conditions.append("d.name = :name")
        params["name"] = q.name
    if q.keywords:
        conditions.append("LOWER(d.name) LIKE CONCAT('%', LOWER(:keywords), '%')")
        params["keywords"] = q.keywords
    id_columns = (("ids", "CAST(d.id AS BINARY)"), ("runs", "d.run"), ("suffixes", "d.suffix"))
    for field, column in id_columns:
        values = getattr(q, field)
        if values:
            conditions.append(column + " IN :" + field)
            params[field] = list(values)
    if allowed_ids is not None:
        conditions.append("CAST(d.id AS BINARY) IN :allowed_ids")  # kolacja: patrz „_IDS_SQL"
        params["allowed_ids"] = sorted(allowed_ids)
    condition = " WHERE " + " AND ".join(conditions)
    direction = "DESC" if q.desc else "ASC"
    order = " ORDER BY d." + q.orderby + " " + direction + ", d.id"
    page_stmt = text(_PAGE_COLUMNS + condition + order + " LIMIT :limit OFFSET :offset")
    count_stmt = text("SELECT COUNT(*) FROM documents d" + condition)  # noqa: S608 — białe listy
    expanding_fields = [field for field in ("ids", "runs", "suffixes") if getattr(q, field)]
    if allowed_ids is not None:
        expanding_fields.append("allowed_ids")
    for stmt_field in expanding_fields:
        page_stmt = page_stmt.bindparams(bindparam(stmt_field, expanding=True))
        count_stmt = count_stmt.bindparams(bindparam(stmt_field, expanding=True))
    total = cast(int, (await session.execute(count_stmt, params)).scalar_one())
    rows: list[tuple[DocumentRow, str]] = []
    if q.page_size > 0:
        found = (
            (
                await session.execute(
                    page_stmt,
                    {**params, "limit": q.page_size, "offset": (q.page - 1) * q.page_size},
                )
            )
            .mappings()
            .all()
        )
        rows = [(_row(row), str(row["nickname"])) for row in found]
    return rows, total


async def exists(
    session: AsyncSession,
    dataset_id: str,
    *,
    document_id: str | None = None,
    name: str | None = None,
) -> bool:
    """Czy w datasecie jest dokument o tym id/nazwie (istnienie filtra listy, DOC:918-927).

    Istnienie sprawdzamy OSOBNO od wyniku listowania (wzór DEC-062 p. 3 dla datasetów):
    puste przecięcie filtrów listy to ``code 0``, a 102 znaczy „nie ma takiego dokumentu".
    """
    conditions = ["dataset_id = :dataset_id"]
    params: dict[str, Any] = {"dataset_id": dataset_id}
    if document_id is not None:
        conditions.append("id = CAST(:document_id AS BINARY)")  # kolacja: patrz „_IDS_SQL"
        params["document_id"] = document_id
    if name is not None:
        conditions.append("name = :name")
        params["name"] = name
    stmt = text("SELECT 1 FROM documents WHERE " + " AND ".join(conditions) + " LIMIT 1")  # noqa: S608
    return (await session.execute(stmt, params)).first() is not None


async def ids_in_dataset(
    session: AsyncSession, dataset_id: str, document_ids: Sequence[str]
) -> set[str]:
    """Podzbiór document_ids należący do datasetu; [] → zbiór pusty bez SQL (C2.1)."""
    if not document_ids:
        return set()
    rows = (
        (await session.execute(_IDS_SQL, {"dataset_id": dataset_id, "ids": list(document_ids)}))
        .scalars()
        .all()
    )
    return {str(row) for row in rows}


async def names_in_dataset(session: AsyncSession, dataset_id: str) -> set[str]:
    """Nazwy wszystkich dokumentów datasetu, małymi literami (C2.1) — deduplikacja uploadu."""
    rows = (await session.execute(_NAMES_SQL, {"dataset_id": dataset_id})).scalars().all()
    return {str(row).lower() for row in rows}


async def exact_names_in_dataset(session: AsyncSession, dataset_id: str) -> set[str]:
    """Oryginalne nazwy dokumentów datasetu (PATCH dokumentu: duplikat nazwy, VU:1122-1124).

    Kolumna ``name`` ma kolację ``utf8mb4_uca1400_ai_ci``, więc ``=`` (i ``LOWER``) nie
    odróżniają wielkości liter — „duplikat nazwy" rozstrzygamy porównaniem w Pythonie
    (DEC-088 p. 5e).
    """
    rows = (await session.execute(_NAMES_SQL, {"dataset_id": dataset_id})).scalars().all()
    return {str(row) for row in rows}


def _pushdown_clause(pushdown: MetadataPushdown) -> tuple[str, dict[str, Any]]:
    """Fragment WHERE zawężający kandydatów + parametry wiązane (DEC-300 p. 2).

    Na każdy pushowalny filtr: klucz istnieje i (typ JSON ≠ ``STRING`` albo tekst równy po
    kolacji ``utf8mb4_uca1400_ai_ci``). Liczby/bool/listy/null przechodzą do Pythona bez oceny
    w SQL; porównanie tekstu ai_ci jest luźniejsze niż ``lower()`` Pythona (nadzbiór), więc
    ostateczne ``match_documents`` nie gubi trafień. Nazwa pola nie zawiera ``"``/``\\``
    (klasyfikator ``metadata.pushdown_condition``), więc bezpiecznie wchodzi do ścieżki JSON.
    """
    fragments: list[str] = []
    params: dict[str, Any] = {}
    for index, f in enumerate(pushdown.filters):
        path_key, value_key = f"pd_path_{index}", f"pd_value_{index}"
        params[path_key] = f'$."{f.name}"'
        params[value_key] = f.value
        fragments.append(
            f"JSON_EXTRACT(meta_fields, :{path_key}) IS NOT NULL AND ("
            f"JSON_TYPE(JSON_EXTRACT(meta_fields, :{path_key})) <> 'STRING' OR "
            f"JSON_VALUE(meta_fields, :{path_key}) COLLATE utf8mb4_uca1400_ai_ci = :{value_key})"
        )
    joined = (" OR " if pushdown.logic == "or" else " AND ").join(fragments)
    return "(" + joined + ")", params


async def meta_fields_by_document(
    session: AsyncSession,
    dataset_id: str,
    document_ids: Sequence[str] | None = None,
    *,
    pushdown: MetadataPushdown | None = None,
) -> dict[str, dict[str, Any]]:
    """Mapa ``document_id`` → ``meta_fields`` dokumentów datasetu (zadanie DS3).

    ``document_ids=None`` → wszystkie dokumenty datasetu (podsumowanie, spłaszczenie);
    pusta lista → ``{}`` bez SQL. Kolejność wierszy po ``id`` (upstream
    ``get_flatted_meta_by_kbs`` sortuje po id). JSON z bazy parsowany; dokument bez
    metadanych ma ``{}`` (DDL ``DEFAULT '{}'``).

    ``pushdown`` (DEC-300 p. 2, tylko ``DocumentService.list``): SQL-owe zawężenie kandydatów
    (nadzbiór trafień) dokładane do ``WHERE``. Zwraca tę samą mapę — ostateczne dopasowanie i tak
    liczy ``match_documents``, więc semantyka zależy wyłącznie od nadzbiorowości pushdownu.
    """
    if document_ids is not None and not document_ids:
        return {}
    conditions = ["dataset_id = :dataset_id"]
    params: dict[str, Any] = {"dataset_id": dataset_id}
    expanding: list[Any] = []
    if document_ids is not None:
        conditions.append("CAST(id AS BINARY) IN :ids")  # kolacja: patrz „_IDS_SQL"
        params["ids"] = list(document_ids)
        expanding.append(bindparam("ids", expanding=True))
    if pushdown is not None:
        clause, pushdown_params = _pushdown_clause(pushdown)
        conditions.append(clause)
        params.update(pushdown_params)
    where = " AND ".join(conditions)
    stmt = text(f"{_META_SELECT} WHERE {where} ORDER BY id").bindparams(*expanding)
    rows = (await session.execute(stmt, params)).all()
    return {str(row.id): _json_column(row.meta_fields) for row in rows}


async def run_counts(session: AsyncSession, dataset_id: str) -> dict[str, int]:
    """Liczba dokumentów datasetu w każdym ``run`` (kod '0'..'5' → liczba).

    Odpowiednik upstream ``DocumentService.get_parsing_status_by_kb_ids`` (DS2, --07):
    zwraca wyłącznie kody obecne w bazie — zera dokłada usługa.
    """
    rows = (await session.execute(_RUN_COUNTS_SQL, {"dataset_id": dataset_id})).mappings()
    return {str(row["run"]): int(row["cnt"]) for row in rows}


async def thumbnails(
    session: AsyncSession,
    document_ids: Sequence[str],
    *,
    visibility: VisibilityFilter,
) -> dict[str, str]:
    """Mapa doc_id → thumbnail dla dokumentów widocznych dla podmiotu (E2-1 DOC2, --31).

    Join po ``datasets`` daje filtr widoczności listy dokumentów (07 §7): cudzy dokument
    w ogóle nie trafia do mapy (upstream ``DocumentService.get_thumbnails`` nie filtruje
    po najemcy — WD dokłada sprawdzenie). Brak wiersza → klucza nie ma. Wartości są już
    w kształcie odpowiedzi: niepusta miniatura dostaje prefiks ``/api/v1/documents/images/``
    (``_thumbnail_value``, upstream DOC:1329-1331).
    """
    if not document_ids:
        return {}
    sql = _THUMBNAILS_SQL
    params: dict[str, Any] = {"ids": list(document_ids)}
    expanding: list[Any] = [bindparam("ids", expanding=True)]
    if not visibility.all:
        sql += _THUMBNAILS_VISIBLE
        expanding.append(bindparam("owners", expanding=True))
        params["owners"] = sorted(visibility.owner_ids)
        params["team"] = visibility.include_team
    rows = (await session.execute(text(sql).bindparams(*expanding), params)).mappings().all()
    return {
        str(row["id"]): _thumbnail_value(str(row["dataset_id"]), row["thumbnail"]) for row in rows
    }


def _thumbnail_value(dataset_id: str, thumbnail: Any) -> str:
    """Wartość miniatury w odpowiedzi ``GET /thumbnails`` (upstream DOC:1329-1331).

    Pusta miniatura zostaje pusta; niepusta dostaje prefiks ``/api/v1/documents/images/{kb_id}-``,
    a miniatura już wbudowana w base64 nie jest opakowywana (upstream ``IMG_BASE64_PREFIX``).
    """
    if not thumbnail:
        return ""
    text = str(thumbnail)
    if text.startswith(_BASE64_THUMBNAIL_PREFIX):
        return text
    return f"/api/v1/documents/images/{dataset_id}-{text}"


async def update_meta(
    session: AsyncSession, document_id: str, fields: Mapping[str, Any], *, now_ms: int
) -> None:
    """Aktualizuje podane kolumny + update_time/date; kolumna spoza białej listy → ValueError.

    parser_config/meta_fields przez ``json.dumps(…, ensure_ascii=False)``; enabled → int(bool).
    Pusty ``fields`` → tylko update_time/update_date (C2.1).
    """
    unknown = sorted(set(fields) - META_COLUMNS)
    if unknown:
        raise ValueError(f"unsupported document columns: {unknown}")
    assignments = ", ".join(column + " = :" + column for column in fields)
    params: dict[str, Any] = dict(fields)
    for column in ("parser_config", "meta_fields"):
        if column in fields:
            params[column] = json.dumps(fields[column], ensure_ascii=False)
    if "enabled" in fields:
        params["enabled"] = int(bool(fields["enabled"]))
    params.update({"document_id": document_id, "now": now_ms, "now_date": from_ms(now_ms)})
    set_clause = (assignments + ", ") if assignments else ""
    await session.execute(
        text(
            "UPDATE documents SET " + set_clause + "update_time = :now,"  # noqa: S608 — białe listy
            " update_date = :now_date WHERE id = :document_id"
        ),
        params,
    )
