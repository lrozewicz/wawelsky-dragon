"""Testy normalizacji wejścia Chat v0.24 (CONTRACT C1) — tabela 02-api §7.1 dosłownie."""

import copy
from typing import Any

import pytest

from app.api.ragflow.normalize.chats import parse_chat_create, parse_chat_update
from app.api.ragflow.normalize.chats_v024 import to_canonical
from app.core.errors import Conflict

PROFILE_V024 = "ragflow_0_24"
PROFILE_V027 = "ragflow_0_27"

# Tabela 02-api §7.1, wiersz po wierszu (C1). Wiersz ``do_refer``/``show_quotation``: C1 (wiążący)
# mówi „usuwane z wyniku" — kanoniczne ChatInput nie zna tego klucza, więc (...)_DROPPED.
_TABLE: list[Any] = [
    pytest.param({"avatar": "a.png"}, {"icon": "a.png"}, id="avatar-icon"),
    pytest.param({"llm": {"model_name": "m"}}, {"llm_id": "m"}, id="llm-model-name"),
    pytest.param(
        {
            "llm": {
                "temperature": 0.1,
                "top_p": 0.3,
                "presence_penalty": 0.4,
                "frequency_penalty": 0.7,
                "max_tokens": 512,
            }
        },
        {
            "llm_setting": {
                "temperature": 0.1,
                "top_p": 0.3,
                "presence_penalty": 0.4,
                "frequency_penalty": 0.7,
                "max_tokens": 512,
            }
        },
        id="llm-settings",
    ),
    pytest.param(
        {"prompt": {"prompt": "sys {knowledge}"}},
        {"prompt_config": {"system": "sys {knowledge}"}},
        id="prompt-system",
    ),
    pytest.param(
        {"prompt": {"opener": "Hi"}}, {"prompt_config": {"prologue": "Hi"}}, id="prompt-prologue"
    ),
    pytest.param(
        {"prompt": {"show_quote": True}}, {"prompt_config": {"quote": True}}, id="prompt-quote"
    ),
    pytest.param(
        {"prompt": {"variables": [{"key": "k", "optional": False}]}},
        {"prompt_config": {"parameters": [{"key": "k", "optional": False}]}},
        id="prompt-parameters",
    ),
    pytest.param(
        {"prompt": {"empty_response": "Sorry!"}},
        {"prompt_config": {"empty_response": "Sorry!"}},
        id="prompt-empty-response",
    ),
    pytest.param({"prompt": {"tts": False}}, {"prompt_config": {"tts": False}}, id="prompt-tts"),
    pytest.param(
        {"prompt": {"refine_multiturn": True}},
        {"prompt_config": {"refine_multiturn": True}},
        id="prompt-refine-multiturn",
    ),
    pytest.param(
        {"prompt": {"similarity_threshold": 0.2}},
        {"similarity_threshold": 0.2},
        id="prompt-similarity",
    ),
    pytest.param(
        {"prompt": {"keywords_similarity_weight": 0.7}},
        {"vector_similarity_weight": 0.3},
        id="prompt-keywords-weight",
    ),
    pytest.param({"prompt": {"top_n": 6}}, {"top_n": 6}, id="prompt-top-n"),
    # C1 (uzupełnienie po T1): upstream v0.24 przenosi ``prompt.top_k`` na górny poziom.
    pytest.param({"prompt": {"top_k": 1024}}, {"top_k": 1024}, id="prompt-top-k"),
    pytest.param({"prompt": {"rerank_model": "r"}}, {"rerank_id": "r"}, id="prompt-rerank"),
    pytest.param({"dataset_ids": ["a"]}, {"dataset_ids": ["a"]}, id="dataset-ids"),
    pytest.param({"datasets": [{"id": "b"}]}, {"dataset_ids": ["b"]}, id="datasets-ids"),
    pytest.param({"do_refer": "1"}, {}, id="do-refer-dropped"),
    pytest.param({"show_quotation": True}, {}, id="show-quotation-dropped"),
]


@pytest.mark.parametrize(("body", "expected"), _TABLE)
def test_table_rows(body: dict[str, Any], expected: dict[str, Any]) -> None:
    """Każdy wiersz tabeli tłumaczenia §7.1 osobno (C1)."""
    assert to_canonical(body) == expected


def test_empty_llm_and_empty_prompt_emit_nothing() -> None:
    """Puste obiekty v0.24 nie tworzą kluczy kanonicznych (C1: klucz nieobecny → brak w wyniku)."""
    assert to_canonical({"llm": {}}) == {}
    assert to_canonical({"prompt": {}}) == {}
    assert to_canonical({"llm": {}, "prompt": {}}) == {}


def test_prompt_without_keywords_weight_has_no_vector_weight() -> None:
    """Brak ``keywords_similarity_weight`` → brak ``vector_similarity_weight`` w wyniku."""
    assert to_canonical({"prompt": {"top_n": 3}}) == {"top_n": 3}


def test_dataset_ids_wins_over_datasets() -> None:
    """Oba klucze naraz: wygrywa ``dataset_ids``, ``datasets`` znika (C1)."""
    body = {"name": "n", "dataset_ids": ["a"], "datasets": [{"id": "b"}]}
    assert to_canonical(body) == {"name": "n", "dataset_ids": ["a"]}


@pytest.mark.parametrize(
    ("keywords_weight", "vector_weight"), [(0.7, 0.3), (0.0, 1.0), (1, 0.0), (0.1, 0.9)]
)
def test_keywords_similarity_weight_is_inverted(
    keywords_weight: float, vector_weight: float
) -> None:
    """Odwrócenie wagi dokładnie dzięki ``round(…, 6)`` (C1, §7.1)."""
    result = to_canonical({"prompt": {"keywords_similarity_weight": keywords_weight}})
    assert result == {"vector_similarity_weight": vector_weight}


@pytest.mark.parametrize("value", [[], "x", 5, None])
def test_llm_must_be_object(value: object) -> None:
    """``llm`` nie-dict → Conflict (C1); None tak jak w kanonicznym ``_normalize``."""
    with pytest.raises(Conflict) as exc:
        to_canonical({"llm": value})
    assert str(exc.value) == "`llm` should be an object."


@pytest.mark.parametrize("value", [[], "x", 5, None])
def test_prompt_must_be_object(value: object) -> None:
    """``prompt`` nie-dict → Conflict (C1)."""
    with pytest.raises(Conflict) as exc:
        to_canonical({"prompt": value})
    assert str(exc.value) == "`prompt` should be an object."


@pytest.mark.parametrize("value", [True, False, "0.7", None, [0.7]])
def test_keywords_similarity_weight_must_be_number(value: object) -> None:
    """``keywords_similarity_weight`` nie-liczba (bool też) → Conflict (C1)."""
    with pytest.raises(Conflict) as exc:
        to_canonical({"prompt": {"keywords_similarity_weight": value}})
    assert str(exc.value) == "`keywords_similarity_weight` should be a number."


def test_does_not_mutate_input_and_returns_deep_copies() -> None:
    """Czysta funkcja: wejście nietknięte, a wynik nie dzieli obiektów z wejściem (C1)."""
    body: dict[str, Any] = {
        "name": "n",
        "avatar": "a.png",
        "llm": {"model_name": "m", "top_p": 0.3},
        "prompt": {"variables": [{"key": "k", "optional": False}]},
        "datasets": [{"id": "d1"}],
    }
    snapshot = copy.deepcopy(body)
    result = to_canonical(body)

    assert body == snapshot
    result["llm_setting"]["top_p"] = 0.9
    result["prompt_config"]["parameters"][0]["key"] = "changed"
    result["dataset_ids"].append("d2")
    assert body == snapshot


# Ciało z briefu T1 p. 5 — jeden obiekt dla obu profili (funkcja nie mutuje wejścia).
_V024_BODY: dict[str, Any] = {
    "name": "c",
    "avatar": "a.png",
    "llm": {"model_name": "m", "temperature": 0.5},
    "prompt": {
        "opener": "Hi",
        "prompt": "sys {knowledge}",
        "keywords_similarity_weight": 0.7,
        "top_n": 3,
        "rerank_model": "r",
    },
    "datasets": [{"id": "d1"}],
}


def test_create_profile_0_24_translates_body() -> None:
    """POST /chats w profilu 0.24 → ChatInput.fields po tłumaczeniu (brief T1 p. 5)."""
    inp = parse_chat_create(_V024_BODY, PROFILE_V024)
    assert inp.fields == {
        "name": "c",
        "icon": "a.png",
        "llm_id": "m",
        "llm_setting": {"temperature": 0.5},
        "prompt_config": {"system": "sys {knowledge}", "prologue": "Hi"},
        "vector_similarity_weight": 0.3,
        "top_n": 3,
        "rerank_id": "r",
        "dataset_ids": ["d1"],
    }


def test_create_profile_0_27_ignores_v024_keys() -> None:
    """Ten sam korpus w profilu 0.27: klucze v0.24 ignorowane (C1, brak regresji v027)."""
    inp = parse_chat_create(_V024_BODY, PROFILE_V027)
    assert inp.fields == {"name": "c"}


def test_update_profile_0_24_translates_body() -> None:
    """PUT/PATCH /chats/{id} w profilu 0.24 → ChatInput.fields po tłumaczeniu."""
    inp = parse_chat_update(
        {"avatar": "a.png", "llm": {"model_name": "m"}}, PROFILE_V024, patch=False
    )
    assert inp.fields == {"icon": "a.png", "llm_id": "m"}
