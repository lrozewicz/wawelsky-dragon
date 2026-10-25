"""Wyrocznia K6 §5 p. 1-3 (kontrakt C4.1): openapi.json aktualny, opisany, spójny."""

import functools
import json
import warnings
from typing import Any

import pytest

from app.api.openapi_export import OPENAPI_PATH, STALE_MESSAGE, render

pytestmark = pytest.mark.contract

# Dolne ograniczenie liczby operacji (nie dokładny licznik): 57 wierszy tabeli C1
# + 11 operacji scenariusza system z E2-1 + 4 operacje ingestii/embeddingu datasetu
# z E2-1 DS2 + 2 trasy E2-1 DOC + 5 operacji metadanych z E2-1 DS3 + 4 operacje
# chat_extras z E2-1 CHAT + 6 tras plikowych z E2-1 DOC2 + 5 operacji openai_dify
# z E2-1 OD + 1 alias ``/chats_openai/…`` z E2-1 OC. Sprawdzane jako ``>=``, by test
# nie zależał od liczby tras dodawanych w kolejnych zadaniach (CONTRACT C6).
_MIN_OPERATIONS = 95

# OperationId operacji z ciałem JSON (wiersze z „J:" w C1 — 32 sztuki).
JSON_BODY_OPS: frozenset[str] = frozenset(
    {
        "auth_login",
        "chat_completions",
        "chat_recommendation",
        "chats_completions",
        "chats_create",
        "chats_delete_many",
        "chats_openai_chat_completions",
        "chats_replace",
        "chats_update",
        "chunks_create",
        "chunks_delete",
        "chunks_switch",
        "chunks_update",
        "chunks_update_legacy",
        "datasets_create",
        "datasets_delete",
        "datasets_embedding_check",
        "datasets_metadata_config_update",
        "datasets_metadata_update",
        "datasets_update",
        "dify_retrieval_post",
        "documents_delete",
        "documents_ingest",
        "documents_parse",
        "documents_parse_legacy",
        "documents_stop",
        "documents_stop_legacy",
        "documents_update",
        "documents_update_legacy",
        "openai_chat_completions",
        "retrieval_query",
        "retrieval_search",
        "retrieval_search_dataset",
        "sessions_create",
        "sessions_delete",
        "sessions_message_feedback",
        "sessions_related_questions",
        "sessions_rename",
        "sessions_rename_legacy",
        "users_me_models_update",
        "users_me_update",
        "users_register",
    }
)

REDIRECT_OPS: frozenset[str] = frozenset(
    {
        "auth_keycloak_callback",
        "auth_login_keycloak",
    }
)

# Operacje, których odpowiedź 200 to treść binarna, nie koperta JSON (K6 §4 p. 1);
# dokumentacja deklaruje application/octet-stream (format: binary).
BINARY_OPS: frozenset[str] = frozenset(
    {
        "documents_download",
        "documents_file_download",
        "documents_file_preview",
        "documents_image_get",
        # E4-5a T7 (DEC-179): pobranie pliku deklaruje octet-stream + kopertę błędu w JSON,
        # tak samo jak `documents_image_get` — rejestracja wyjątku treści K6 §4 p. 1.
        "files_download",
    }
)

# Operacje przyjmujące multipart/form-data (pole ``file``).
MULTIPART_OPS: frozenset[str] = frozenset({"documents_upload", "documents_upload_info"})

_METHODS = ("get", "post", "put", "patch", "delete")


@functools.cache
def _spec() -> dict[str, Any]:
    """openapi.json wczytany leniwie, raz (obraz test-ocr nie ma pliku — krok binaries)."""
    loaded: dict[str, Any] = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    return loaded


_ERR_REF = {"$ref": "#/components/schemas/RagflowError"}


def _operations() -> list[tuple[str, str, dict[str, Any]]]:
    """(ścieżka, metoda, operacja) dla wszystkich operacji pliku."""
    return [
        (path, method, path_item[method])
        for path, path_item in _spec()["paths"].items()
        for method in _METHODS
        if method in path_item
    ]


def test_openapi_json_is_current() -> None:
    assert render() == OPENAPI_PATH.read_text(encoding="utf-8"), STALE_MESSAGE


def test_generation_has_no_warnings() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        render()


def test_operation_ids_unique() -> None:
    ops = _operations()
    ids = [op["operationId"] for _, _, op in ops]
    assert len(ids) >= _MIN_OPERATIONS
    assert len(set(ids)) == len(ids)


def test_api_v1_operations_described() -> None:
    for path, method, op in _operations():
        assert op["operationId"], (path, method)
        assert op["tags"], (path, method)
        if not path.startswith("/api/v1"):
            continue
        responses = op["responses"]
        assert "422" not in responses, (path, method)
        assert responses["401"]["content"]["application/json"]["schema"] == _ERR_REF, (path, method)
        assert responses["default"]["content"]["application/json"]["schema"] == _ERR_REF, (
            path,
            method,
        )
        if op["operationId"] in REDIRECT_OPS:
            assert "302" in responses, (path, method)
            assert "200" not in responses, (path, method)
            continue
        content_200 = responses["200"]["content"]
        if op["operationId"] in BINARY_OPS:
            assert "application/octet-stream" in content_200, (path, method)
            continue
        if op["operationId"] == "system_ping":
            # Wyjątek treści K6 §4 p. 1: /system/ping bez koperty. Złoto v0.27.2
            # (system__ping/system--01.json) ma content-type "text/html; charset=utf-8"
            # (odpowiedź tekstowa Quarta), więc deklarujemy text/html.
            assert "text/html" in content_200, (path, method)
            continue
        assert content_200["application/json"]["schema"]["$ref"], (path, method)
        if op["operationId"] in {
            "chats_completions",
            "chat_completions",
            "openai_chat_completions",
            "chats_openai_chat_completions",
        }:
            assert "text/event-stream" in content_200, (path, method)
        if op["operationId"] in JSON_BODY_OPS:
            ref = op["requestBody"]["content"]["application/json"]["schema"]["$ref"]
            assert ref, (path, method)
        if op["operationId"] in MULTIPART_OPS:
            ref = op["requestBody"]["content"]["multipart/form-data"]["schema"]["$ref"]
            assert ref, (path, method)


def test_all_refs_resolve() -> None:
    schemas = set(_spec()["components"]["schemas"])

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "$ref":
                    assert value.rsplit("/", 1)[-1] in schemas, value
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(_spec())


def test_health_tags() -> None:
    live = _spec()["paths"]["/health/live"]["get"]
    ready = _spec()["paths"]["/health/ready"]["get"]
    assert live["tags"] == ["health"]
    assert live["operationId"] == "health_live"
    assert ready["tags"] == ["health"]
    assert ready["operationId"] == "health_ready"
