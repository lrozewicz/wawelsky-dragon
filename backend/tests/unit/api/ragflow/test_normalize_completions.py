"""Testy parse_completion (CONTRACT C4 p. 1-6) — przypadki z briefu T4 dosłownie.

Sekcja ``openai_request_error``: komunikaty dosłownie z ``openai_api.py:243-262`` v0.27.2
(port E2-3a2/T3, DEC-092 p. 2).
"""

import pytest

from app.api.ragflow.normalize.completions import openai_request_error, parse_completion
from app.core.errors import ValidationFailed

# Profil dziś nieużywany przez parse_completion (zarezerwowany dla E2-2).
PROFILE = "ragflow_0_27"


def parse(body: dict, path_chat_id: str | None = None):
    return parse_completion(body, PROFILE, path_chat_id=path_chat_id)  # type: ignore[arg-type]


def test_question_builds_single_user_message() -> None:
    call = parse({"question": "Q"}, "c1")
    assert call.req.chat_id == "c1"
    assert call.req.messages == ({"role": "user", "content": "Q"},)
    assert call.stream is True
    assert call.legacy is False
    assert call.req.quote is True
    assert call.req.store_history_messages is True
    assert call.req.llm_setting is None
    assert call.req.doc_ids is None
    assert call.req.session_id is None


def test_body_chat_id_wins_over_path() -> None:
    assert parse({"chat_id": "c2", "question": "Q"}, "c1").req.chat_id == "c2"


def test_messages_without_path_chat_id_gives_none() -> None:
    call = parse({"messages": [{"role": "user", "content": "Q"}]}, None)
    assert call.req.chat_id is None


def test_empty_body_missing_messages() -> None:
    with pytest.raises(ValidationFailed) as exc:
        parse({}, None)
    assert str(exc.value) == "required argument are missing: messages"


def test_messages_empty_list() -> None:
    with pytest.raises(ValidationFailed) as exc:
        parse({"messages": []}, None)
    assert str(exc.value) == "`messages` must be a non-empty list."


def test_messages_item_not_object() -> None:
    with pytest.raises(ValidationFailed) as exc:
        parse({"messages": ["x"]}, None)
    assert str(exc.value) == "Every item in `messages` must be an object."


def test_messages_item_missing_role_or_content() -> None:
    with pytest.raises(ValidationFailed) as exc:
        parse({"messages": [{"role": "user"}]}, None)
    assert str(exc.value) == "Every item in `messages` must include `role` and `content`."


def test_system_and_leading_assistant_skipped() -> None:
    call = parse(
        {
            "messages": [
                {"role": "system", "content": "s"},
                {"role": "assistant", "content": "a"},
                {"role": "user", "content": "Q"},
            ]
        },
        None,
    )
    assert call.req.messages == ({"role": "user", "content": "Q"},)


def test_only_system_message_rejected() -> None:
    with pytest.raises(ValidationFailed) as exc:
        parse({"messages": [{"role": "system", "content": "s"}]}, None)
    assert str(exc.value) == "`messages` must contain a user message."


def test_last_message_not_user_rejected() -> None:
    with pytest.raises(ValidationFailed) as exc:
        parse(
            {
                "messages": [
                    {"role": "user", "content": "Q"},
                    {"role": "assistant", "content": "a"},
                ]
            },
            None,
        )
    assert str(exc.value) == "The last message must be from user."


def test_stream_false_plain() -> None:
    assert parse({"question": "Q", "stream": False}, None).stream is False


def test_stream_string_false_is_stream() -> None:
    # R8: łańcuch "false" jest truthy — jak upstream `if stream_mode:`.
    assert parse({"question": "Q", "stream": "false"}, None).stream is True


def test_flags_aliases_and_strings() -> None:
    call = parse(
        {
            "question": "Q",
            "legacy": "yes",
            "quote": "0",
            "store_history": "false",
            "pass_all_history": 1,
        },
        None,
    )
    assert call.legacy is True
    assert call.req.quote is False
    assert call.req.store_history_messages is False
    assert call.req.pass_all_history_messages is True


def test_conversation_id_as_session() -> None:
    assert parse({"question": "Q", "conversation_id": "s1"}, None).req.session_id == "s1"


def test_session_id_wins_over_conversation_id() -> None:
    call = parse({"question": "Q", "session_id": "s2", "conversation_id": "s1"}, None)
    assert call.req.session_id == "s2"


def test_generation_config_enabled_flags() -> None:
    call = parse(
        {
            "question": "Q",
            "temperature": 0.2,
            "top_p": None,
            "max_tokens": 10,
            "maxTokensEnabled": False,
        },
        None,
    )
    assert call.req.llm_setting == {"temperature": 0.2}


def test_doc_ids_from_csv() -> None:
    assert parse({"question": "Q", "doc_ids": "d1,,d2"}, None).req.doc_ids == ("d1", "d2")


def test_doc_ids_from_list() -> None:
    assert parse({"question": "Q", "doc_ids": ["d1", ""]}, None).req.doc_ids == ("d1",)


def test_doc_ids_empty_string_none() -> None:
    assert parse({"question": "Q", "doc_ids": ""}, None).req.doc_ids is None


def test_metadata_condition_dict_kept() -> None:
    call = parse({"question": "Q", "metadata_condition": {"a": 1}}, None)
    assert call.req.metadata_condition == {"a": 1}


def test_metadata_condition_not_dict_none() -> None:
    call = parse({"question": "Q", "metadata_condition": "x"}, None)
    assert call.req.metadata_condition is None


def test_empty_llm_id_none() -> None:
    assert parse({"question": "Q", "llm_id": ""}, None).req.llm_id is None


_MESSAGES = [{"role": "user", "content": "hello"}]

# (ciało żądania, oczekiwany komunikat) — kolejność jak w `openai_api.py:243-262`.
_OPENAI_INVALID = [
    ({"extra_body": "invalid_extra_body"}, "extra_body must be an object."),
    (
        {"extra_body": {"reference_metadata": "invalid_reference_metadata"}},
        "reference_metadata must be an object.",
    ),
    (
        {"extra_body": {"reference_metadata": {"fields": "author"}}},
        "reference_metadata.fields must be an array.",
    ),
    ({"messages": []}, "You have to provide messages."),
    (
        {"messages": [{"role": "assistant", "content": "hello"}]},
        "The last content of this conversation is not from user.",
    ),
]


@pytest.mark.parametrize(("body", "message"), _OPENAI_INVALID)
def test_openai_request_error_messages(body: dict, message: str) -> None:
    assert openai_request_error(body) == message


@pytest.mark.parametrize(
    "body",
    [
        {"messages": _MESSAGES},
        # Prawdziwościowo, jak upstream: pusty/nieobecny `extra_body` nie jest błędem.
        {"messages": _MESSAGES, "extra_body": {}},
        {"messages": _MESSAGES, "extra_body": None},
        {"messages": _MESSAGES, "extra_body": {"reference": True}},
        {"messages": _MESSAGES, "extra_body": {"reference_metadata": {"fields": ["author"]}}},
    ],
)
def test_openai_request_error_none(body: dict) -> None:
    assert openai_request_error(body) is None
