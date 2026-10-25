"""Prezentery dokumentów (kontrakt E1-9a C2.4): kształty v0.27.2 i profil zgodności 0.24.0.

Profil ``ragflow_0_24`` zwraca zbiory kluczy złota ``v0.24.0`` (dokumenty_parse--02/--03/--06,
chunks_list--06 → data.doc): bez ``content_hash`` (klucz v0.27), bez ``nickname``
i ``pipeline_name`` na liście, z ``title`` (``null``); ``parser_config`` przez
``parser_config_v024``. Profil ``ragflow_0_27`` zachowuje kształt v0.27.2 bez zmian.
"""

from typing import Any

from app.api.ragflow.compat import CompatProfile
from app.api.ragflow.present.common import date, ts
from app.api.ragflow.present.datasets import parser_config_v024
from app.services.documents import DocumentRow


def _turn2jsonschema(metadata: Any) -> Any:
    """``metadata`` dokumentu jako JSON-Schema (upstream ``common/metadata_utils.py:486-501``).

    Gotowy JSON-Schema (``$schema`` albo ``type: object`` + ``properties``) zwracany bez zmian;
    lista pól ``{key, description?, enum?}`` normalizowana do ``{type: object, properties: {…},
    additionalProperties: false}`` (bez ``type`` pola — tak samo jak upstream ``metadata_schema``,
    złoto ``metadata_e6--58``); inny kształt → ``{}``.
    """
    if isinstance(metadata, dict):
        if "$schema" in metadata or (
            metadata.get("type") == "object" and isinstance(metadata.get("properties"), dict)
        ):
            return metadata
        return {}
    if not isinstance(metadata, list) or not metadata:
        return {}
    properties: dict[str, Any] = {}
    for item in metadata:
        if not isinstance(item, dict) or not item.get("key"):
            return {}
        prop: dict[str, Any] = {"description": item.get("description", "")}
        if item.get("enum"):
            prop["enum"] = item["enum"]
            prop["type"] = "string"
        properties[item["key"]] = prop
    return {"type": "object", "properties": properties, "additionalProperties": False}


def _parser_config_v027(cfg: dict[str, Any]) -> dict[str, Any]:
    """``parser_config`` dokumentu w profilu v0.27.2: ``metadata`` jako JSON-Schema.

    Upstream ``document_api.py:851`` woła ``turn2jsonschema`` na ``metadata`` dokumentu (krok 58;
    ``graphrag``/``raptor`` nie trafiają do dokumentu już przy tworzeniu — patrz
    ``services.ingest_link.document_parser_config``).
    """
    if cfg.get("metadata"):
        return {**cfg, "metadata": _turn2jsonschema(cfg["metadata"])}
    return cfg


def _doc_parser_config(cfg: dict[str, Any], profile: CompatProfile) -> dict[str, Any]:
    """``parser_config`` dokumentu wg profilu: v0.27.2 kształt złota, 0.24.0 przez
    ``parser_config_v024``."""
    if profile == "ragflow_0_27":
        return _parser_config_v027(cfg)
    return parser_config_v024(cfg, profile)


# Kody run → nazwy odpowiedzi (C2.4; odwrotność RUN_CODES z usługi).
RUN_NAMES = {
    "0": "UNSTART",
    "1": "RUNNING",
    "2": "CANCEL",
    "3": "DONE",
    "4": "FAIL",
    "5": "SCHEDULE",
}


def _fields_base(row: DocumentRow, profile: CompatProfile) -> dict[str, Any]:
    """14 kluczy plikowych wspólnych dla wszystkich kształtów (bez content_hash)."""
    return {
        "chunk_method": row.chunk_method,
        "created_by": row.created_by,
        "dataset_id": row.dataset_id,
        "id": row.id,
        "location": row.name,  # kontrakt C2.4: location ← row.name (kolumna to klucz storage)
        "name": row.name,
        "parser_config": _doc_parser_config(row.parser_config, profile),
        "pipeline_id": None,
        "run": RUN_NAMES[row.run],
        "size": row.size,
        "source_type": row.source_type,
        "suffix": row.suffix,
        "thumbnail": row.thumbnail or "",
        "type": row.type,
    }


def _status_fields(row: DocumentRow) -> dict[str, Any]:
    """11 kluczy stanu/czasu listy i pełnego dokumentu (C2.4, C0 p. 6)."""
    return {
        "chunk_count": row.chunk_count,
        "create_date": date(row.create_time),
        "create_time": ts(row.create_time),
        "process_begin_at": (
            date(row.process_begin_at) if row.process_begin_at is not None else None
        ),
        "process_duration": float(row.process_duration),
        "progress": float(row.progress),
        "progress_msg": row.progress_msg,
        "status": "1" if row.enabled else "0",
        "token_count": row.token_count,
        "update_date": date(row.update_time),
        "update_time": ts(row.update_time),
    }


def document_uploaded(row: DocumentRow, profile: CompatProfile) -> dict[str, Any]:
    """Odpowiedź uploadu: 15 kluczy v0.27.2, 14 w profilu 0.24.0.

    Złoto ``documents_parse--02`` (v0.24.0) nie ma ``content_hash`` (klucz v0.27).
    """
    data = _fields_base(row, profile)
    if profile == "ragflow_0_27":
        data["content_hash"] = row.content_hash
    return data


def document_listed(row: DocumentRow, nickname: str, profile: CompatProfile) -> dict[str, Any]:
    """Element listy dokumentów: 28 kluczy v0.27.2 (--03/--06 → data.docs[i]), 27 w 0.24.0.

    Złoto ``documents_parse--03/--06`` (v0.24.0) nie ma ``nickname`` ani ``pipeline_name``,
    a ma ``title`` o wartości ``null`` (pole tabeli dokumentu nieobecne w WD).
    """
    data = _fields_base(row, profile)
    data.update(_status_fields(row))
    data["meta_fields"] = row.meta_fields
    if profile == "ragflow_0_27":
        data["nickname"] = nickname
        data["pipeline_name"] = None
    else:
        data["title"] = None
    return data


def document_full(row: DocumentRow, profile: CompatProfile) -> dict[str, Any]:
    """Pełny dokument: v0.27.2 = 26 kluczy (base + status + content_hash), 0.24.0 = 25.

    Złoto ``chunks_list--06`` → data.doc; także odpowiedź PATCH/PUT (C2.4, C2.5).
    """
    data = _fields_base(row, profile)
    data.update(_status_fields(row))
    if profile == "ragflow_0_27":
        data["content_hash"] = row.content_hash
    return data


def document_metadata_config(row: DocumentRow, profile: CompatProfile) -> dict[str, Any]:
    """Odpowiedź PUT …/documents/{id}/metadata/config (S-320): surowy kształt ``doc.to_dict()``.

    Upstream ``document_api.py:1288`` zwraca ``strip_graphrag_raptor_config(doc.to_dict())`` —
    surowe kolumny dokumentu (``kb_id``/``parser_id``/``chunk_num``/``token_num``, ``run`` jako
    kod ``'0'..'5'``), a nie kształt :func:`document_full` (złoto ``metadata_e6--35``).
    """
    return {
        "chunk_num": row.chunk_count,
        "content_hash": row.content_hash,
        "create_date": date(row.create_time),
        "create_time": ts(row.create_time),
        "created_by": row.created_by,
        "id": row.id,
        "kb_id": row.dataset_id,
        "location": row.name,
        "name": row.name,
        "parser_config": parser_config_v024(row.parser_config, profile),
        "parser_id": row.chunk_method,
        "pipeline_id": None,
        "process_begin_at": (
            date(row.process_begin_at) if row.process_begin_at is not None else None
        ),
        "process_duration": float(row.process_duration),
        "progress": float(row.progress),
        "progress_msg": row.progress_msg,
        "run": row.run,
        "size": row.size,
        "source_type": row.source_type,
        "status": "1" if row.enabled else "0",
        "suffix": row.suffix,
        "thumbnail": row.thumbnail or "",
        "token_num": row.token_count,
        "type": row.type,
        "update_date": date(row.update_time),
        "update_time": ts(row.update_time),
    }
