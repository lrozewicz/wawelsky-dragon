"""Testy modeli T3 (brief E1-11 T3 p. 5): required ciał, klucze modeli, ramki SSE."""

import functools
import json
from collections.abc import Callable
from typing import Any

import pytest

from app.api.openapi_export import OPENAPI_PATH
from app.api.ragflow.normalize.chats import parse_chat_create, parse_chat_update, parse_delete_ids
from app.api.ragflow.normalize.completions import parse_completion
from app.api.ragflow.normalize.sessions import parse_session_create, parse_session_rename
from app.api.ragflow.present.chats import chat_detail, chat_list_item
from app.api.ragflow.schemas.auth import User
from app.api.ragflow.schemas.chats import Chat, ChatListItem
from app.api.ragflow.schemas.completions import CompletionData
from app.api.ragflow.sse import native_frames
from app.api.ragflow.user_view import user_safe_dict
from app.core.errors import WDError
from app.domain.chat.events import AnswerDelta, StreamIds, ThinkStart
from app.domain.chat.events import Final as FinalEvent
from app.services.chat_validation import ChatView
from app.services.users import UserRow

# Profil dziś nieużywany przez normalizatory czatów (zarezerwowany dla E2-2).
PROFILE = "ragflow_0_27"
TIME_MS = 1700000000000

_METHODS = ("get", "post", "put", "patch", "delete")


@functools.cache
def _spec() -> dict[str, Any]:
    """openapi.json wczytany leniwie, raz (obraz test-ocr nie ma pliku — krok binaries)."""
    loaded: dict[str, Any] = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    return loaded


def _operation(operation_id: str) -> dict[str, Any]:
    """Obiekt operacji z openapi.json o danym operationId; brak → KeyError."""
    for path_item in _spec()["paths"].values():
        for method in _METHODS:
            candidate: dict[str, Any] = path_item.get(method) or {}
            if candidate.get("operationId") == operation_id:
                return candidate
    raise KeyError(operation_id)


def _chats_create() -> object:
    return parse_chat_create({}, PROFILE)


def _chats_replace() -> object:
    return parse_chat_update({}, PROFILE, patch=False)


def _chats_update() -> object:
    return parse_chat_update({}, PROFILE, patch=True)


def _delete_ids() -> object:
    return parse_delete_ids({})


def _sessions_create() -> object:
    return parse_session_create({})


def _sessions_rename() -> object:
    return parse_session_rename({})


def _completions() -> object:
    return parse_completion({}, PROFILE, path_chat_id=None)


# (operationId, oczekiwane required, parser ciała; None = handler czyta json_body sam).
# Reguła briefu: required=True wtedy, gdy ciało {} nie może dać code 0. Handlery:
# auth_login/users_register — {} rzuca (code 109/403, 101); users_me_update/models_update
# — {} daje code 0.
_CASES: list[tuple[str, bool, Callable[[], object] | None]] = [
    ("auth_login", True, None),
    ("users_register", True, None),
    ("users_me_update", False, None),
    ("users_me_models_update", False, None),
    ("chats_create", True, _chats_create),
    ("chats_replace", False, _chats_replace),
    ("chats_update", False, _chats_update),
    ("chats_delete_many", False, _delete_ids),
    ("sessions_create", False, _sessions_create),
    ("sessions_delete", False, _delete_ids),
    ("sessions_rename", False, _sessions_rename),
    ("sessions_rename_legacy", False, _sessions_rename),
    ("chats_completions", True, _completions),
    ("chat_completions", True, _completions),
]


@pytest.mark.parametrize(
    ("operation_id", "expected", "parse_empty"), _CASES, ids=[case[0] for case in _CASES]
)
def test_request_body_required(
    operation_id: str, expected: bool, parse_empty: Callable[[], object] | None
) -> None:
    """required w openapi.json zgodne z zachowaniem parsera/ handlera na pustym ciele."""
    if parse_empty is not None:
        raised = False
        try:
            parse_empty()
        except WDError:
            raised = True
        assert raised is expected, operation_id
    operation = _operation(operation_id)
    assert operation["requestBody"]["required"] is expected, operation_id


def _chat_view() -> ChatView:
    """Widok czatu z wartościami reprezentatywnymi dla obu kształtów (wg test_present_chats)."""
    return ChatView(
        id="chat1",
        tenant_id="tenant1",
        name="Asystent",
        description="opis",
        icon="icon.png",
        language="Polish",
        llm_id="m0del1d",
        tenant_llm_id="m0del1d",
        llm_setting={"temperature": 0.1},
        prompt_type="simple",
        prompt_config={"system": ""},
        similarity_threshold=0.1,
        vector_similarity_weight=0.3,
        top_n=6,
        top_k=1024,
        rerank_candidates_count=64,
        rerank_id="rerank",
        tenant_rerank_id=None,
        do_refer="1",
        meta_data_filter={},
        status="1",
        dataset_ids=["d1"],
        kb_names=["kb1"],
        nickname="seed",
        tenant_avatar="a.png",
        create_time=TIME_MS,
        update_time=TIME_MS,
    )


def _user_row() -> UserRow:
    """Wiersz użytkownika: avatar None (nullable) i strefa str (obie gałęzie unii)."""
    return UserRow(
        id="u1",
        email="seed@wd.test",
        nickname="seed",
        password_hash="hash-wartość-testowa",  # noqa: S106 — próbka widoku, nie hasło
        auth_source="local",
        oidc_sub=None,
        is_superuser=True,
        is_active=True,
        is_service=False,
        language="Polish",
        timezone="Europe/Warsaw",
        avatar=None,
        last_login_time=None,
        token_version=1,
        create_time=TIME_MS,
        update_time=TIME_MS,
    )


def test_chat_model_keys_match_chat_detail() -> None:
    """Klucze Chat == klucze chat_detail, kolejność równa; przykładowy widok przechodzi."""
    detail = chat_detail(_chat_view(), PROFILE)
    assert list(Chat.model_fields) == list(detail)
    Chat.model_validate(detail, strict=True)


def test_chat_list_item_model_keys_match_presenter() -> None:
    """Klucze ChatListItem == klucze chat_list_item, kolejność równa."""
    item = chat_list_item(_chat_view(), PROFILE)
    assert list(ChatListItem.model_fields) == list(item)
    ChatListItem.model_validate(item, strict=True)


def test_user_model_keys_match_user_safe_dict() -> None:
    """Klucze User == klucze user_safe_dict, kolejność równa; is_active to str."""
    safe = user_safe_dict(_user_row())
    assert list(User.model_fields) == list(safe)
    User.model_validate(safe, strict=True)


_IDS = StreamIds(message_id="m1", session_id="s" * 32, chat_id="c" * 32)
_REFERENCE: dict[str, Any] = {
    "total": 1,
    "chunks": [
        {
            "id": "chunk1",
            "content": "smok wawelski",
            "document_id": "d1",
            "document_name": "wawel.txt",
            "dataset_id": "ds1",
            "image_id": "",
            "positions": [[0, 1, 2, 3]],
            "url": None,
            "similarity": 0.9,
            "vector_similarity": 0.8,
            "term_similarity": 0.7,
            "row_id": None,
            "doc_type": "",
            "document_metadata": None,
        }
    ],
    "doc_aggs": [{"doc_name": "wawel.txt", "doc_id": "d1", "count": 1}],
}


def test_completion_data_validates_native_frames() -> None:
    """Data każdej ramki native_frames (4 zdarzenia) waliduje CompletionData(strict)."""
    events: list[ThinkStart | AnswerDelta | FinalEvent] = [
        ThinkStart(),
        AnswerDelta(text="ala "),
        FinalEvent(
            answer="",
            reference=_REFERENCE,
            prompt="P",
            created_at=1.5,
            final_answer="ala",
            thinking=None,
            usage=(1, 1),
            empty=False,
        ),
        FinalEvent(
            answer="E",
            reference=_REFERENCE,
            prompt="P",
            created_at=None,
            final_answer="E",
            thinking=None,
            usage=(0, 0),
            empty=True,
        ),
    ]
    seen = 0
    for event in events:
        for frame in native_frames(event, _IDS):
            data = json.loads(frame[5:])["data"]
            CompletionData.model_validate(data, strict=True)
            seen += 1
    assert seen > 0
