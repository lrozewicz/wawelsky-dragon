"""Testy czystych pomocników DatasetService: deep_merge i unique_name (brief T1a)."""

from app.services.datasets import DEFAULT_PARSER_CONFIG, deep_merge, unique_name


def test_deep_merge_overrides_leaves_and_adds_keys() -> None:
    """deep_merge: klucze dict scalane rekurencyjnie, pozostałe nadpisywane (brief T1a)."""
    base = {"a": 1, "p": {"x": 1, "y": 2}}
    override = {"p": {"y": 3}, "b": 2}
    merged = deep_merge(base, override)
    assert merged == {"a": 1, "p": {"x": 1, "y": 3}, "b": 2}
    assert base == {"a": 1, "p": {"x": 1, "y": 2}}  # argumenty niezmienione
    assert override == {"p": {"y": 3}, "b": 2}


def test_deep_merge_non_dict_value_replaces_dict() -> None:
    """Wartość niebędąca dict nadpisuje dict z bazy (upstream api_utils deep_merge)."""
    assert deep_merge({"p": {"x": 1}}, {"p": 5}) == {"p": 5}
    assert deep_merge({"a": [1]}, {"a": [1, 2]}) == {"a": [1, 2]}
    assert deep_merge({}, {"only": True}) == {"only": True}


def test_unique_name_free_name_unchanged() -> None:
    """Wolna nazwa zwracana bez zmian (brief T1a)."""
    assert unique_name("b", set()) == "b"


def test_unique_name_appends_counter() -> None:
    """Zajęta nazwa → stem(1).ext (brief T1a)."""
    assert unique_name("x", {"x"}) == "x(1)"
    assert unique_name("a.txt", {"a.txt"}) == "a(1).txt"


def test_unique_name_increments_existing_counter() -> None:
    """Zajęte stem(1).ext → stem(2).txt (brief T1a)."""
    assert unique_name("a.txt", {"a.txt", "a(1).txt"}) == "a(2).txt"


def test_unique_name_is_case_insensitive() -> None:
    """Porównanie na małych literach, zwracana oryginalna wielkość (brief T1a)."""
    assert unique_name("A.txt", {"a.txt"}) == "A(1).txt"


def test_default_parser_config_matches_gold() -> None:
    """DEFAULT_PARSER_CONFIG = złoto G/datasets/datasets_crud--01.json (poza llm_id)."""
    assert DEFAULT_PARSER_CONFIG == {
        "auto_keywords": 0,
        "auto_questions": 0,
        "children_delimiter": "",
        "chunk_token_num": 512,
        "delimiter": "\n",
        "html4excel": False,
        "image_context_size": 0,
        "layout_recognize": "DeepDOC",
        "llm_id": "",
        "parent_child": {"children_delimiter": "\n", "use_parent_child": False},
        "table_context_size": 0,
        "topn_tags": 3,
    }
