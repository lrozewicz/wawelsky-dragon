"""Repozytorium tabeli `document_profiles` (K21 §1 — spisy treści dokumentów).

SQL przez ``text()``, bez ``commit``/``rollback`` — transakcję otwiera ``app.db.uow.transaction``
(wzorzec pozostałych repozytoriów). `outline` to JSON — kodowany przy zapisie, dekodowany przy
odczycie (jak `errors`/`summary` w repozytorium `dataset_imports`). Etap 1 mapy bazy wiedzy:
`summary`/`topics`/`model` pozostają zawsze NULL (rezerwa etapu 2 — K21 §1).
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, TypedDict, cast

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession


class OutlineItem(TypedDict):
    """Pozycja spisu treści (K21 §1): `level` 0 = najwyższy, `page` od 1 albo None."""

    level: int
    title: str
    page: int | None


@dataclass(frozen=True)
class CatalogDoc:
    """Wiersz katalogu bazy wiedzy do promptu czatu (K21 §3)."""

    document_id: str
    document_name: str
    dataset_id: str
    dataset_name: str
    outline: list[OutlineItem]
    outline_source: str


# `create_time` tylko w INSERT (przy aktualizacji zachowane), `update_time` zawsze z zegara
# wołającego; `summary`/`topics`/`model` bezwzględnie NULL (K21 §1, etap 1).
_UPSERT_SQL = text(
    "INSERT INTO document_profiles"
    " (document_id, dataset_id, outline, outline_source, outline_count, summary, topics,"
    " model, create_time, update_time)"
    " VALUES (:document_id, :dataset_id, :outline, :outline_source, :outline_count, NULL,"
    " NULL, NULL, :now_ms, :now_ms)"
    " ON DUPLICATE KEY UPDATE dataset_id = VALUES(dataset_id), outline = VALUES(outline),"
    " outline_source = VALUES(outline_source), outline_count = VALUES(outline_count),"
    " summary = NULL, topics = NULL, model = NULL, update_time = :now_ms"
)

# Zakres katalogu wyłącznie z `dataset_ids` (K21 §3 p. 1); dokumenty `enabled=1` i `run='3'`,
# kolejność: nazwa datasetu, nazwa dokumentu (+ `d.id` — deterministyczny tie-breaker duplikatów
# nazw). Dokument bez profilu → LEFT JOIN z NULL-ami (`outline`=[], `outline_source`='none').
_LIST_CATALOG_SQL = text(
    "SELECT d.id AS document_id, d.name AS document_name, d.dataset_id AS dataset_id,"
    " ds.name AS dataset_name, p.outline AS outline, p.outline_source AS outline_source"
    " FROM documents d JOIN datasets ds ON ds.id = d.dataset_id"
    " LEFT JOIN document_profiles p ON p.document_id = d.id"
    " WHERE d.enabled = 1 AND d.run = '3' AND d.dataset_id IN :dataset_ids"
    " ORDER BY ds.name, d.name, d.id"
).bindparams(bindparam("dataset_ids", expanding=True))

# Porcja do przeglądu (sweep) `build_outline`: dokumenty `run='3'` bez profilu (K21 §2 p. 4),
# w stabilnej kolejności `d.id` (bez ORDER BY porcja z LIMIT byłaby zależna od planu zapytania).
_IDS_WITHOUT_PROFILE_SQL = text(
    "SELECT d.id FROM documents d WHERE d.run = '3' AND NOT EXISTS"
    " (SELECT 1 FROM document_profiles p WHERE p.document_id = d.id)"
    " ORDER BY d.id LIMIT :limit"
)


def _decode_outline(raw: Any) -> list[OutlineItem]:
    """Wartość kolumny JSON `outline` (tekst od sterownika albo NULL) → lista pozycji."""
    if raw is None:
        return []
    return cast("list[OutlineItem]", json.loads(raw))


async def upsert(  # noqa: PLR0913 — sygnatura z CONTRACT V13-1 (kolumny tabeli K21 §1)
    session: AsyncSession,
    *,
    document_id: str,
    dataset_id: str,
    outline: list[dict[str, Any]],
    outline_source: str,
    now_ms: int,
) -> None:
    """Zapisuje profil dokumentu po kluczu `document_id`; reparsowanie nadpisuje (K21 §1).

    `outline_count` = `len(outline)`; powtórny zapis tego samego dokumentu daje jeden wiersz
    z treścią ostatniego wywołania (`create_time` z pierwszego, `update_time` = `now_ms`).
    """
    await session.execute(
        _UPSERT_SQL,
        {
            "document_id": document_id,
            "dataset_id": dataset_id,
            "outline": json.dumps(outline, ensure_ascii=False),
            "outline_source": outline_source,
            "outline_count": len(outline),
            "now_ms": now_ms,
        },
    )


async def list_catalog(session: AsyncSession, dataset_ids: Sequence[str]) -> list[CatalogDoc]:
    """Katalog bazy wiedzy dla datasetów zapytania (K21 §3 p. 1); pusty zakres → `[]`."""
    if not dataset_ids:
        return []
    rows = (
        (await session.execute(_LIST_CATALOG_SQL, {"dataset_ids": list(dataset_ids)}))
        .mappings()
        .all()
    )
    return [
        CatalogDoc(
            document_id=str(row["document_id"]),
            document_name=str(row["document_name"]),
            dataset_id=str(row["dataset_id"]),
            dataset_name=str(row["dataset_name"]),
            outline=_decode_outline(row["outline"]),
            outline_source=(
                str(row["outline_source"]) if row["outline_source"] is not None else "none"
            ),
        )
        for row in rows
    ]


async def ids_without_profile(session: AsyncSession, limit: int) -> list[str]:
    """Do `limit` identyfikatorów dokumentów `run='3'` bez wiersza profilu (K21 §2 p. 4)."""
    rows = (await session.execute(_IDS_WITHOUT_PROFILE_SQL, {"limit": limit})).all()
    return [str(row[0]) for row in rows]
