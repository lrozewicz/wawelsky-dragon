"""Wspólne helpery etapów migracji: czas i JSON (kontrakt §3, WP E4-6b1)."""

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.core.timeutil import from_ms, to_ms


def datetime_ms(value: datetime | None) -> int | None:
    """`datetime` źródła (naiwna traktowana jak UTC) → milisekundy epoki; NULL zostaje NULL-em."""
    if value is None:
        return None
    return to_ms(value.replace(tzinfo=UTC) if value.tzinfo is None else value)


def ms_naive(ms: int) -> datetime:
    """Milisekundy epoki → naiwna `datetime` (kolumny `*_date` typu DATETIME(3))."""
    return from_ms(ms).replace(tzinfo=None)


def pick_times(
    src_create: Any,
    src_update: Any,
    existing: Mapping[str, Any] | None,
    now_ms: int,
) -> tuple[int, int]:
    """Czasy wiersza celu jako `(create_time, update_time)`.

    Nie-NULL ze źródła wygrywa. Dla źródłowego NULL-a bierzemy czas z wiersza celu, jeśli
    taki istnieje (`existing` to mapa kolumn celu z kluczami `create_time`/`update_time`),
    a gdy wiersza celu nie ma — `now_ms`.
    """
    create = int(src_create) if src_create is not None else now_ms
    update = int(src_update) if src_update is not None else now_ms
    if existing is not None:
        if src_create is None and existing["create_time"] is not None:
            create = int(existing["create_time"])
        if src_update is None and existing["update_time"] is not None:
            update = int(existing["update_time"])
    return create, update


def _json_value(value: Any) -> Any:
    """Wartość porównywalna: tekst/`bytes` (JSON) → obiekt; `dict`/`list`/`None` bez zmian."""
    if isinstance(value, str | bytes):
        return json.loads(value)
    return value


def same_json(a: Any, b: Any) -> bool:
    """Czy dwie wartości JSON są równe (tekst parsowany; `None` równa się tylko `None`)."""
    return bool(_json_value(a) == _json_value(b))


def dumps_json(value: Any) -> str:
    """Serializacja wartości do tekstu JSON bez escapowania znaków spoza ASCII."""
    return json.dumps(value, ensure_ascii=False)
