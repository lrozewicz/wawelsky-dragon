"""Testy prezenterą odmowy per trasa (K11 §10c p. 9, kontrakt E2-1 C2)."""

import json

import pytest
from starlette.requests import Request

from app.api.ragflow.refusals import PROFILES, refuse
from app.core.errors import NotFound, PermissionDenied
from app.domain.policy import Principal

_OK = 200
_USER_ID = "u" * 32
_DATASET_ID = "d" * 32
_CHAT_ID = "5" * 32

_PRINCIPAL = Principal(
    _USER_ID, "bob@x.pl", is_superuser=False, is_service=False, auth_kind="api_key"
)


def _request(path_params: dict[str, str] | None = None) -> Request:
    """Żądanie z ustawionymi parametrami ścieżki (bez I/O; prezentacja jest czysta)."""
    scope = {"type": "http", "path": "/api/v1/datasets", "path_params": path_params or {}}
    return Request(scope)


def _payload(response: object) -> dict[str, object]:
    return json.loads(bytes(response.body))  # type: ignore[attr-defined]


def test_profiles_are_within_golden_codes() -> None:
    """Kody profili to wyłącznie 102 albo 109 (K3 §1: DATA_ERROR, AUTHENTICATION_ERROR)."""
    assert {profile.code for profile in PROFILES.values()} == {102, 109}


def test_envelope_has_no_data_key() -> None:
    """Koperta odmowy nie ma ``data`` (w złocie jest tylko przy HTTP 401)."""
    response = refuse(
        _request({"dataset_id": _DATASET_ID}),
        _PRINCIPAL,
        "documents_list",
        PermissionDenied("You don't own the dataset x."),
        compat="ragflow_0_27",
    )
    assert response.status_code == _OK
    assert _payload(response) == {
        "code": 102,
        "message": f"You don't own the dataset {_DATASET_ID}. ",
    }


@pytest.mark.parametrize("route", ["datasets_get", "datasets_update"])
def test_lacks_permission_message(route: str) -> None:
    """Trasy datasetu: komunikat „lacks permission" z id użytkownika i datasetu (--10/--11)."""
    response = refuse(
        _request({"dataset_id": _DATASET_ID}),
        _PRINCIPAL,
        route,
        PermissionDenied("You don't own the dataset x."),
        compat="ragflow_0_27",
    )
    assert _payload(response) == {
        "code": 102,
        "message": f"User '{_USER_ID}' lacks permission for dataset '{_DATASET_ID}'",
    }


def test_datasets_delete_message_uses_body_ids() -> None:
    """DELETE /datasets: komunikat „lacks permission for datasets" z ids z ciała (złoto --53)."""
    response = refuse(
        _request(),
        _PRINCIPAL,
        "datasets_delete",
        PermissionDenied("You don't own the dataset x."),
        ids=[_DATASET_ID, "e" * 32],
        compat="ragflow_0_27",
    )
    assert _payload(response) == {
        "code": 102,
        "message": f"User '{_USER_ID}' lacks permission for datasets: '{_DATASET_ID}, {'e' * 32}'",
    }


def test_documents_download_message_hides_existence() -> None:
    """Pobranie cudzego dokumentu: „document not found" także dla istniejącego wiersza (--15)."""
    response = refuse(
        _request({"dataset_id": _DATASET_ID, "document_id": "c" * 32}),
        _PRINCIPAL,
        "documents_download",
        PermissionDenied("You don't own the dataset x."),
        compat="ragflow_0_27",
    )
    assert _payload(response) == {"code": 102, "message": "document not found"}


def test_upload_refusal_is_109() -> None:
    """Upload do cudzego datasetu: 109 „no authorization" (złoto --13)."""
    response = refuse(
        _request({"dataset_id": _DATASET_ID}),
        _PRINCIPAL,
        "documents_upload",
        PermissionDenied("You don't own the dataset x."),
        compat="ragflow_0_27",
    )
    assert _payload(response) == {"code": 109, "message": "no authorization"}


@pytest.mark.parametrize(
    ("route", "message"),
    [
        ("documents_parse", "You don't own the dataset x."),
        ("documents_stop", "You don't own the dataset x."),
        ("chunks_list", "you don't own the document x"),
        ("chunks_create", "You don't own the dataset x."),
        ("chunks_delete", "You don't own the dataset x."),
        ("datasets_list", "User 'x' lacks permission for dataset 'y'"),
        ("retrieval_query", "You don't own the dataset x."),
    ],
)
def test_message_of_exception_is_kept(route: str, message: str) -> None:
    """Trasy bez własnego szablonu zachowują komunikat wyjątku (już zgodny ze złotem)."""
    response = refuse(
        _request({"dataset_id": _DATASET_ID}),
        _PRINCIPAL,
        route,
        NotFound(message),
        compat="ragflow_0_27",
    )
    assert _payload(response) == {"code": 102, "message": message}


def test_unknown_route_raises_permission_denied() -> None:
    """Trasa bez profilu w danym profilu zgodności → 108 ``PermissionDenied`` (fallback C1)."""
    with pytest.raises(PermissionDenied):
        refuse(_request(), _PRINCIPAL, "chats_delete", NotFound("x"), compat="ragflow_0_27")


def test_profile_without_template_requires_exception() -> None:
    """Profil bez szablonu bierze komunikat z wyjątku — wołanie bez niego to błąd użycia."""
    with pytest.raises(RuntimeError, match="wymaga wyjątku"):
        refuse(_request(), _PRINCIPAL, "chats_delete_many", compat="ragflow_0_27")


# Trasy czatu i sesji, których odmowa to 109 ``no authorization`` z ``data: false``
# (upstream ``_ensure_owned_chat`` / ``openai_api``-owe ``get_json_result``).
_CHAT_REFUSAL_ROUTES = (
    "chats_get",
    "chats_update",
    "chats_completions",
    "chat_completions",
    "sessions_create",
    "sessions_list",
    "sessions_get",
    "sessions_rename",
    "sessions_delete",
)


@pytest.mark.parametrize("route", _CHAT_REFUSAL_ROUTES)
def test_chat_refusals_are_109_with_data_false(route: str) -> None:
    """Cudzy (albo nieistniejący) czat → 109 ``no authorization`` + ``data: false``.

    Złoto v0.27.2: czat i sesja ``errors_access--{25,26,27,28,29,30,31,33,34,45,46,51}.json``.
    """
    response = refuse(
        _request({"chat_id": _CHAT_ID}),
        _PRINCIPAL,
        route,
        PermissionDenied("You don't own the chat x"),
        compat="ragflow_0_27",
    )
    assert _payload(response) == {"code": 109, "message": "no authorization", "data": False}


def test_chats_delete_many_message_is_kept_without_data() -> None:
    """Opis usunięcia (rzucany przez usługę) trafia do koperty, ale bez klucza ``data``.

    Złoto ``chats/errors_access--52.json``: ``Chat(<id>) not found.`` przy 0 usunięciach.
    """
    response = refuse(
        _request(),
        _PRINCIPAL,
        "chats_delete_many",
        NotFound(f"Chat({_CHAT_ID}) not found."),
        compat="ragflow_0_27",
    )
    assert _payload(response) == {"code": 102, "message": f"Chat({_CHAT_ID}) not found."}
