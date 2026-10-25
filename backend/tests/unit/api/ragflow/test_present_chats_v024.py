"""Testy prezentera Chat v0.24 (CONTRACT C2) — klucze/wartości = złoto v0.24.0 (test czyta plik)."""

import json
from pathlib import Path
from typing import Any

import pytest

from app.api.ragflow.envelope import ok
from app.api.ragflow.present.chats import chat_detail, chat_list, chat_list_item
from app.api.ragflow.present.chats_v024 import (
    chat_detail_v024,
    chat_list_item_v024,
    chat_list_v024,
)
from app.api.ragflow.present.datasets import dataset
from app.db.repositories.datasets import DatasetRecord
from app.services.chats import ChatView

PROFILE_V024 = "ragflow_0_24"
PROFILE_V027 = "ragflow_0_27"
GOLDEN = Path(__file__).parents[3] / "contract" / "golden" / "v0.24.0" / "chats"
TIME_MS = 1700000000000
MODEL_ID = "m0del1d"
MODEL_NAME = "fake-chat___OpenAI-API@OpenAI-API-Compatible"


def _golden(name: str) -> Any:
    """``body.data`` pliku złota (szczegół obiektu albo lista elementów)."""
    return json.loads((GOLDEN / name).read_bytes())["body"]["data"]


def _view(data: dict[str, Any], **overrides: Any) -> ChatView:
    """``ChatView`` z wartościami złota — odwrotność mapowania C2 (wartości tokenów własne)."""
    llm = data["llm"]
    prompt = data["prompt"]
    values: dict[str, Any] = {
        "id": data["id"],
        "tenant_id": data["tenant_id"],
        "name": data["name"],
        "description": data["description"],
        "icon": data["avatar"],
        "language": data["language"],
        "llm_id": MODEL_ID,
        "tenant_llm_id": MODEL_ID,
        "llm_name": llm["model_name"],
        "llm_setting": {k: v for k, v in llm.items() if k != "model_name"},
        "prompt_type": data["prompt_type"],
        "prompt_config": {
            "system": prompt["prompt"],
            "prologue": prompt["opener"],
            "quote": prompt["show_quote"],
            "parameters": prompt["variables"],
            "empty_response": prompt["empty_response"],
            "tts": prompt["tts"],
            "refine_multiturn": prompt["refine_multiturn"],
        },
        "similarity_threshold": prompt["similarity_threshold"],
        "vector_similarity_weight": round(1 - prompt["keywords_similarity_weight"], 6),
        "top_n": prompt["top_n"],
        "top_k": data.get("top_k", 1024),
        "rerank_candidates_count": 0,
        "rerank_id": prompt["rerank_model"],
        "tenant_rerank_id": None,
        "do_refer": data["do_refer"],
        "meta_data_filter": data["meta_data_filter"],
        "status": data["status"],
        "dataset_ids": list(data.get("dataset_ids", [])),
        "kb_names": [],
        "nickname": "",
        "tenant_avatar": None,
        "create_time": TIME_MS,
        "update_time": TIME_MS,
    }
    values.update(overrides)
    return ChatView(**values)


def test_chat_detail_round_trip_keys_and_values() -> None:
    """Złoto --01: pełny round-trip (klucze na wszystkich poziomach + wartości nie-tokenowe)."""
    data = _golden("chat_session--01.json")
    d = chat_detail_v024(_view(data))

    assert sorted(d) == sorted(data)
    assert sorted(d["llm"]) == sorted(data["llm"])
    assert sorted(d["prompt"]) == sorted(data["prompt"])
    # Wartości: llm i prompt odtwarzają się 1:1 (llm_setting + model_name ↔ llm; prompt_config).
    assert d["llm"] == data["llm"]
    assert d["prompt"] == data["prompt"]
    tokens = {"create_date", "create_time", "update_date", "update_time"}
    for key in sorted(set(data) - {"llm", "prompt"} - tokens):
        assert d[key] == data[key]
    assert d["create_time"] == TIME_MS
    assert d["update_time"] == TIME_MS
    assert d["create_date"] == d["update_date"]
    assert isinstance(d["create_date"], str)


def test_chat_detail_drops_canonical_keys() -> None:
    """Tylko klucze v0.24: bez icon/llm_id/llm_setting/prompt_config/top_k/tenant_llm_id."""
    d = chat_detail_v024(_view(_golden("chat_session--01.json")))
    for key in ("icon", "llm_id", "llm_setting", "prompt_config", "top_k", "tenant_llm_id"):
        assert key not in d
    assert d["avatar"] == ""


def test_chat_list_item_round_trip_keys_and_values() -> None:
    """Złoto --02 data[0]: klucze + wartości; ``datasets`` puste, ``top_k`` obecne."""
    data = _golden("chat_session--02.json")[0]
    item = chat_list_item_v024(_view(data))

    assert sorted(item) == sorted(data)
    assert sorted(item["llm"]) == sorted(data["llm"])
    assert sorted(item["prompt"]) == sorted(data["prompt"])
    assert item["llm"] == data["llm"]
    assert item["prompt"] == data["prompt"]
    assert item["datasets"] == data["datasets"] == []
    assert item["top_k"] == data["top_k"]
    assert item["avatar"] == data["avatar"]
    assert item["create_time"] == TIME_MS


def test_chat_list_v024_returns_plain_list() -> None:
    """C2: ``chat_list`` w profilu 0.24 zwraca listę elementów; pusta lista → ``[]``."""
    item = chat_list_item_v024(_view(_golden("chat_session--02.json")[0]))
    assert chat_list_v024([]) == []
    assert chat_list_v024([_view(_golden("chat_session--02.json")[0])]) == [item]


def test_chat_list_envelope_profile_0_24_brief_example() -> None:
    """Brief T3, przykłady: ``ok(chat_list(...))`` → ``{"code":0,"data":[…]}` z listą."""
    item = chat_list_item_v024(_view(_golden("chat_session--02.json")[0]))
    response = ok(chat_list([_view(_golden("chat_session--02.json")[0])], 1, PROFILE_V024))
    assert json.loads(response.body) == {"code": 0, "message": "success", "data": [item]}


def test_chat_list_profile_0_27_unchanged() -> None:
    """C2: profil 0.27 bez zmian (koperta ``{"chats": [], "total": 0}``)."""
    assert chat_list([], 0, PROFILE_V027) == {"chats": [], "total": 0}


def test_dispatcher_profile_0_24_delegates() -> None:
    """C2: chat_detail/chat_list_item/chat_list w 0.24 delegują do ``_v024``."""
    detail_data = _golden("chat_session--01.json")
    item_data = _golden("chat_session--02.json")[0]
    assert chat_detail(_view(detail_data), PROFILE_V024) == chat_detail_v024(_view(detail_data))
    assert chat_list_item(_view(item_data), PROFILE_V024) == chat_list_item_v024(_view(item_data))
    assert chat_list([_view(item_data)], 1, PROFILE_V024) == chat_list_v024([_view(item_data)])


@pytest.mark.parametrize(
    ("vector_weight", "expected"), [(0.3, 0.7), (0.9, 0.1), (1.0, 0.0), (0.0, 1.0)]
)
def test_keywords_similarity_weight_is_inverted(vector_weight: float, expected: float) -> None:
    """C2: ``keywords_similarity_weight = round(1 - vector_similarity_weight, 6)`` dokładnie."""
    view = _view(_golden("chat_session--01.json"), vector_similarity_weight=vector_weight)
    assert chat_detail_v024(view)["prompt"]["keywords_similarity_weight"] == expected


def test_avatar_comes_from_icon() -> None:
    """Brief T3, przykłady: ``icon`` → ``avatar``; klucza ``icon`` nie ma w wyniku."""
    view = _view(_golden("chat_session--01.json"), icon="a.png")
    d = chat_detail_v024(view)
    assert d["avatar"] == "a.png"
    assert "icon" not in d


def test_prompt_missing_keys_use_golden_defaults() -> None:
    """C2: brak klucza w ``prompt_config`` → domyślne ze złota (``""``, ``False``, ``True``)."""
    data = _golden("chat_session--01.json")
    view = _view(data, prompt_config={"prologue": "Hi"})
    assert chat_detail_v024(view)["prompt"] == {
        "empty_response": "",
        "keywords_similarity_weight": 0.7,
        "opener": "Hi",
        "prompt": "",
        "refine_multiturn": True,
        "rerank_model": "",
        "show_quote": True,
        "similarity_threshold": 0.2,
        "top_n": 6,
        "tts": False,
        "variables": [],
    }


def test_llm_missing_setting_keys_use_v024_defaults() -> None:
    """C0 p. 2: ``llm`` ma 6 kluczy — brakujące dopełniają domyślne v0.24, ustawione wygrywa."""
    data = _golden("chat_session--01.json")
    view = _view(data, llm_setting={"temperature": 0.5}, llm_name=MODEL_NAME)
    assert chat_detail_v024(view)["llm"] == {
        "frequency_penalty": 0.7,
        "max_tokens": 512,
        "model_name": MODEL_NAME,
        "presence_penalty": 0.4,
        "temperature": 0.5,
        "top_p": 0.3,
    }


def test_llm_empty_setting_is_five_defaults() -> None:
    """C0 p. 2: pusty ``llm_setting`` → 5 domyślnych upstreamu v0.24 (``db_models.py:942``)."""
    data = _golden("chat_session--01.json")
    view = _view(data, llm_setting={}, llm_name=MODEL_NAME)
    assert chat_detail_v024(view)["llm"] == {
        "frequency_penalty": 0.7,
        "max_tokens": 512,
        "model_name": MODEL_NAME,
        "presence_penalty": 0.4,
        "temperature": 0.1,
        "top_p": 0.3,
    }


def test_llm_without_model_name() -> None:
    """C2: brak rozwiązanego modelu (``llm_name == ""``) → ``model_name`` pusty."""
    view = _view(_golden("chat_session--01.json"), llm_name="")
    assert chat_detail_v024(view)["llm"]["model_name"] == ""


def _record() -> DatasetRecord:
    """Rekord datasetu do prezentacji w liście (kształt C1.1)."""
    return DatasetRecord(
        id="s" * 32,
        tenant_id="t" * 32,
        created_by="u" * 32,
        name="ragflow_intro",
        description="opis",
        avatar=None,
        language="Polish",
        embedding_model="fake-embed",
        embedding_dim=1024,
        permission="me",
        chunk_method="naive",
        parser_config={},
        similarity_threshold=0.2,
        vector_similarity_weight=0.3,
        pagerank=0,
        document_count=1,
        chunk_count=2,
        token_num=10,
        status="1",
        create_time=TIME_MS,
        update_time=TIME_MS,
        owner_nickname="seed",
    )


def test_list_item_datasets_use_dataset_presenter() -> None:
    """C2/C0 p. 2: ``datasets`` listy = ``present.datasets.dataset(rec, …)`` dla każdego rekordu."""
    record = _record()
    view = _view(_golden("chat_session--02.json")[0], dataset_ids=[record.id], datasets=(record,))
    item = chat_list_item_v024(view)
    assert item["datasets"] == [dataset(record, PROFILE_V024)]
    assert item["datasets"][0]["id"] == record.id
    assert item["datasets"][0]["name"] == "ragflow_intro"
