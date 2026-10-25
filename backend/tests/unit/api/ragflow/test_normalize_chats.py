"""Testy normalizacji czatów (CONTRACT C4) — przypadki z briefu T2c dosłownie."""

import pytest

from app.api.ragflow.normalize.chats import (
    parse_chat_create,
    parse_chat_list,
    parse_chat_update,
    parse_delete_ids,
    parse_recommendation,
)
from app.core.errors import Conflict, ValidationFailed
from app.services.chats import ChatInput

# Profil dziś nieużywany przez normalize (zarezerwowany dla E2-2).
PROFILE = "ragflow_0_27"
# Domyślny rozmiar strony parse_page (C5).
_DEFAULT_PAGE_SIZE = 30


def test_create_strips_name_and_keeps_dataset_ids() -> None:
    inp = parse_chat_create({"name": " a ", "dataset_ids": []}, PROFILE)
    assert inp == ChatInput(fields={"name": "a", "dataset_ids": []})


def test_create_rejects_tenant_id_before_name() -> None:
    with pytest.raises(Conflict) as exc:
        parse_chat_create({"name": "a", "tenant_id": "x"}, PROFILE)
    assert str(exc.value) == "`tenant_id` must not be provided"
    with pytest.raises(Conflict) as exc:
        parse_chat_create({"tenant_id": "x"}, PROFILE)
    assert str(exc.value) == "`tenant_id` must not be provided"


def test_create_name_required() -> None:
    for body in ({}, {"name": "  "}):
        with pytest.raises(Conflict) as exc:
            parse_chat_create(body, PROFILE)
        assert str(exc.value) == "`name` is required"
    with pytest.raises(Conflict) as exc:
        parse_chat_create({"name": 5}, PROFILE)
    assert str(exc.value) == "chat name must be a string"


def test_create_name_too_long() -> None:
    with pytest.raises(Conflict) as exc:
        parse_chat_create({"name": "ą" * 128}, PROFILE)
    assert str(exc.value) == "chat name length is 256 which is larger than 255"


def test_create_dataset_ids_must_be_list() -> None:
    with pytest.raises(Conflict) as exc:
        parse_chat_create({"name": "a", "dataset_ids": "x"}, PROFILE)
    assert str(exc.value) == "`dataset_ids` should be a list."
    inp = parse_chat_create({"name": "a", "dataset_ids": None}, PROFILE)
    assert inp.fields["dataset_ids"] == []


def test_create_objects_required() -> None:
    with pytest.raises(Conflict) as exc:
        parse_chat_create({"name": "a", "llm_setting": []}, PROFILE)
    assert str(exc.value) == "`llm_setting` should be an object."
    with pytest.raises(Conflict) as exc:
        parse_chat_create({"name": "a", "prompt_config": 1}, PROFILE)
    assert str(exc.value) == "`prompt_config` should be an object."


def test_create_prompt_parameters_duplicate_key() -> None:
    body = {"name": "a", "prompt_config": {"parameters": [{"key": "k"}, {"key": "k"}]}}
    with pytest.raises(Conflict) as exc:
        parse_chat_create(body, PROFILE)
    assert str(exc.value) == "`parameters` contains duplicate key: k"


def test_create_llm_id_must_be_string() -> None:
    with pytest.raises(Conflict) as exc:
        parse_chat_create({"name": "a", "llm_id": 5}, PROFILE)
    assert str(exc.value) == "`llm_id` must be a string"
    inp = parse_chat_create({"name": "a", "llm_id": None}, PROFILE)
    assert inp.fields["llm_id"] is None


def test_create_invalid_number_format() -> None:
    with pytest.raises(ValidationFailed) as exc:
        parse_chat_create({"name": "a", "top_n": "abc"}, PROFILE)
    assert str(exc.value).startswith("Field: <top_n>")


def test_create_ignores_v024_keys() -> None:
    inp = parse_chat_create({"name": "a", "llm": {"model_name": "x"}, "avatar": "b"}, PROFILE)
    assert inp.fields == {"name": "a"}


def test_update_patch_name_null_omitted() -> None:
    inp = parse_chat_update({"name": None}, PROFILE, patch=True)
    assert inp.fields == {}


def test_update_put_name_null_required() -> None:
    with pytest.raises(Conflict) as exc:
        parse_chat_update({"name": None}, PROFILE, patch=False)
    assert str(exc.value) == "`name` is required"


def test_update_patch_empty_name() -> None:
    with pytest.raises(Conflict) as exc:
        parse_chat_update({"name": ""}, PROFILE, patch=True)
    assert str(exc.value) == "`name` cannot be empty"


def test_update_put_without_name_is_fine() -> None:
    inp = parse_chat_update({"top_n": 3}, PROFILE, patch=False)
    assert inp.fields == {"top_n": 3}


def test_list_invalid_orderby() -> None:
    with pytest.raises(ValidationFailed) as exc:
        parse_chat_list({"orderby": "id"}, PROFILE, max_size=1000)
    assert str(exc.value) == "invalid orderby field: id"


def test_list_id_clears_keywords_and_defaults() -> None:
    q = parse_chat_list({"id": "c1", "keywords": "k"}, PROFILE, max_size=1000)
    assert q.chat_id == "c1"
    assert q.keywords == ""
    assert q.page == 1
    assert q.page_size == _DEFAULT_PAGE_SIZE
    assert q.orderby == "create_time"
    assert q.desc is True


def test_delete_ids() -> None:
    assert parse_delete_ids({"ids": ["a", 1]}) == (["a", "1"], False)
    assert parse_delete_ids({"delete_all": True}) == (None, True)
    assert parse_delete_ids({"delete_all": "true"}) == (None, False)


def test_recommendation_requires_question() -> None:
    """Ciało recommendation: question wymagane i typu str (api_utils.py:176)."""
    assert parse_recommendation({"question": "smok"}) == "smok"
    assert parse_recommendation({"question": ""}) == ""
    assert parse_recommendation({"question": "q", "industry": "search"}) == "q"
    for body in ({}, {"question": None}, {"question": 7}):
        with pytest.raises(ValidationFailed) as exc:
            parse_recommendation(body)
        assert str(exc.value) == "required argument are missing: question; "
