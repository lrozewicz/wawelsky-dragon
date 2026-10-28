"""Repozytorium tabeli `runpod_pods` (wdrożenia modeli na RunPod, migracja 0011).

SQL przez ``text()``, bez ``commit``/``rollback`` — transakcję otwiera ``app.db.uow.transaction``.
``id`` ma kolację `ascii_bin`, więc porównania z parametrem idą przez ``CAST(:x AS BINARY)``.
Kolumny JSON (`data_center_ids`, `pending_parse`): kodowane przy zapisie, dekodowane przy odczycie.
"""

import json
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import bindparam, text
from sqlalchemy.engine import CursorResult, RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

# Stany, w których pod jeszcze kosztuje albo jest w drodze (nie `terminated`/`failed`).
ACTIVE_STATUSES = ("requested", "provisioning", "starting", "loading", "ready", "terminating")

_COLUMNS = (
    "id, model_name, origin, status, pod_id, gpu_id, gpu_name, vram_gb, cloud, data_center_ids,"
    " data_center_id, price_per_hr, base_url, api_token_enc, pending_parse, error, created_by,"
    " create_time, update_time, ready_time, busy_time, end_time"
)

# Pola, które wolno zmieniać `update_fields` (nazwa kolumny == nazwa pola; JSON kodowany).
_UPDATABLE = frozenset(
    {
        "status",
        "pod_id",
        "data_center_id",
        "price_per_hr",
        "base_url",
        "api_token_enc",
        "pending_parse",
        "error",
        "ready_time",
        "busy_time",
        "end_time",
    }
)


@dataclass(frozen=True)
class PodRow:
    """Wiersz `runpod_pods` ze zdekodowanymi kolumnami JSON."""

    id: str
    model_name: str
    origin: str  # `panel` (Ustawienia → RunPod) albo `parse` (start parsowania z Bazy Wiedzy)
    status: str
    pod_id: str | None
    gpu_id: str
    gpu_name: str
    vram_gb: int
    cloud: str
    data_center_ids: list[str]
    data_center_id: str | None
    price_per_hr: float
    base_url: str | None
    api_token_enc: bytes | None
    pending_parse: list[dict[str, Any]]
    error: str | None
    created_by: str | None
    create_time: int
    update_time: int
    ready_time: int | None
    busy_time: int | None
    end_time: int | None


def _row(row: RowMapping) -> PodRow:
    return PodRow(
        id=row["id"],
        model_name=row["model_name"],
        origin=row["origin"],
        status=row["status"],
        pod_id=row["pod_id"],
        gpu_id=row["gpu_id"],
        gpu_name=row["gpu_name"],
        vram_gb=int(row["vram_gb"]),
        cloud=row["cloud"],
        data_center_ids=json.loads(row["data_center_ids"] or "[]"),
        data_center_id=row["data_center_id"],
        price_per_hr=float(row["price_per_hr"]),
        base_url=row["base_url"],
        api_token_enc=bytes(row["api_token_enc"]) if row["api_token_enc"] is not None else None,
        pending_parse=json.loads(row["pending_parse"] or "[]"),
        error=row["error"],
        created_by=row["created_by"],
        create_time=int(row["create_time"]),
        update_time=int(row["update_time"]),
        ready_time=row["ready_time"],
        busy_time=row["busy_time"],
        end_time=row["end_time"],
    )


_INSERT_SQL = text(
    "INSERT INTO runpod_pods (id, model_name, origin, status, gpu_id, gpu_name, vram_gb, cloud,"
    " data_center_ids, price_per_hr, api_token_enc, pending_parse, created_by, create_time,"
    " update_time, busy_time)"
    " VALUES (:id, :model_name, :origin, 'requested', :gpu_id, :gpu_name, :vram_gb, :cloud,"
    " :data_center_ids, :price_per_hr, :api_token_enc, :pending_parse, :created_by, :now_ms,"
    " :now_ms, :now_ms)"
)

_GET_SQL = text(f"SELECT {_COLUMNS} FROM runpod_pods WHERE id = CAST(:id AS BINARY)")  # noqa: S608

_ACTIVE_SQL = text(
    f"SELECT {_COLUMNS} FROM runpod_pods WHERE status IN :statuses ORDER BY create_time"  # noqa: S608
).bindparams(bindparam("statuses", expanding=True))

_DELETE_ENDED_SQL = text("DELETE FROM runpod_pods WHERE status IN ('terminated', 'failed')")

_RECENT_SQL = text(
    f"SELECT {_COLUMNS} FROM runpod_pods ORDER BY create_time DESC LIMIT :limit"  # noqa: S608
)

# Zadania parsowania (queued/running), których dokument używa modelu `:model` jako parsera.
_PENDING_TASKS_SQL = text(
    "SELECT COUNT(*) FROM tasks t JOIN documents d ON d.id = t.document_id"
    " WHERE t.task_type = 'parse_document' AND t.status IN ('queued','running')"
    " AND JSON_UNQUOTE(JSON_EXTRACT(d.parser_config, '$.layout_recognize')) = :model"
)


async def insert(  # noqa: PLR0913 — kolumny wiersza
    session: AsyncSession,
    *,
    deployment_id: str,
    model_name: str,
    origin: str,
    gpu_id: str,
    gpu_name: str,
    vram_gb: int,
    cloud: str,
    data_center_ids: list[str],
    price_per_hr: float,
    api_token_enc: bytes,
    pending_parse: list[dict[str, Any]],
    created_by: str | None,
    now_ms: int,
) -> None:
    """Zakłada wdrożenie w stanie `requested` (zanim powstanie pod w RunPod)."""
    await session.execute(
        _INSERT_SQL,
        {
            "id": deployment_id,
            "model_name": model_name,
            "origin": origin,
            "gpu_id": gpu_id,
            "gpu_name": gpu_name,
            "vram_gb": vram_gb,
            "cloud": cloud,
            "data_center_ids": json.dumps(data_center_ids),
            "price_per_hr": price_per_hr,
            "api_token_enc": api_token_enc,
            "pending_parse": json.dumps(pending_parse),
            "created_by": created_by,
            "now_ms": now_ms,
        },
    )


async def get(session: AsyncSession, pod_id: str) -> PodRow | None:
    """Wdrożenie po id albo None."""
    row = (await session.execute(_GET_SQL, {"id": pod_id})).mappings().first()
    return _row(row) if row is not None else None


async def list_active(session: AsyncSession) -> list[PodRow]:
    """Wdrożenia, które jeszcze trwają (od najstarszego)."""
    rows = (await session.execute(_ACTIVE_SQL, {"statuses": list(ACTIVE_STATUSES)})).mappings()
    return [_row(row) for row in rows]


async def list_recent(session: AsyncSession, limit: int = 20) -> list[PodRow]:
    """Ostatnie wdrożenia (najnowsze pierwsze) — aktywne i zakończone."""
    rows = (await session.execute(_RECENT_SQL, {"limit": limit})).mappings()
    return [_row(row) for row in rows]


async def delete_ended(session: AsyncSession) -> int:
    """Czyści historię: kasuje zakończone wdrożenia (terminated, failed); aktywnych nie rusza."""
    result = cast("CursorResult[Any]", await session.execute(_DELETE_ENDED_SQL))
    return int(result.rowcount or 0)


async def update_fields(
    session: AsyncSession, deployment_id: str, *, now_ms: int, **fields: Any
) -> None:
    """Aktualizuje wskazane pola (whitelist `_UPDATABLE`); JSON kodowany, `update_time` z zegara."""
    unknown = set(fields) - _UPDATABLE
    if unknown:
        raise ValueError(f"unsupported runpod_pods fields: {sorted(unknown)}")
    values = {
        key: json.dumps(value) if key == "pending_parse" else value for key, value in fields.items()
    }
    assignments = ", ".join(f"{key} = :{key}" for key in values)
    sets = f"{assignments}, " if assignments else ""
    query = f"UPDATE runpod_pods SET {sets}update_time = :now_ms WHERE id = CAST(:id AS BINARY)"  # noqa: S608
    sql = text(query)
    await session.execute(sql, {**values, "id": deployment_id, "now_ms": now_ms})


async def count_pending_parse_tasks(session: AsyncSession, model_name: str) -> int:
    """Liczba aktywnych zadań parsowania dokumentów, których parserem jest `model_name`."""
    return int((await session.execute(_PENDING_TASKS_SQL, {"model": model_name})).scalar_one())
