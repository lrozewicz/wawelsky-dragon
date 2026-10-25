"""Testy normalizacji sesji (CONTRACT C4) — przypadki z briefu T3b dosłownie."""

import pytest

from app.api.ragflow.normalize.sessions import (
    parse_message_feedback,
    parse_session_create,
    parse_session_list,
    parse_session_rename,
)
from app.core.error_codes import RetCode
from app.core.errors import Conflict, ValidationFailed
from app.services.sessions import SessionListQuery

# Limit długości nazwy sesji (upstream: strip()[:255]).
_NAME_MAX = 255


def test_create_default_and_stripped_name() -> None:
    assert parse_session_create({}) == "New session"
    assert parse_session_create({"name": "  a "}) == "a"
    assert parse_session_create({"name": "x" * 300}) == "x" * _NAME_MAX


def test_create_empty_or_non_string_name() -> None:
    for body in ({"name": ""}, {"name": 5}, {"name": None}):
        with pytest.raises(Conflict) as exc:
            parse_session_create(body)
        assert str(exc.value) == "`name` can not be empty"


def test_rename_rejects_message_and_reference_keys() -> None:
    with pytest.raises(Conflict) as exc:
        parse_session_rename({"messages": []})
    assert str(exc.value) == "`messages` cannot be changed"
    with pytest.raises(Conflict) as exc:
        parse_session_rename({"message": 1})
    assert str(exc.value) == "`messages` cannot be changed"
    with pytest.raises(Conflict) as exc:
        parse_session_rename({"reference": {}})
    assert str(exc.value) == "`reference` cannot be changed"


def test_rename_name_rules() -> None:
    assert parse_session_rename({}) is None
    assert parse_session_rename({"name": None}) is None
    with pytest.raises(Conflict) as exc:
        parse_session_rename({"name": " "})
    assert str(exc.value) == "`name` can not be empty"
    assert parse_session_rename({"name": "b"}) == "b"
    assert parse_session_rename({"name": "b"}) == "b"
    assert parse_session_rename({"name": " nowa nazwa "}) == "nowa nazwa"
    assert parse_session_rename({"name": "q" * 300}) == "q" * _NAME_MAX


def test_list_zero_page_size_allowed() -> None:
    query = parse_session_list({"page_size": "0"}, "ragflow_0_27", max_size=1000)
    assert query.page_size == 0


def test_list_invalid_orderby() -> None:
    with pytest.raises(ValidationFailed) as exc:
        parse_session_list({"orderby": "x"}, "ragflow_0_27", max_size=1000)
    assert str(exc.value) == "invalid orderby field: x"


def test_list_filters_set_from_query() -> None:
    query = parse_session_list(
        {"id": "s", "name": "n", "user_id": "u"}, "ragflow_0_27", max_size=1000
    )
    assert query == SessionListQuery(
        page=1,
        page_size=30,
        orderby="create_time",
        desc=True,
        session_id="s",
        name="n",
        user_id="u",
    )


def test_list_empty_filters_are_none() -> None:
    query = parse_session_list({}, "ragflow_0_27", max_size=1000)
    assert query.session_id is None
    assert query.name is None
    assert query.user_id is None
    assert query.page == 1
    assert query.orderby == "create_time"


def test_list_default_orderby_depends_on_profile() -> None:
    """A4: konto serwisowe 0.24 domyślnie ``update_time DESC``; 0.27 bez zmian."""
    v024 = parse_session_list({}, "ragflow_0_24", max_size=1000)
    assert (v024.orderby, v024.desc) == ("update_time", True)
    assert parse_session_list({}, "ragflow_0_27", max_size=1000).orderby == "create_time"


def test_list_explicit_orderby_beats_profile_default() -> None:
    """A4: jawne ``orderby``/``desc`` z zapytania wygrywa z domyślnym profilem 0.24."""
    query = parse_session_list(
        {"orderby": "create_time", "desc": "false"}, "ragflow_0_24", max_size=1000
    )
    assert (query.orderby, query.desc) == ("create_time", False)


def test_message_feedback_requires_bool_thumbup() -> None:
    """chat_api.py:1036-1038: thumbup musi być bool → ``get_data_error_result`` (102)."""
    assert parse_message_feedback({"thumbup": True}) == (True, None)
    assert parse_message_feedback({"thumbup": False, "feedback": "nie tak"}) == (False, "nie tak")
    assert parse_message_feedback({"thumbup": True, "feedback": 7}) == (True, None)
    for body in ({}, {"thumbup": 1}, {"thumbup": 0}, {"thumbup": "true"}, {"thumbup": None}):
        with pytest.raises(Conflict) as exc:
            parse_message_feedback(body)
        assert str(exc.value) == "thumbup must be a boolean"
        assert exc.value.code == RetCode.DATA_ERROR
