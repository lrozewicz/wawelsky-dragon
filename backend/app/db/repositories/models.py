"""Repozytorium tabeli `models` (kontrakt C9, K5 §0) — Core `text()`, bez commit/rollback."""

import json
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import bindparam, text
from sqlalchemy.engine import CursorResult, RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import from_ms

# Kolumny SELECT-ów rejestru; `instance_id` (K13 §1) na końcu listy.
_COLUMNS = (
    "id, name, model_type, provider, instance_id, display_name, base_url, api_key_enc,"
    " max_tokens, dimension, extra, is_default, is_active"
)


@dataclass(frozen=True)
class ModelRow:
    """Wiersz `models`; flagi jako `bool`, `extra` po `json.loads` (C9)."""

    id: str
    name: str
    model_type: str
    provider: str
    display_name: str | None
    base_url: str | None
    api_key_enc: bytes | None
    max_tokens: int | None
    dimension: int | None
    extra: dict[str, Any] | None
    is_default: bool
    is_active: bool
    instance_id: str | None  # K13 §1: instancja dostawcy; NULL = instancja domyślna


def _row(row: RowMapping) -> ModelRow:
    """RowMapping → ModelRow; JSON i TINYINT(1) konwertowane jawnie."""
    extra = row["extra"]
    return ModelRow(
        id=row["id"],
        name=row["name"],
        model_type=row["model_type"],
        provider=row["provider"],
        display_name=row["display_name"],
        base_url=row["base_url"],
        api_key_enc=row["api_key_enc"],
        max_tokens=row["max_tokens"],
        dimension=row["dimension"],
        extra=json.loads(extra) if extra is not None else None,
        is_default=bool(row["is_default"]),
        is_active=bool(row["is_active"]),
        instance_id=row["instance_id"],
    )


async def get_by_id(session: AsyncSession, model_id: str) -> ModelRow | None:
    """Model po identyfikatorze; None gdy brak."""
    result = await session.execute(
        text(
            f"SELECT {_COLUMNS}"  # noqa: S608 — stała kolumn
            " FROM models WHERE id = :id"
        ),
        {"id": model_id},
    )
    found = result.mappings().first()
    return _row(found) if found is not None else None


async def get_by_name(session: AsyncSession, name: str, model_type: str) -> ModelRow | None:
    """Model po nazwie i typie (uq_models_name_type — najwyżej jeden wiersz)."""
    result = await session.execute(
        text(
            f"SELECT {_COLUMNS}"  # noqa: S608 — stała kolumn
            " FROM models WHERE name = :name AND model_type = :model_type"
        ),
        {"name": name, "model_type": model_type},
    )
    found = result.mappings().first()
    return _row(found) if found is not None else None


async def get_default(session: AsyncSession, model_type: str) -> ModelRow | None:
    """Domyślny model danego typu (is_default = 1; default_key unikalny)."""
    result = await session.execute(
        text(
            f"SELECT {_COLUMNS}"  # noqa: S608 — stała kolumn
            " FROM models WHERE is_default = 1 AND model_type = :model_type"
        ),
        {"model_type": model_type},
    )
    found = result.mappings().first()
    return _row(found) if found is not None else None


async def list_all(session: AsyncSession) -> list[ModelRow]:
    """Wszystkie modele rejestru w kolejności (model_type, name) — determinizm (brief SYS p. 4)."""
    result = await session.execute(
        text(f"SELECT {_COLUMNS} FROM models ORDER BY model_type, name")  # noqa: S608 — stała
    )
    return [_row(row) for row in result.mappings().all()]


async def list_default(session: AsyncSession) -> list[ModelRow]:
    """Modele domyślne (is_default = 1) w kolejności typu — najwyżej jeden na typ."""
    result = await session.execute(
        text(
            f"SELECT {_COLUMNS}"  # noqa: S608 — stała kolumn
            " FROM models WHERE is_default = 1 ORDER BY model_type"
        )
    )
    return [_row(row) for row in result.mappings().all()]


async def list_by_instance(session: AsyncSession, instance_id: str | None) -> list[ModelRow]:
    """Modele instancji (None → `instance_id IS NULL`), po (name, model_type) (CONTRACT §T1)."""
    if instance_id is None:
        where = "instance_id IS NULL"
        params: dict[str, Any] = {}
    else:
        # Kolacja: `models.instance_id` jest CHAR(32) ascii_bin, parametr utf8mb4 (DEC-087/090).
        where = "instance_id = CAST(:instance_id AS BINARY)"
        params = {"instance_id": instance_id}
    result = await session.execute(
        text(f"SELECT {_COLUMNS} FROM models WHERE {where} ORDER BY name, model_type"),  # noqa: S608
        params,
    )
    return [_row(row) for row in result.mappings().all()]


async def get_by_name_type_any(
    session: AsyncSession, name: str, model_type: str
) -> ModelRow | None:
    """Para (nazwa, typ) w dowolnej instancji — jak `get_by_name` (CONTRACT §T1)."""
    return await get_by_name(session, name, model_type)


async def insert_for_instance(  # noqa: PLR0913 — sygnatura z CONTRACT E3-6b §T1
    session: AsyncSession,
    *,
    id: str,
    name: str,
    model_type: str,
    instance_id: str | None,
    max_tokens: int,
    dimension: int | None,
    extra: dict[str, Any] | None,
    created_by: str | None,
    now_ms: int,
) -> None:
    """Model instancji: provider='litellm', is_default=0, is_active=1, base_url/klucz NULL."""
    date = from_ms(now_ms).replace(tzinfo=None)
    await session.execute(
        text(
            "INSERT INTO models (id, name, model_type, provider, instance_id, max_tokens,"
            " dimension, extra, is_default, is_active, created_by,"
            " create_time, create_date, update_time, update_date)"
            " VALUES (:id, :name, :model_type, 'litellm', :instance_id, :max_tokens,"
            " :dimension, :extra, 0, 1, :created_by, :now_ms, :date, :now_ms, :date)"
        ),
        {
            "id": id,
            "name": name,
            "model_type": model_type,
            "instance_id": instance_id,
            "max_tokens": max_tokens,
            "dimension": dimension,
            "extra": json.dumps(extra, ensure_ascii=False) if extra is not None else None,
            "created_by": created_by,
            "now_ms": now_ms,
            "date": date,
        },
    )


async def update_fields(  # noqa: PLR0913 — sygnatura z CONTRACT E3-6b §T1
    session: AsyncSession,
    *,
    model_id: str,
    is_active: bool | None,
    max_tokens: int | None,
    extra: dict[str, Any] | None,
    now_ms: int,
) -> None:
    """Aktualizuje tylko podane pola (None = bez zmiany); zawsze `update_time`/`update_date`."""
    sets = ["update_time = :now_ms", "update_date = :date"]
    params: dict[str, Any] = {"model_id": model_id, "now_ms": now_ms}
    if is_active is not None:
        sets.append("is_active = :is_active")
        params["is_active"] = int(is_active)
    if max_tokens is not None:
        sets.append("max_tokens = :max_tokens")
        params["max_tokens"] = max_tokens
    if extra is not None:
        sets.append("extra = :extra")
        params["extra"] = json.dumps(extra, ensure_ascii=False)
    params["date"] = from_ms(now_ms).replace(tzinfo=None)
    await session.execute(
        text(f"UPDATE models SET {', '.join(sets)} WHERE id = :model_id"),  # noqa: S608 — stała SET
        params,
    )


async def delete_by_ids(session: AsyncSession, ids: list[str]) -> int:
    """Usuwa modele o podanych id; zwraca liczbę usuniętych wierszy (CONTRACT §T1)."""
    result = await session.execute(
        text("DELETE FROM models WHERE CAST(id AS BINARY) IN :ids").bindparams(
            bindparam("ids", expanding=True)
        ),
        {"ids": ids},
    )
    return int(cast("CursorResult[Any]", result).rowcount)


async def count_datasets_using(session: AsyncSession, model: ModelRow) -> int:
    """Liczba datasetów wskazujących model (id albo nazwa z odciętym `@…`, jak C11 `_find`)."""
    value = (
        await session.execute(
            text(
                "SELECT COUNT(*) FROM datasets"
                " WHERE embedding_model = :model_id"
                " OR SUBSTRING_INDEX(embedding_model, '@', 1) = :model_id"
                " OR SUBSTRING_INDEX(embedding_model, '@', 1) = :model_name"
            ),
            {"model_id": model.id, "model_name": model.name},
        )
    ).scalar()
    return int(cast(int, value))


async def insert(  # noqa: PLR0913 — sygnatura z kontraktu C9
    session: AsyncSession,
    *,
    id: str,
    name: str,
    model_type: str,
    is_default: bool,
    now_ms: int,
) -> None:
    """Wstawia model; pozostałe kolumny z DEFAULT/NULL DDL; `default_key` jest generowany."""
    date = from_ms(now_ms).replace(tzinfo=None)
    await session.execute(
        text(
            "INSERT INTO models (id, name, model_type, is_default,"
            " create_time, create_date, update_time, update_date)"
            " VALUES (:id, :name, :model_type, :is_default, :now_ms, :date, :now_ms, :date)"
        ),
        {
            "id": id,
            "name": name,
            "model_type": model_type,
            "is_default": int(is_default),
            "now_ms": now_ms,
            "date": date,
        },
    )


async def set_default(session: AsyncSession, model_id: str, model_type: str, now_ms: int) -> None:
    """Ustawia is_default wybranemu modelowi, zdejmuje pozostałym tego typu (C10).

    Kolejność UPDATE wymuszona unikalnym default_key (= model_type gdy is_default = 1):
    najpierw zdjęcie flagi innym, potem ustawienie wybranemu.
    """
    date = from_ms(now_ms).replace(tzinfo=None)
    await session.execute(
        text(
            "UPDATE models SET is_default = 0, update_time = :now_ms, update_date = :date"
            " WHERE model_type = :model_type AND is_default = 1 AND id <> :id"
        ),
        {"model_type": model_type, "id": model_id, "now_ms": now_ms, "date": date},
    )
    await session.execute(
        text(
            "UPDATE models SET is_default = 1, update_time = :now_ms, update_date = :date"
            " WHERE id = :id"
        ),
        {"id": model_id, "now_ms": now_ms, "date": date},
    )


async def set_dimension_if_null(session: AsyncSession, model_id: str, dim: int, now_ms: int) -> int:
    """Ustawia dimension (z update_time/date) tylko gdy NULL; zwraca rowcount."""
    date = from_ms(now_ms).replace(tzinfo=None)
    result = await session.execute(
        text(
            "UPDATE models SET dimension = :dim, update_time = :now_ms, update_date = :date"
            " WHERE id = :id AND dimension IS NULL"
        ),
        {"dim": dim, "now_ms": now_ms, "date": date, "id": model_id},
    )
    return cast(CursorResult[Any], result).rowcount
