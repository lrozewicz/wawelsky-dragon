"""Testy present/datasets w profilu zgodności 0.24.0 (brief E2-2a T1, CONTRACT C0 p. 1-2).

Profil 0.24 zwraca zbiór kluczy złota ``v0.24.0`` (bez 8 grup zadań ``*_task_id`` /
``*_task_finish_at``, ``tenant_embd_id``, ``connectors`` i pól właściciela na liście);
``parser_config`` v0.24 nie ma ``children_delimiter``/``parent_child``, a ma ``graphrag``
i ``raptor``. Profil 0.27 pozostaje bez zmian (złoto ``v0.27.2`` porównane tym samym testem).
"""

import json
from pathlib import Path
from typing import Any

from app.api.ragflow.present.datasets import (
    GRAPHRAG_V024,
    RAPTOR_V024,
    dataset,
    dataset_detail,
    dataset_listed,
    dataset_updated,
    parser_config_v024,
)
from app.services.datasets import DEFAULT_PARSER_CONFIG, DatasetRecord

PROFILE_V024 = "ragflow_0_24"
PROFILE_V027 = "ragflow_0_27"
NOW_MS = 1790157600000  # → "2026-09-23 10:00:00" UTC (date())
LLM_ID = "fake-chat"

GOLDEN_V024 = Path(__file__).resolve().parents[3] / "contract" / "golden" / "v0.24.0"
GOLDEN_V027 = Path(__file__).resolve().parents[3] / "contract" / "golden" / "v0.27.2"

# Grupy zadań obecne w złocie v0.27.2, których v0.24.0 nie zna (baseline §2).
V027_ONLY_TASK_GROUPS = (
    "session_essence",
    "session_graph",
    "skill",
    "structure",
    "structure_graph",
    "structure_mindmap",
    "timeline",
    "wiki",
)


def _record(**overrides: Any) -> DatasetRecord:
    """Pełny DatasetRecord do testów prezentertów (pola wg kontraktu C1.1)."""
    values: dict[str, Any] = dict(
        id="d" * 32,
        tenant_id="u" * 32,
        created_by="u" * 32,
        name="wd_rec_ds",
        description=None,
        avatar=None,
        language="English",
        embedding_model="fake-embed-1024",
        embedding_dim=1024,
        permission="me",
        chunk_method="naive",
        parser_config={**DEFAULT_PARSER_CONFIG, "llm_id": LLM_ID},
        similarity_threshold=0.2,
        vector_similarity_weight=0.3,
        pagerank=0,
        document_count=0,
        chunk_count=0,
        token_num=0,
        status="1",
        create_time=NOW_MS,
        update_time=NOW_MS,
        owner_nickname="Alice",
    )
    values.update(overrides)
    return DatasetRecord(**values)


def _golden(root: Path, name: str, path: list[Any]) -> Any:
    """Węzeł body pliku złota po przejściu po ``path`` (np. ["data", 0])."""
    node: Any = json.loads((root / name).read_text(encoding="utf-8"))["body"]
    for part in path:
        node = node[part]
    return node


def test_dataset_keys_match_golden_create_v024() -> None:
    """dataset() w profilu 0.24 ma dokładnie klucze złota POST (datasets_crud--01)."""
    golden = _golden(GOLDEN_V024, "datasets/datasets_crud--01.json", ["data"])
    assert sorted(dataset(_record(), PROFILE_V024).keys()) == sorted(golden.keys())


def test_dataset_has_no_unknown_task_keys_v024() -> None:
    """Profil 0.24 nie zwraca 8 grup zadań ani tenant_embd_id (baseline §2)."""
    data = dataset(_record(), PROFILE_V024)
    for group in V027_ONLY_TASK_GROUPS:
        assert f"{group}_task_id" not in data
        assert f"{group}_task_finish_at" not in data
    assert "tenant_embd_id" not in data
    # Grupy wspólne dla obu profili zostają.
    for group in ("graphrag", "mindmap", "raptor"):
        assert data[f"{group}_task_id"] is None
        assert data[f"{group}_task_finish_at"] is None


def test_dataset_values_v024() -> None:
    """Wartości dataset() v0.24 identyczne jak w v0.27 poza usuniętymi kluczami."""
    data = dataset(_record(), PROFILE_V024)
    assert data["id"] == "d" * 32
    assert data["tenant_id"] == data["created_by"] == "u" * 32
    assert data["name"] == "wd_rec_ds"
    assert data["status"] == "1"
    assert data["permission"] == "me"
    assert data["chunk_method"] == "naive"
    assert data["embedding_model"] == "fake-embed-1024"
    assert data["create_date"] == data["update_date"] == "2026-09-23 10:00:00"
    assert data["create_time"] == data["update_time"] == NOW_MS
    assert data["pipeline_id"] is None
    assert data["document_count"] == data["chunk_count"] == data["token_num"] == 0


def test_dataset_parser_config_matches_golden_v024() -> None:
    """parser_config w profilu 0.24: klucze złota + graphrag/raptor o wartościach złota."""
    golden = dict(
        _golden(GOLDEN_V024, "datasets/datasets_crud--01.json", ["data", "parser_config"])
    )
    data = dataset(_record(), PROFILE_V024)
    assert sorted(data["parser_config"].keys()) == sorted(golden.keys())
    assert data["parser_config"]["graphrag"] == golden["graphrag"] == GRAPHRAG_V024
    assert data["parser_config"]["raptor"] == golden["raptor"] == RAPTOR_V024
    assert "children_delimiter" not in data["parser_config"]
    assert "parent_child" not in data["parser_config"]


def test_dataset_updated_keys_match_golden_put_v024() -> None:
    """dataset_updated() w profilu 0.24 = dataset() bez connectors (datasets_crud--03)."""
    golden = _golden(GOLDEN_V024, "datasets___/datasets_crud--03.json", ["data"])
    data = dataset_updated(_record(), PROFILE_V024)
    assert sorted(data.keys()) == sorted(golden.keys())
    assert "connectors" not in data


def test_dataset_detail_keys_v024() -> None:
    """dataset_detail() v0.24 = zołoto PUT (--03) + ``size``; bez connectors."""
    data = dataset_detail(_record(), PROFILE_V024, 0)
    assert "connectors" not in data
    assert "size" not in dataset_updated(_record(), PROFILE_V024)
    assert data["size"] == 0


def test_dataset_listed_keys_match_golden_list_v024() -> None:
    """Element listy v0.24 = dataset() bez nickname/tenant_avatar/embedding_model_name (--02)."""
    golden = _golden(GOLDEN_V024, "datasets/datasets_crud--02.json", ["data", 0])
    data = dataset_listed(_record(), PROFILE_V024)
    assert sorted(data.keys()) == sorted(golden.keys())
    assert "nickname" not in data
    assert "tenant_avatar" not in data
    assert "embedding_model_name" not in data


def test_parser_config_v024_drops_and_adds_keys() -> None:
    """parser_config_v024: usuwa children_delimiter/parent_child, dokłada graphrag/raptor."""
    cfg = {**DEFAULT_PARSER_CONFIG, "llm_id": LLM_ID}
    result = parser_config_v024(cfg, PROFILE_V024)
    assert "children_delimiter" not in result
    assert "parent_child" not in result
    assert result["graphrag"] == GRAPHRAG_V024
    assert result["raptor"] == RAPTOR_V024
    assert result["llm_id"] == LLM_ID
    # Wejście bez zmian (prezenter nie mutuje wiersza).
    assert "children_delimiter" in cfg
    assert "graphrag" not in cfg
    assert result is not cfg


def test_parser_config_v024_keeps_v027_unchanged() -> None:
    """W profilu 0.27 parser_config_v024 oddaje wejście bez zmian."""
    cfg = {**DEFAULT_PARSER_CONFIG, "llm_id": LLM_ID}
    assert parser_config_v024(cfg, PROFILE_V027) == cfg


def test_profile_v027_unchanged() -> None:
    """Ten sam rekord w profilu 0.27: klucze złota v0.27.2 (regresja, C0 p. 1)."""
    create = _golden(GOLDEN_V027, "datasets/datasets_crud--01.json", ["data"])
    listed = _golden(GOLDEN_V027, "datasets/datasets_crud--02.json", ["data", 0])
    updated = _golden(GOLDEN_V027, "datasets___/datasets_crud--03.json", ["data"])
    rec = _record()
    assert sorted(dataset(rec, PROFILE_V027).keys()) == sorted(create.keys())
    assert sorted(dataset_listed(rec, PROFILE_V027).keys()) == sorted(listed.keys())
    assert sorted(dataset_updated(rec, PROFILE_V027).keys()) == sorted(updated.keys())
    # ``llm_id`` zależy od nagrania (rekord testowy ma ``fake-chat``), reszta kluczy nie.
    parser_config = dataset(rec, PROFILE_V027)["parser_config"]
    golden_parser_config = dict(
        _golden(GOLDEN_V027, "datasets/datasets_crud--01.json", ["data", "parser_config"])
    )
    assert sorted(parser_config.keys()) == sorted(golden_parser_config.keys())
    assert parser_config["llm_id"] == LLM_ID
    for key, value in golden_parser_config.items():
        if key != "llm_id":
            assert parser_config[key] == value
