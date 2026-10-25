"""Czyste rozstrzyganie wierszy ``dialog`` na wartości ``chats`` (kontrakt §2, WP E4-6b2 T1).

Wydzielone z :mod:`app.tools.ragflow_migrate.stages.chats` (limit 400 linii pliku; BRIEF WP
E4-6b2 dopuszcza pomocnicze moduły w pakiecie narzędzia). Bez bazy i bez SQL — testy jednostkowe
w ``tests/unit/tools/test_ragflow_chats.py``.
"""

import json
from collections.abc import Iterable, Mapping
from typing import Any

from app.core.timeutil import from_ms
from app.tools.ragflow_migrate.model_map import ModelMap
from app.tools.ragflow_migrate.stages.base import Issue

#: Domyślny język czatu, gdy źródło nie podaje (``chats.language`` ma w WD domyślnie 'Polish').
DEFAULT_LANGUAGE = "English"

#: Domyślny status czatu (schemat WD: ``status CHAR(1) NOT NULL DEFAULT '1'``).
DEFAULT_STATUS = "1"

#: Domyślne ``do_refer`` (schemat WD: ``do_refer CHAR(1) NOT NULL DEFAULT '1'``).
DEFAULT_DO_REFER = "1"

#: Domyślny typ promptu (schemat WD: ``prompt_type VARCHAR(16) NOT NULL DEFAULT 'simple'``).
DEFAULT_PROMPT_TYPE = "simple"

#: ``rerank_candidates_count`` — w źródle RAGFlow nie ma tej kolumny, WD ma stałe 64.
DEFAULT_RERANK_CANDIDATES = 64

#: Wartość wstawiana tam, gdzie WD wymaga obiektu JSON, a źródło go nie podaje.
EMPTY_JSON_OBJECT = "{}"


def chat_name(row: Mapping[str, Any]) -> str:
    """Nazwa czatu: ``name`` źródła, a gdy NULL/pusta — id dialogu (kontrakt §2)."""
    return str(row["name"] or row["id"])


def chat_name_collision_groups(rows: Iterable[Mapping[str, Any]]) -> list[list[str]]:
    """Grupy id dialogów o tej samej nazwie (bez wielkości liter) w tym samym tenancie."""
    by_key: dict[tuple[str, str], list[str]] = {}
    for row in rows:
        key = (str(row["tenant_id"]), chat_name(row).lower())
        by_key.setdefault(key, []).append(str(row["id"]))
    return [sorted(ids) for ids in by_key.values() if len(set(ids)) > 1]


def json_object_text(value: Any) -> tuple[str, bool]:
    """Kolumna JSON źródła → tekst obiektu JSON; ``False`` w krotce = wartość poprawna."""
    if value is None or value == "":
        return EMPTY_JSON_OBJECT, False
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (ValueError, TypeError):
        return EMPTY_JSON_OBJECT, True
    if not isinstance(parsed, dict):
        return EMPTY_JSON_OBJECT, True
    return json.dumps(parsed, ensure_ascii=False), False


def optional_json_text(value: Any) -> str | None:
    """``meta_data_filter`` źródła → tekst JSON obiektu niepustego; inaczej ``None`` (§2)."""
    if value is None or value == "":
        return None
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict) or not parsed:
        return None
    return json.dumps(parsed, ensure_ascii=False)


def parse_kb_ids(value: Any) -> tuple[list[str], bool]:
    """``kb_ids`` źródła → id datasetów bez duplikatów (kolejność zachowana) i flaga błędu JSON."""
    if value is None or value == "":
        return [], False
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (ValueError, TypeError):
        return [], True
    if not isinstance(parsed, list):
        return [], True
    ids: list[str] = []
    for item in parsed:
        dataset_id = str(item)
        if dataset_id not in ids:
            ids.append(dataset_id)
    return ids, False


def mapped_model(key: str, model_names: Mapping[str, str], model_map: ModelMap) -> str | None:
    """Nazwa modelu WD dla klucza źródła: ``ctx.shared['model_names']``, inaczej mapa modeli."""
    shared = model_names.get(key)
    if shared:
        return str(shared)
    entry = model_map.get(key)
    return entry.name if entry is not None else None


def embedding_mismatch(dataset_ids: Iterable[str], embeddings: Mapping[str, Any]) -> bool:
    """Prawda, gdy datasety czatu mają więcej niż jedną różną wartość embeddingu (CONTRACT §7).

    Wspólne kryterium ``plan`` i ``run``: ``plan`` podaje ``embd_id`` ze źródła, ``run`` —
    ``(embedding_model, embedding_dim)`` datasetów celu. Brak wpisu w mapie liczy się jak jedna,
    nieznana wartość.
    """
    return len({embeddings.get(dataset_id) for dataset_id in dataset_ids}) > 1


def _json_issue(chat_id: str, column: str) -> Issue:
    """Ostrzeżenie o niepoprawnej wartości JSON w kolumnie źródła (kontrakt §2)."""
    return Issue(
        severity="warning",
        code="chat_json_invalid",
        message=f"kolumna {column} czatu nie jest poprawnym JSON-em — użyto wartości domyślnej",
        ids=[chat_id],
    )


def _unmapped_issue(chat_id: str, column: str, code: str) -> Issue:
    """Ostrzeżenie o modelu bez odpowiednika w WD; ``column`` to ``llm_id`` albo ``rerank_id``."""
    return Issue(
        severity="warning",
        code=code,
        message=(
            f"{column} czatu nie ma odpowiednika w modelach WD (brak w --model-map"
            " i w tabeli models) — zapisano pustą wartość"
        ),
        ids=[chat_id],
    )


def _time(value: Any, stored: int | None, now_ms: int) -> int:
    """Czas w ms: wartość źródła, inaczej istniejącego wiersza celu, inaczej bieżący (§2)."""
    if value is not None:
        return int(value)
    return stored if stored is not None else now_ms


def resolve_chat(  # noqa: PLR0913, PLR0917 — sygnatura z kontraktu §2
    row: Mapping[str, Any],
    owner_ids: set[str],
    model_names: Mapping[str, str],
    model_map: ModelMap,
    dataset_ids: set[str],
    embeddings: Mapping[str, Any],
    stored_times: tuple[int, int] | None,
    now_ms: int,
) -> tuple[dict[str, Any] | None, list[str], list[Issue]]:
    """Wiersz ``dialog`` → wartości kolumn ``chats``, id datasetów i uwagi (kontrakt §2).

    ``None`` jako wiersz celu = Issue ``critical`` (wiersz nie jest pisany). ``dataset_ids`` to id
    datasetów obecnych w celu, ``embeddings`` — ich ``(embedding_model, embedding_dim)`` (w
    ``plan``: ``embd_id`` źródła, CONTRACT §7), ``stored_times`` — ``(create_time, update_time)``
    istniejącego wiersza celu (idempotencja).
    """
    dialog_id = str(row["id"])
    tenant_id = str(row["tenant_id"])
    issues: list[Issue] = []
    if tenant_id not in owner_ids:
        issues.append(
            Issue(
                severity="critical",
                code="chat_owner_missing",
                message="tenant czatu nie ma właściciela w tabeli users celu — czat pomijany",
                ids=[dialog_id],
            )
        )
        return None, [], issues

    llm_setting, llm_invalid = json_object_text(row["llm_setting"])
    prompt_config, prompt_invalid = json_object_text(row["prompt_config"])
    if llm_invalid:
        issues.append(_json_issue(dialog_id, "llm_setting"))
    if prompt_invalid:
        issues.append(_json_issue(dialog_id, "prompt_config"))
    kb_ids, kb_invalid = parse_kb_ids(row["kb_ids"])
    if kb_invalid:
        issues.append(_json_issue(dialog_id, "kb_ids"))

    present: list[str] = []
    for dataset_id in kb_ids:
        if dataset_id in dataset_ids:
            present.append(dataset_id)
        else:
            issues.append(
                Issue(
                    severity="warning",
                    code="chat_dataset_missing",
                    message="dataset czatu nie ma w tabeli datasets celu — powiązanie pominięte",
                    ids=[dialog_id, dataset_id],
                )
            )
    if embedding_mismatch(present, embeddings):
        issues.append(
            Issue(
                severity="warning",
                code="chat_embedding_mismatch",
                message="datasety czatu mają różne embeddingi — czat zapisany mimo to",
                ids=[dialog_id],
            )
        )

    llm_id = mapped_model(str(row["llm_id"] or ""), model_names, model_map)
    if llm_id is None:
        issues.append(_unmapped_issue(dialog_id, "llm_id", "chat_llm_unmapped"))
        llm_id = ""
    rerank_id = str(row["rerank_id"] or "")
    if rerank_id:
        mapped_rerank = mapped_model(rerank_id, model_names, model_map)
        if mapped_rerank is None:
            issues.append(_unmapped_issue(dialog_id, "rerank_id", "chat_rerank_unmapped"))
        rerank_id = mapped_rerank or ""

    create_time = _time(row["create_time"], stored_times[0] if stored_times else None, now_ms)
    update_time = _time(row["update_time"], stored_times[1] if stored_times else None, now_ms)
    return (
        {
            "id": dialog_id,
            "tenant_id": tenant_id,
            "created_by": tenant_id,
            "name": chat_name(row),
            "description": row["description"] or "",
            "icon": row["icon"] or None,
            "language": row["language"] or DEFAULT_LANGUAGE,
            "llm_id": llm_id,
            "llm_setting": llm_setting,
            "prompt_type": row["prompt_type"] or DEFAULT_PROMPT_TYPE,
            "prompt_config": prompt_config,
            "similarity_threshold": row["similarity_threshold"],
            "vector_similarity_weight": row["vector_similarity_weight"],
            "top_n": int(row["top_n"]),
            "top_k": int(row["top_k"]),
            "rerank_candidates_count": DEFAULT_RERANK_CANDIDATES,
            "rerank_id": rerank_id,
            "do_refer": row["do_refer"] or DEFAULT_DO_REFER,
            "meta_data_filter": optional_json_text(row["meta_data_filter"]),
            "status": row["status"] or DEFAULT_STATUS,
            "create_time": create_time,
            "create_date": from_ms(create_time).replace(tzinfo=None),
            "update_time": update_time,
            "update_date": from_ms(update_time).replace(tzinfo=None),
        },
        present,
        issues,
    )


def resolve_chats(  # noqa: PLR0913, PLR0917 — sygnatura z kontraktu §2
    rows: list[dict[str, Any]],
    owner_ids: set[str],
    model_names: Mapping[str, str],
    model_map: ModelMap,
    dataset_ids: set[str],
    embeddings: Mapping[str, Any],
    stored_times: Mapping[str, tuple[int, int]],
    now_ms: int,
) -> tuple[list[dict[str, Any]], dict[str, list[str]], list[Issue]]:
    """Wiersze ``dialog`` → wiersze ``chats``, id datasetów per czat i uwagi (czysta funkcja).

    Wiersz, dla którego :func:`resolve_chat` zwróci Issue ``critical`` (albo który należy do grupy
    kolizji nazw), nie trafia na listę wynikową (kontrakt §2).
    """
    groups = chat_name_collision_groups(rows)
    collisions = {row_id for group in groups for row_id in group}
    issues: list[Issue] = [
        Issue(
            severity="critical",
            code="chat_name_collision",
            message=(
                "nazwa czatu powtarza się w tym samym tenancie pod różnymi id: " + ", ".join(group)
            ),
            ids=group,
        )
        for group in groups
    ]
    targets: list[dict[str, Any]] = []
    links: dict[str, list[str]] = {}
    for row in rows:
        dialog_id = str(row["id"])
        target, present, row_issues = resolve_chat(
            row,
            owner_ids,
            model_names,
            model_map,
            dataset_ids,
            embeddings,
            stored_times.get(dialog_id),
            now_ms,
        )
        issues.extend(row_issues)
        if target is None or dialog_id in collisions:
            continue
        targets.append(target)
        links[dialog_id] = present
    return targets, links, issues
