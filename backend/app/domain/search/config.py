"""Domyślny `search_config` wyszukiwarki (K15 §1, CONTRACT E4-4a §D2).

Zestaw flag i liczb, który dostaje nowe wyszukiwanie, gdy klient nie poda własnych ustawień.
Klucz `chat_settingcross_languages` bywa mylący: to jeden zlepek, nie `chat_setting` +
`cross_languages` — zostaje w tej postaci, bo tak go zapisuje i odczytuje złoto.
`kb_ids` nie trafia do kolumny `search_config` — wiązania żyją w `search_datasets`,
a prezenter dokłada `kb_ids` przy odczycie.
"""

from collections.abc import Mapping
from typing import Any, Final

DEFAULT_SEARCH_CONFIG: Final[Mapping[str, Any]] = {
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


def default_config() -> dict[str, Any]:
    """Głęboka kopia `DEFAULT_SEARCH_CONFIG` — mutacja wyniku nie psuje stałej (K15 §1)."""
    config = dict(DEFAULT_SEARCH_CONFIG)
    config["llm_setting"] = dict(DEFAULT_SEARCH_CONFIG["llm_setting"])
    config["kb_ids"] = list(DEFAULT_SEARCH_CONFIG["kb_ids"])
    config["doc_ids"] = list(DEFAULT_SEARCH_CONFIG["doc_ids"])
    config["chat_settingcross_languages"] = list(
        DEFAULT_SEARCH_CONFIG["chat_settingcross_languages"]
    )
    return config
