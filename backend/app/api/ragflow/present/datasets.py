"""Prezentery datasetów (kontrakt E1-9a C1.4): kształty v0.27.2 i profil zgodności 0.24.0.

Wszystkie funkcje biorą ``profile`` (CONTRACT E2-2a C0 p. 1): ``ragflow_0_24`` zwraca zbiór
kluczy złota ``v0.24.0`` (baseline §2), ``ragflow_0_27`` zachowuje kształt v0.27.2 bez zmian.
"""

from typing import Any

from app.api.ragflow.compat import CompatProfile
from app.api.ragflow.present.common import date, ts
from app.services.datasets import DatasetRecord

# 11 zadań x 2 (task_id, task_finish_at) = 22 klucze None (C1.4).
TASK_KEYS = (
    "graphrag",
    "mindmap",
    "raptor",
    "session_essence",
    "session_graph",
    "skill",
    "structure_graph",
    "structure_mindmap",
    "structure",
    "timeline",
    "wiki",
)

# Klucze złota v0.27.2 nieobecne w v0.24.0 (baseline §2): 8 grup zadań, których v0.24 nie zna
# (graphrag/mindmap/raptor zostają), oraz ``tenant_embd_id``.
V027_ONLY_KEYS: tuple[str, ...] = (
    "session_essence_task_finish_at",
    "session_essence_task_id",
    "session_graph_task_finish_at",
    "session_graph_task_id",
    "skill_task_finish_at",
    "skill_task_id",
    "structure_graph_task_finish_at",
    "structure_graph_task_id",
    "structure_mindmap_task_finish_at",
    "structure_mindmap_task_id",
    "structure_task_finish_at",
    "structure_task_id",
    "tenant_embd_id",
    "timeline_task_finish_at",
    "timeline_task_id",
    "wiki_task_finish_at",
    "wiki_task_id",
)

# Klucze ``parser_config`` v0.27.2 nieobecne w złocie v0.24.0 (baseline §2).
V027_ONLY_PARSER_KEYS = ("children_delimiter", "parent_child")

# Domyślne ``raptor``/``graphrag`` v0.24.0 dla ``chunk_method="naive"`` — dosłownie
# ``api/utils/api_utils.py:377-395`` (v0.24.0); zgadzają się ze złotem wszystkich 18 plików
# ``golden/v0.24.0`` z ``parser_config``.
GRAPHRAG_V024: dict[str, Any] = {
    "entity_types": ["organization", "person", "geo", "event", "category"],
    "method": "light",
    "use_graphrag": True,
}
RAPTOR_V024: dict[str, Any] = {
    "max_cluster": 64,
    "max_token": 256,
    "prompt": (
        "Please summarize the following paragraphs. Be careful with the numbers, "
        "do not make things up. Paragraphs as following:\n      {cluster_content}\n"
        "The above is the content you need to summarize."
    ),
    "random_seed": 0,
    "threshold": 0.1,
    "use_raptor": True,
}

# Ostrzeżenie no-opu ``DELETE /datasets`` (02-api §7.3, Q14) — komunikat WD, brak w złocie.
MSG_DELETE_NOTHING_V024 = (
    "nothing deleted: `ids` is null or empty and `delete_all` is not true (Q14)."
)


def parser_config_v024(cfg: dict[str, Any], profile: CompatProfile) -> dict[str, Any]:
    """``parser_config`` w kształcie profilu (brief T1 p. 2; użycie także dla dokumentów).

    Profil 0.24.0: bez ``children_delimiter`` i ``parent_child``, z ``graphrag`` i ``raptor``
    (brakujące klucze dostają wartości złota); wynik to nowy dict — prezentacja nie mutuje
    wiersza. Profil 0.27.2: wejście bez zmian.
    """
    if profile == "ragflow_0_27":
        return cfg
    result = {key: value for key, value in cfg.items() if key not in V027_ONLY_PARSER_KEYS}
    result.setdefault("graphrag", dict(GRAPHRAG_V024))
    result.setdefault("raptor", dict(RAPTOR_V024))
    return result


def dataset(rec: DatasetRecord, profile: CompatProfile) -> dict[str, Any]:
    """Podstawa złota POST /datasets: 46 kluczy w v0.27.2, 29 w profilu 0.24.0."""
    data: dict[str, Any] = {
        "avatar": rec.avatar,
        "chunk_count": rec.chunk_count,
        "chunk_method": rec.chunk_method,
        "create_date": date(rec.create_time),
        "create_time": ts(rec.create_time),
        "created_by": rec.created_by,
        "description": rec.description,
        "document_count": rec.document_count,
        "embedding_model": rec.embedding_model,
        "id": rec.id,
        "language": rec.language,
        "name": rec.name,
        "pagerank": rec.pagerank,
        "parser_config": parser_config_v024(rec.parser_config, profile),
        "permission": rec.permission,
        "pipeline_id": None,
        "similarity_threshold": rec.similarity_threshold,
        "status": rec.status,
        "tenant_embd_id": None,
        "tenant_id": rec.tenant_id,
        "token_num": rec.token_num,
        "update_date": date(rec.update_time),
        "update_time": ts(rec.update_time),
        "vector_similarity_weight": rec.vector_similarity_weight,
    }
    for key in TASK_KEYS:
        data[f"{key}_task_id"] = None
        data[f"{key}_task_finish_at"] = None
    if profile == "ragflow_0_24":
        for key in V027_ONLY_KEYS:
            del data[key]
    return data


def dataset_updated(rec: DatasetRecord, profile: CompatProfile) -> dict[str, Any]:
    """Odpowiedź PUT (--03): v0.27.2 = dataset() + connectors []; v0.24.0 = samo dataset()."""
    data = dataset(rec, profile)
    if profile == "ragflow_0_27":
        data["connectors"] = []
    return data


def dataset_detail(rec: DatasetRecord, profile: CompatProfile, size: int) -> dict[str, Any]:
    """Odpowiedź GET /datasets/{id} (DAS:272-276): updated + ``size``.

    ``size`` = suma rozmiarów plików dokumentów datasetu (upstream
    ``DocumentService.get_total_size_by_kb_id``); PUT go nie zwraca (DAS:405-407).
    """
    data = dataset_updated(rec, profile)
    data["size"] = size
    return data


def dataset_listed(rec: DatasetRecord, profile: CompatProfile) -> dict[str, Any]:
    """Element GET /datasets (--02, --04).

    v0.27.2: dataset() + 3 pola właściciela/modelu (C1.4); v0.24.0: samo dataset() —
    złoto v0.24 nie ma ``nickname``/``tenant_avatar``/``embedding_model_name``.
    """
    data = dataset(rec, profile)
    if profile == "ragflow_0_27":
        data["nickname"] = rec.owner_nickname
        data["tenant_avatar"] = None
        data["embedding_model_name"] = ""
    return data


def delete_ok_v024() -> dict[str, Any]:
    """Koperta sukcesu ``DELETE /datasets`` w profilu 0.24.0 — złoto --05: samo ``{"code": 0}``."""
    return {"code": 0}


def delete_noop_v024() -> dict[str, Any]:
    """Koperta no-opu ``DELETE /datasets`` w profilu 0.24.0 (02-api §7.3): ostrzeżenie."""
    return {"code": 0, "message": MSG_DELETE_NOTHING_V024}
