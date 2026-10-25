"""Testy present/datasets: zbiory kluczy i wartości wg złota v0.27.2 (kontrakt E1-9a C1.4)."""

import json
from pathlib import Path
from typing import Any

from app.api.ragflow.present.datasets import (
    dataset,
    dataset_detail,
    dataset_listed,
    dataset_updated,
)
from app.services.datasets import DEFAULT_PARSER_CONFIG, DatasetRecord

PROFILE = "ragflow_0_27"
NOW_MS = 1790157600000  # → "2026-09-23 10:00:00" UTC (date())

GOLDEN = Path(__file__).resolve().parents[3] / "contract" / "golden" / "v0.27.2"


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
        parser_config={**DEFAULT_PARSER_CONFIG, "llm_id": "fake-chat"},
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


def _golden(name: str, path: list[Any]) -> Any:
    """Węzeł body pliku złota po przejściu po ``path`` (np. ["data", 0])."""
    node: Any = json.loads((GOLDEN / name).read_text(encoding="utf-8"))["body"]
    for part in path:
        node = node[part]
    return node


def test_dataset_keys_match_golden_create() -> None:
    """dataset() ma dokładnie zbiór kluczy body.data złota POST (datasets_crud--01)."""
    golden = _golden("datasets/datasets_crud--01.json", ["data"])
    assert sorted(dataset(_record(), PROFILE).keys()) == sorted(golden.keys())


def test_dataset_values() -> None:
    """Wartości dataset(): stałe, daty i znaczniki czasu (C1.4, C0 p. 6)."""
    data = dataset(_record(), PROFILE)
    assert data["id"] == "d" * 32
    assert data["tenant_id"] == data["created_by"] == "u" * 32
    assert data["name"] == "wd_rec_ds"
    assert data["language"] == "English"
    assert data["permission"] == "me"
    assert data["chunk_method"] == "naive"
    assert data["status"] == "1"
    assert data["embedding_model"] == "fake-embed-1024"
    assert data["parser_config"] == {**DEFAULT_PARSER_CONFIG, "llm_id": "fake-chat"}
    assert data["create_time"] == data["update_time"] == NOW_MS
    assert data["create_date"] == data["update_date"] == "2026-09-23 10:00:00"
    assert data["pagerank"] == 0
    assert data["document_count"] == data["chunk_count"] == data["token_num"] == 0
    assert data["avatar"] is data["description"] is None
    assert data["pipeline_id"] is data["tenant_embd_id"] is None
    for key in (
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
    ):
        assert data[f"{key}_task_id"] is None
        assert data[f"{key}_task_finish_at"] is None


def test_dataset_updated_keys_match_golden_put() -> None:
    """dataset_updated() = dataset() + connectors: [] (złoto PUT, datasets_crud--03)."""
    golden = _golden("datasets___/datasets_crud--03.json", ["data"])
    data = dataset_updated(_record(), PROFILE)
    assert sorted(data.keys()) == sorted(golden.keys())
    assert data["connectors"] == []


def test_dataset_detail_has_connectors() -> None:
    """dataset_detail() jak updated: connectors [] (GET /datasets/{id}, C1.4)."""
    assert dataset_detail(_record(), PROFILE, 0)["connectors"] == []


def test_dataset_detail_has_size_matching_golden_get() -> None:
    """dataset_detail() = updated + ``size`` (złoto GET datasets_extras--06: size 1319)."""
    golden = _golden("datasets___/datasets_extras--06.json", ["data"])
    data = dataset_detail(_record(), PROFILE, golden["size"])
    assert data["size"] == golden["size"] == 1319  # noqa: PLR2004 — wartość ze złota
    assert sorted(data.keys()) == sorted(golden.keys())
    assert "size" not in dataset_updated(_record(), PROFILE)


def test_dataset_listed_keys_match_golden_get() -> None:
    """dataset_listed() = dataset() + nickname/tenant_avatar/embedding_model_name (--02)."""
    golden = _golden("datasets/datasets_crud--02.json", ["data", 0])
    data = dataset_listed(_record(), PROFILE)
    assert sorted(data.keys()) == sorted(golden.keys())
    assert data["nickname"] == "Alice"
    assert data["tenant_avatar"] is None
    assert data["embedding_model_name"] == ""
