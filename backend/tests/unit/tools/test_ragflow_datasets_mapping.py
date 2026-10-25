"""Testy czystych funkcji etapu ``datasets`` (brief T6, kontrakt §4) — bez bazy."""

import json
from typing import Any

from app.services.datasets import DEFAULT_PARSER_CONFIG
from app.tools.ragflow_migrate.stages.datasets import (
    CHUNK_METHODS,
    KNOWN_PARSER_CONFIG_KEYS,
    LEGACY_PARSER_CONFIG_KEY,
    map_chunk_method,
    name_collision_groups,
    raw_parser_config,
    resolve_datasets,
    split_parser_config,
)

#: ``parser_id`` RAGFlow v0.24 obsługiwane przez WD (``_PRESETS`` w ``app/domain/chunking``).
SUPPORTED_PARSER_IDS = (
    "naive",
    "email",
    "manual",
    "book",
    "laws",
    "paper",
    "presentation",
    "one",
    "picture",
    "qa",
    "table",
)

#: ``parser_id`` odrzucane przez WD (``UNSUPPORTED_CHUNK_METHODS``).
UNSUPPORTED_PARSER_IDS = ("tag", "knowledge_graph", "resume", "audio")

#: Wartości wiersza źródłowego użyte w asercjach (kształt fixture'u).
EMBEDDING_DIM = 1024
DOC_NUM = 2
CHUNK_NUM = 10
TOKEN_NUM = 1000
CREATE_TIME = 1759305840000


def test_supported_parser_ids_map_to_themselves() -> None:
    """Każda metoda obsługiwana przez WD ma wpis i mapuje się na tę samą nazwę."""
    assert set(SUPPORTED_PARSER_IDS) == set(CHUNK_METHODS)
    for parser_id in SUPPORTED_PARSER_IDS:
        assert map_chunk_method(parser_id) == parser_id


def test_unsupported_and_unknown_parser_ids_are_none() -> None:
    """Metody odrzucane przez WD i wartości spoza słownika RAGFlow → ``None``."""
    for parser_id in (*UNSUPPORTED_PARSER_IDS, "pipeline", ""):
        assert map_chunk_method(parser_id) is None


def test_split_parser_config_keeps_known_keys_on_top() -> None:
    """Znane klucze zostają wprost, nieznane lądują pod kluczem legacy."""
    assert split_parser_config(
        {"chunk_token_num": 128, "delimiter": "\n", "layout_recognize": "DeepDOC", "unknown_key": 1}
    ) == {
        "chunk_token_num": 128,
        "delimiter": "\n",
        "layout_recognize": "DeepDOC",
        LEGACY_PARSER_CONFIG_KEY: {"unknown_key": 1},
    }


def test_split_parser_config_omits_legacy_key_when_nothing_is_unknown() -> None:
    """Bez nieznanych kluczy nie ma klucza legacy (kontrakt §4)."""
    result = split_parser_config({"chunk_token_num": 256, "pages": [[1, 10]]})
    assert result == {"chunk_token_num": 256, "pages": [[1, 10]]}
    assert LEGACY_PARSER_CONFIG_KEY not in result


def test_split_parser_config_accepts_nested_known_keys() -> None:
    """``parent_child``/``raptor``/``graphrag`` są znane — nie trafiają do legacy."""
    result = split_parser_config({"parent_child": {"use_parent_child": False}, "extra": 1})
    assert result == {
        "parent_child": {"use_parent_child": False},
        LEGACY_PARSER_CONFIG_KEY: {"extra": 1},
    }


def test_split_parser_config_of_empty_dict_is_empty() -> None:
    """Pusty ``parser_config`` źródła → pusty konfig WD."""
    assert split_parser_config({}) == {}


def test_known_parser_config_keys_cover_defaults() -> None:
    """Lista znanych kluczy pokrywa wszystkie klucze ``DEFAULT_PARSER_CONFIG`` WD."""
    assert set(DEFAULT_PARSER_CONFIG) <= KNOWN_PARSER_CONFIG_KEYS


def test_raw_parser_config_parses_text_dict_and_none() -> None:
    """Kolumna źródła (tekst JSON albo ``dict``) → ``dict``; NULL → pusto."""
    assert raw_parser_config('{"chunk_token_num": 128}') == {"chunk_token_num": 128}
    assert raw_parser_config({"pages": [[1, 2]]}) == {"pages": [[1, 2]]}
    assert raw_parser_config(None) == {}


def test_name_collision_groups_ignores_case_and_other_tenants() -> None:
    """Kolizja to ta sama nazwa (bez wielkości liter) w tym samym tenancie."""
    rows = [
        {"id": "a", "tenant_id": "t1", "name": "Report"},
        {"id": "b", "tenant_id": "t1", "name": "report"},
        {"id": "c", "tenant_id": "t2", "name": "report"},
    ]
    assert name_collision_groups(rows) == [["a", "b"]]


def _row(**overrides: Any) -> dict[str, Any]:
    """Wiersz źródła ``knowledgebase`` w kształcie fixture'u (kontrakt §4)."""
    row: dict[str, Any] = {
        "id": "d1e2f3a4b5c60718293a4b5c6d7e8f01",
        "create_time": 1759305840000,
        "update_time": 1759305840000,
        "avatar": None,
        "tenant_id": "t1",
        "name": "kb-naive",
        "language": "English",
        "description": None,
        "embd_id": "fake-embed-1024@OpenAI-API-Compatible",
        "permission": "me",
        "created_by": "t1",
        "doc_num": 2,
        "token_num": 1000,
        "chunk_num": 10,
        "similarity_threshold": 0.2,
        "vector_similarity_weight": 0.3,
        "parser_id": "naive",
        "parser_config": '{"chunk_token_num": 128, "unknown_key": 1}',
        "pagerank": 0,
        "status": "1",
    }
    row.update(overrides)
    return row


def _resolve(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """``resolve_datasets`` z mapą fixture'u (nazwa i wymiar embeddingu znane)."""
    names = {"fake-embed-1024@OpenAI-API-Compatible": "fake-embed-1024"}
    dimensions = {"fake-embed-1024@OpenAI-API-Compatible": 1024}
    targets, issues = resolve_datasets(rows, {"t1"}, names, dimensions, 0)
    return targets, [issue.code for issue in issues if issue.severity == "critical"]


def test_resolve_datasets_maps_row_columns() -> None:
    """Wiersz bez problemów daje kolumny celu: progi, liczniki, czasy, ``parser_config``."""
    targets, critical = _resolve([_row()])
    assert critical == []
    target = targets[0]
    assert target["id"] == "d1e2f3a4b5c60718293a4b5c6d7e8f01"
    assert target["embedding_model"] == "fake-embed-1024"
    assert target["embedding_dim"] == EMBEDDING_DIM
    assert target["chunk_method"] == "naive"
    assert json.loads(target["parser_config"]) == {
        "chunk_token_num": 128,
        LEGACY_PARSER_CONFIG_KEY: {"unknown_key": 1},
    }
    assert target["document_count"] == DOC_NUM
    assert target["chunk_count"] == CHUNK_NUM
    assert target["token_num"] == TOKEN_NUM
    assert target["create_time"] == CREATE_TIME
    assert target["tenant_id"] == "t1"
    assert target["language"] == "English"


def test_resolve_datasets_skips_unsupported_chunk_method() -> None:
    """``parser_id='resume'`` → critical ``chunk_method_unsupported`` i brak wiersza celu."""
    targets, critical = _resolve([_row(parser_id="resume")])
    assert targets == []
    assert critical == ["chunk_method_unsupported"]


def test_resolve_datasets_skips_unknown_dimension() -> None:
    """Brak wymiaru w mapie → critical ``embedding_dim_unknown`` i brak wiersza celu."""
    targets, issues = resolve_datasets(
        [_row()],
        {"t1"},
        {"fake-embed-1024@OpenAI-API-Compatible": "fake-embed-1024"},
        {},
        0,
    )
    assert targets == []
    assert [issue.code for issue in issues] == ["embedding_dim_unknown"]


def test_resolve_datasets_skips_missing_owner() -> None:
    """Właściciel spoza ``owner_ids`` → critical ``dataset_owner_missing``."""
    targets, critical = _resolve([_row(tenant_id="t-orphan")])
    assert targets == []
    assert critical == ["dataset_owner_missing"]


def test_resolve_datasets_collision_blocks_both_rows() -> None:
    """Dwie nazwy tej samej w tenancie → critical ``dataset_name_collision`` i brak obu wierszy."""
    rows = [_row(id="a"), _row(id="b", name="kb-naive")]
    targets, critical = _resolve(rows)
    assert targets == []
    assert critical == ["dataset_name_collision"]
