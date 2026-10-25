"""Testy domyślnego `search_config` wyszukiwarki (CONTRACT E4-4a §D2, K15 §1)."""

from app.domain.search.config import DEFAULT_SEARCH_CONFIG, default_config

# Wartości dosłownie z CONTRACT §D2 (upstream `db_models.py` `Search.search_config`).
EXPECTED = {
    "kb_ids": [],
    "doc_ids": [],
    "similarity_threshold": 0.2,
    "vector_similarity_weight": 0.3,
    "use_kg": False,
    "rerank_id": "",
    "top_k": 1024,
    "summary": False,
    "chat_id": "",
    "llm_setting": {
        "temperature": 0.1,
        "top_p": 0.3,
        "frequency_penalty": 0.7,
        "presence_penalty": 0.4,
        "temperature_enabled": True,
        "top_p_enabled": True,
        "frequency_penalty_enabled": True,
        "presence_penalty_enabled": True,
    },
    "chat_settingcross_languages": [],
    "highlight": False,
    "keyword": False,
    "web_search": False,
    "related_search": False,
    "query_mindmap": False,
}


def test_constant_matches_contract() -> None:
    """`DEFAULT_SEARCH_CONFIG` = dosłowny obiekt z §D2 (16 kluczy, w tym zlepek upstreamu)."""
    assert DEFAULT_SEARCH_CONFIG == EXPECTED


def test_default_config_returns_equal_copy() -> None:
    """`default_config()` zwraca dict równy stałej (płytkie == zagnieżdżone porównuje)."""
    config = default_config()
    assert isinstance(config, dict)
    assert config == EXPECTED


def test_default_config_mutation_does_not_touch_constant() -> None:
    """Mutacja wyniku (nawet zagnieżdżonych list/słowników) nie psuje stałej."""
    config = default_config()
    config["similarity_threshold"] = 0.9
    config["kb_ids"].append("kb-1")
    config["doc_ids"].append("doc-1")
    config["chat_settingcross_languages"].append("pl")
    config["llm_setting"]["temperature"] = 9.9

    assert config["llm_setting"] is not DEFAULT_SEARCH_CONFIG["llm_setting"]
    assert DEFAULT_SEARCH_CONFIG == EXPECTED
