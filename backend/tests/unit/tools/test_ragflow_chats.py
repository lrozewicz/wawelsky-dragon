"""Testy czystych funkcji etapu ``chats`` (brief T1, kontrakt §2) — bez bazy."""

from typing import Any

from app.tools.ragflow_migrate.model_map import MappedModel, ModelMap
from app.tools.ragflow_migrate.stages.base import Issue
from app.tools.ragflow_migrate.stages.chats_rows import (
    chat_name,
    chat_name_collision_groups,
    json_object_text,
    optional_json_text,
    parse_kb_ids,
    resolve_chats,
)

#: Id z fixture'u (kolejność i wartości jak ``tests/fixtures/ragflow_v024``).
U1_ID = "b0a1c2d3e4f5061728394a5b6c7d8e91"
U2_ID = "b0a1c2d3e4f5061728394a5b6c7d8e92"
DIALOG_ID = "e1f2a3b4c5d60718293a4b5c6d7e8f01"
CREATE_TIME = 1759306080000
NOW_MS = 1759999999000
RERANK_CANDIDATES = 64
CHAT_KEY = "fake-chat@OpenAI-API-Compatible"

#: Mapa modeli z fixture'u (``model-map.yaml``) — wpis ``fake-chat``.
FIXTURE_MAP = ModelMap({CHAT_KEY: MappedModel(name="fake-chat", model_type="chat", dimension=None)})

#: Argumenty ``resolve_chats`` wspólne dla przypadków: właściciel, mapa, brak datasetów w celu.
_BASE: dict[str, Any] = {
    "owner_ids": {U1_ID, U2_ID},
    "model_names": {},
    "model_map": FIXTURE_MAP,
    "dataset_ids": set(),
    "embeddings": {},
    "stored_times": {DIALOG_ID: (CREATE_TIME, CREATE_TIME)},
    "now_ms": NOW_MS,
}


def row(**overrides: Any) -> dict[str, Any]:
    """Wiersz ``dialog`` o kształcie fixture'u, z nadpisanymi polami."""
    values: dict[str, Any] = {
        "id": DIALOG_ID,
        "tenant_id": U1_ID,
        "name": "chat-rag",
        "description": None,
        "icon": None,
        "language": "English",
        "llm_id": CHAT_KEY,
        "llm_setting": '{"temperature": 0.1}',
        "prompt_type": "simple",
        "prompt_config": '{"system": "Test."}',
        "meta_data_filter": None,
        "similarity_threshold": 0.2,
        "vector_similarity_weight": 0.3,
        "top_n": 6,
        "top_k": 1024,
        "do_refer": "1",
        "rerank_id": "",
        "kb_ids": "[]",
        "status": "1",
        "create_time": CREATE_TIME,
        "update_time": CREATE_TIME,
    }
    values.update(overrides)
    return values


def resolve(
    dialog: dict[str, Any], **overrides: Any
) -> tuple[list[dict[str, Any]], dict[str, list[str]], list[Issue]]:
    """``resolve_chats`` dla jednego wiersza, z domyślnymi argumentami przypadku."""
    args = {**_BASE, **overrides}
    return resolve_chats(
        [dialog],
        args["owner_ids"],
        args["model_names"],
        args["model_map"],
        args["dataset_ids"],
        args["embeddings"],
        args["stored_times"],
        args["now_ms"],
    )


def single(
    dialog: dict[str, Any], **overrides: Any
) -> tuple[dict[str, Any], list[str], list[Issue]]:
    """Wynik dla jednego wiersza, który ma trafić do celu (asercja liczby wierszy)."""
    targets, links, issues = resolve(dialog, **overrides)
    assert len(targets) == 1
    return targets[0], links[DIALOG_ID], issues


def resolve_many(
    rows: list[dict[str, Any]], **overrides: Any
) -> tuple[list[dict[str, Any]], dict[str, list[str]], list[Issue]]:
    """``resolve_chats`` dla wielu wierszy (przypadki kolizji nazw)."""
    args = {**_BASE, **overrides}
    return resolve_chats(
        rows,
        args["owner_ids"],
        args["model_names"],
        args["model_map"],
        args["dataset_ids"],
        args["embeddings"],
        args["stored_times"],
        args["now_ms"],
    )


def codes(issues: list[Issue]) -> list[tuple[str, str]]:
    """Pary ``(kod, waga)`` uwag — do zwięzłych asercji."""
    return [(issue.code, issue.severity) for issue in issues]


def test_defaults_for_empty_source_values() -> None:
    """NULL/puste pola źródła → wartości domyślne WD (kontrakt §2)."""
    target, links, issues = single(
        row(
            name=None,
            description=None,
            icon="",
            language=None,
            prompt_type="",
            do_refer=None,
            status=None,
        )
    )
    assert target["name"] == DIALOG_ID
    assert target["description"] == ""
    assert target["icon"] is None
    assert target["language"] == "English"
    assert target["prompt_type"] == "simple"
    assert target["do_refer"] == "1"
    assert target["status"] == "1"
    assert target["rerank_candidates_count"] == RERANK_CANDIDATES
    assert target["tenant_id"] == U1_ID
    assert target["created_by"] == U1_ID
    assert links == []
    assert issues == []


def test_valid_json_is_kept_and_empty_becomes_object() -> None:
    """Poprawny JSON przechodzi 1:1 (bez escapingu znaków), NULL/pusty → ``{}`` bez uwagi."""
    target, _links, issues = single(row(llm_setting='{"temperature": 0.1, "max_tokens": 512}'))
    assert target["llm_setting"] == '{"temperature": 0.1, "max_tokens": 512}'
    empty, _links, issues_empty = single(row(llm_setting=None, prompt_config=""))
    assert empty["llm_setting"] == "{}"
    assert empty["prompt_config"] == "{}"
    assert issues == []
    assert issues_empty == []


def test_invalid_json_becomes_empty_object_with_issue() -> None:
    """Niepoprawny JSON (także JSON nie-obiekt) → ``{}`` i warning ``chat_json_invalid``."""
    target, _links, issues = single(row(llm_setting="nie-json", prompt_config="[1, 2]"))
    assert target["llm_setting"] == "{}"
    assert target["prompt_config"] == "{}"
    assert codes(issues) == [("chat_json_invalid", "warning"), ("chat_json_invalid", "warning")]
    assert {issue.ids[0] for issue in issues} == {DIALOG_ID}


def test_json_object_text_returns_flag_for_broken_value() -> None:
    """``json_object_text``: ``False`` tylko dla wartości poprawnej albo pustej."""
    assert json_object_text('{"a": 1}') == ('{"a": 1}', False)
    assert json_object_text(None) == ("{}", False)
    assert json_object_text('"tekst"') == ("{}", True)
    assert json_object_text("{nie-json") == ("{}", True)


def test_meta_data_filter_keeps_only_non_empty_object() -> None:
    """``meta_data_filter``: niepusty obiekt → tekst JSON, wszystko inne → ``None``."""
    assert optional_json_text('{"method": "auto", "from_llm": false}') == (
        '{"method": "auto", "from_llm": false}'
    )
    for value in (None, "", "{}", "nie-json", "[1]"):
        assert optional_json_text(value) is None


def test_kb_ids_are_deduplicated_with_order_kept() -> None:
    """``kb_ids``: duplikaty usunięte, kolejność pierwszego wystąpienia zachowana (§2)."""
    target, links, issues = single(
        row(kb_ids='["ds-2", "ds-1", "ds-2"]'),
        dataset_ids={"ds-1", "ds-2"},
        embeddings={"ds-1": ("m", 1024), "ds-2": ("m", 1024)},
    )
    assert target["id"] == DIALOG_ID
    assert links == ["ds-2", "ds-1"]
    assert issues == []


def test_invalid_kb_ids_is_empty_with_issue() -> None:
    """Niepoprawny JSON w ``kb_ids`` → brak powiązań i warning ``chat_json_invalid``."""
    for value in ("nie-json", '{"ds": 1}'):
        target, links, issues = single(row(kb_ids=value))
        assert target["id"] == DIALOG_ID
        assert links == []
        assert codes(issues) == [("chat_json_invalid", "warning")]


def test_parse_kb_ids_ignores_null_and_empty_text() -> None:
    """Puste ``kb_ids`` źródła → pusta lista bez uwagi."""
    assert parse_kb_ids(None) == ([], False)
    assert parse_kb_ids("") == ([], False)
    assert parse_kb_ids('["ds-1"]') == (["ds-1"], False)


def test_model_name_from_shared_names_wins_over_model_map() -> None:
    """Nazwa modelu: ``ctx.shared['model_names']`` przed ``ctx.model_map`` (kontrakt §2)."""
    target, _links, issues = single(
        row(llm_id="chat@Faktura"),
        model_names={"chat@Faktura": "chat-wd"},
        model_map=ModelMap(
            {"chat@Faktura": MappedModel(name="inna-nazwa", model_type="chat", dimension=None)}
        ),
    )
    assert target["llm_id"] == "chat-wd"
    assert issues == []
    from_map, _links, _issues = single(row(llm_id=CHAT_KEY), model_names={})
    assert from_map["llm_id"] == "fake-chat"


def test_unmapped_llm_and_rerank_warn_and_stay_empty() -> None:
    """Model spoza map i celu → warning i pusta wartość; puste ``rerank_id`` bez uwagi."""
    target, _links, issues = single(
        row(llm_id="brak@nikt", rerank_id="rerank@nikt"), model_map=ModelMap({})
    )
    assert target["llm_id"] == ""
    assert target["rerank_id"] == ""
    assert codes(issues) == [
        ("chat_llm_unmapped", "warning"),
        ("chat_rerank_unmapped", "warning"),
    ]
    mapped, _links, mapped_issues = single(row(rerank_id=""))
    assert mapped["rerank_id"] == ""
    assert mapped_issues == []


def test_missing_dataset_warns_and_link_is_skipped() -> None:
    """Dataset spoza celu → warning z oboma id, czat zapisany bez powiązania (§2)."""
    target, links, issues = single(
        row(kb_ids='["nie-ma"]'), dataset_ids={"ds-1"}, embeddings={"ds-1": ("m", 1024)}
    )
    assert target["id"] == DIALOG_ID
    assert links == []
    assert codes(issues) == [("chat_dataset_missing", "warning")]
    assert issues[0].ids == [DIALOG_ID, "nie-ma"]


def test_embedding_mismatch_warns_and_chat_is_kept() -> None:
    """Różne embeddingi datasetów czatu → warning ``chat_embedding_mismatch``, zapis mimo to."""
    _target, links, issues = single(
        row(kb_ids='["ds-1", "ds-2"]'),
        dataset_ids={"ds-1", "ds-2"},
        embeddings={"ds-1": ("m-1024", 1024), "ds-2": ("m-2048", 2048)},
    )
    assert links == ["ds-1", "ds-2"]
    assert codes(issues) == [("chat_embedding_mismatch", "warning")]
    assert issues[0].ids == [DIALOG_ID]


def test_chat_name_collision_groups_are_case_insensitive_per_tenant() -> None:
    """Kolizja nazw: bez wielkości liter, w obrębie jednego tenanta (kontrakt §2)."""
    rows = [
        row(id="aaa", name="Chat X"),
        row(id="bbb", name="chat x"),
        row(id="ccc", name="inny"),
        row(id="ddd", name="Chat X", tenant_id=U2_ID),
    ]
    assert chat_name_collision_groups(rows) == [["aaa", "bbb"]]
    assert chat_name(rows[0]) == "Chat X"


def test_name_collision_skips_both_rows_with_critical() -> None:
    """Dwa dialogi o tej samej nazwie w tenancie → critical ``chat_name_collision`` i brak celów."""
    targets, links, issues = resolve_many(
        [row(id="aaa", name="Chat X"), row(id="bbb", name="chat x")]
    )
    assert targets == []
    assert links == {}
    assert codes(issues) == [("chat_name_collision", "critical")]
    assert issues[0].ids == ["aaa", "bbb"]


def test_owner_missing_is_critical_and_row_is_not_written() -> None:
    """Właściciel spoza celu → critical ``chat_owner_missing``, brak wiersza i powiązań."""
    targets, links, issues = resolve(row(tenant_id="b0a1c2d3e4f5061728394a5b6c7d8e99"))
    assert targets == []
    assert links == {}
    assert codes(issues) == [("chat_owner_missing", "critical")]
    assert issues[0].ids == [DIALOG_ID]


def test_null_times_fall_back_to_stored_row_then_to_clock() -> None:
    """NULL w źródle → czas istniejącego wiersza celu, a gdy go nie ma — ``ctx.clock`` (§2)."""
    stored, _links, _issues = single(row(create_time=None, update_time=None))
    assert (stored["create_time"], stored["update_time"]) == (CREATE_TIME, CREATE_TIME)
    fresh, _links, _issues = single(row(create_time=None, update_time=None), stored_times={})
    assert (fresh["create_time"], fresh["update_time"]) == (NOW_MS, NOW_MS)
