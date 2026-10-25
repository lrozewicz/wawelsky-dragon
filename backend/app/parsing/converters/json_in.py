"""Konwertery JSON i JSONL (kontrakt C8b) — rekordy płaskie jako tabela, reszta jako listy."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.parsing.converters.common import finish, read_bytes
from app.parsing.encoding import decode_bytes
from app.parsing.errors import corrupted_file, limit_exceeded
from app.parsing.html import esc, table_html
from app.parsing.types import ConvertedDocument, ConvertOptions

_MAX_DEPTH = 20


def _scalar(value: object) -> str:
    """Skalar JSON jako tekst: null/true/false, reszta str()."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def _is_scalar(value: object) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _is_flat_records(value: list[Any]) -> bool:
    """Lista rekordów płaskich: każdy element to dict z wyłącznie skalarnymi wartościami."""
    return all(isinstance(el, dict) and all(_is_scalar(v) for v in el.values()) for el in value)


def _records_table(records: list[Any]) -> str:
    """Tabela: nagłówki wg pierwszego wystąpienia klucza, brak klucza = pusta komórka."""
    keys: list[str] = []
    for record in records:
        for key in record:
            if key not in keys:
                keys.append(key)
    # table_html escapuje komórki sam (C3) — tu surowe wartości, bez podwójnego esc.
    rows = [[_scalar(record[key]) if key in record else "" for key in keys] for record in records]
    return table_html([keys, *rows], header_rows=1)


def _render(value: Any, depth: int) -> str:
    """Rekurencyjny render wartości JSON do HTML (C8b); za głębokie wartości jako dumps."""
    if depth > _MAX_DEPTH:
        return f"<p>{esc(json.dumps(value, ensure_ascii=False))}</p>"
    if isinstance(value, dict):
        items: list[str] = []
        for key, val in value.items():
            if _is_scalar(val):
                items.append(f"<li><strong>{esc(key)}</strong>: {esc(_scalar(val))}</li>")
            else:
                items.append(f"<li><strong>{esc(key)}</strong>{_render(val, depth + 1)}</li>")
        return "<ul>" + "".join(items) + "</ul>"
    if isinstance(value, list):
        items = []
        for el in value:
            if _is_scalar(el):
                items.append(f"<li>{esc(_scalar(el))}</li>")
            else:
                items.append(f"<li>{_render(el, depth + 1)}</li>")
        return "<ul>" + "".join(items) + "</ul>"
    return f"<p>{esc(_scalar(value))}</p>"  # skalar na poziomie renderu


def _top_level(value: Any, opts: ConvertOptions) -> str:
    """Render najwyższego poziomu: tabela dla rekordów płaskich, `<h2>Record n</h2>` dla reszty."""
    if isinstance(value, list):
        if len(value) > opts.max_sheet_rows:
            raise limit_exceeded("records", len(value), opts.max_sheet_rows)
        if _is_flat_records(value):
            return _records_table(value)
        return "".join(
            f"<h2>Record {nr}</h2>{_render(el, 1)}" for nr, el in enumerate(value, start=1)
        )
    return _render(value, 0)


def convert_json(path: Path, opts: ConvertOptions) -> ConvertedDocument:
    """Plik JSON → HTML (C8b)."""
    text, _ = decode_bytes(read_bytes(path), fmt="json")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise corrupted_file("json", f"invalid JSON at line {exc.lineno}") from exc
    return finish(_top_level(value, opts), diagnosis="JSON has no values")


def convert_jsonl(path: Path, opts: ConvertOptions) -> ConvertedDocument:
    """Plik JSONL → HTML; każda niepusta linia to rekord, wynik jak lista (C8b)."""
    text, _ = decode_bytes(read_bytes(path), fmt="jsonl")
    records: list[Any] = []
    for nr, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise corrupted_file("jsonl", f"invalid JSON at line {nr}") from exc
    return finish(_top_level(records, opts), diagnosis="JSON has no values")
