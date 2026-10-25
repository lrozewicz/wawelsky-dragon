"""Kontrakt K6 §5 dla tras WD ``/api/wd/v1``: dokument ``openapi.json`` opisuje każdą operację.

Test czyta wyłącznie commitowany dokument (``backend/openapi.json``) — bez uruchamiania aplikacji
i bez bazy, jak ``tests/contract/test_openapi_current.py``. Domknięcie WP E3-6a (T6) sprawdza:
DOKŁADNY zbiór ``operationId`` przestrzeni ``wd`` (14 integracji z E4-3b §4 + 17 admina
z E3-6a §2 + 2 zadań eksportu/importu z E7-1f §7 + 5 sesji importu z E7-1b §2 + 3 eksportu
z E7-1a §4 + 1 użycia datasetu z K20 §4 = 42 operacje), opis (``tags``), zakaz ``422``,
kopertę ``WdErrorResponse`` w ``400``/``401``/``403``, schemat treści przy sukcesie, kopertę
``Envelope_…`` w sukcesach list, brak sekretów (``token``/``password_hash``/``password``) w
``ApiKey``/``WdUser``/``AuditEntry`` przy ``token`` wyłącznie w ``ApiKeyCreated`` (kontrakt §3),
``ApiKey.expires_at`` (DEC-095) oraz ``UpdateMeRequest`` bez ``required``. Trasy
``/api/wd/v1/test/reset`` nie ma w dokumencie (§5).
"""

from __future__ import annotations

import functools
import json
from typing import Any

import pytest

from app.api.openapi_export import OPENAPI_PATH

pytestmark = pytest.mark.contract

WD_PREFIX = "/api/wd/v1"
WD_RESET_PATH = "/api/wd/v1/test/reset"
_METHODS = ("get", "post", "put", "patch", "delete")
_SUCCESS_CODES = ("200", "201", "202")
_AUTH_CODES = ("401", "403")
_FORBIDDEN_CODE = "422"
_NO_CONTENT = "204"
_WD_ERROR_REF = {"$ref": "#/components/schemas/WdErrorResponse"}

# Kontrakt E4-3b §4: 14 operacji integracji — 7 z ``crud.py`` i 7 z ``runs.py``.
WD_OPERATION_IDS = frozenset(
    {
        "integrations_list",
        "integrations_create",
        "integrations_test",
        "integrations_get",
        "integrations_update",
        "integrations_delete",
        "integrations_test_saved",
        "integrations_sync",
        "integrations_cancel",
        "integrations_status",
        "integrations_drives",
        "integrations_runs_list",
        "integration_run_events",
        "documents_source_link",
    }
)

# Kontrakt E3-6a §2: 17 operacji admina — users (11), access (4) i system (2).
WD_ADMIN_OPERATION_IDS = frozenset(
    {
        "users_list",
        "users_create",
        "users_get",
        "users_update",
        "users_delete",
        "users_set_password",
        "users_activate",
        "users_deactivate",
        "user_api_keys_list",
        "user_api_keys_create",
        "user_api_keys_delete",
        "access_assistants_list",
        "access_assistants_replace",
        "access_assistants_grant",
        "access_assistants_revoke",
        "stats_get",
        "audit_list",
    }
)

# Kontrakt E7-1f §7: trasy zadań eksportu/importu (K19 §3 trasy 3-4).
WD_TASK_OPERATION_IDS = frozenset({"wd_task_get", "wd_task_stop"})

# Kontrakt E7-1b §2: trasy sesji importu (K19 §3 trasy 6-10); trasę 9 ``start`` dokłada T6.
WD_IMPORT_OPERATION_IDS = frozenset(
    {
        "dataset_import_create",
        "dataset_import_upload",
        "dataset_import_get",
        "dataset_import_start",
        "dataset_import_delete",
    }
)

# Kontrakt E7-1a §4: trasy eksportu (K19 §3 trasy 1, 2 i 5).
WD_EXPORT_OPERATION_IDS = frozenset(
    {"dataset_export_preview", "dataset_export", "dataset_export_download"}
)

# Kontrakt K20 §4: 1 operacja użycia datasetu przed usunięciem.
WD_USAGE_OPERATION_IDS = frozenset({"dataset_usage"})

# Kontrakt §2: 14 + 17 = 31 operacji przestrzeni ``wd``; E7-1f §7 dokłada 2 trasy zadań WD,
# E7-1b §2 — 5 tras sesji importu, E7-1a §4 — 3 trasy eksportu, K20 §4 — 1 trasę użycia.
WD_INTEGRATION_OPERATION_COUNT = 14
WD_ADMIN_OPERATION_COUNT = 17
WD_TASK_OPERATION_COUNT = 2
WD_IMPORT_OPERATION_COUNT = 5
WD_EXPORT_OPERATION_COUNT = 3
WD_USAGE_OPERATION_COUNT = 1
WD_OPERATION_COUNT = 42

# Kontrakt E3-6a §2: trasy list — sukces w kopercie ``Envelope[Page|Items[T]]``.
WD_LIST_OPERATION_IDS = frozenset(
    {"users_list", "user_api_keys_list", "access_assistants_list", "audit_list"}
)

# K19 §3 trasa 5 (E7-1a §4): pobranie jest binarne (``application/zip``) i BEZ aktora — brak
# sesji nie daje 401 (autoryzuje podpis HMAC), a 200 to plik, nie koperta JSON. Wyjątek od
# reguł koperty WD, jak ``BINARY_OPS`` w ``test_openapi_current.py``.
WD_BINARY_OPERATION_IDS = frozenset({"dataset_export_download"})

# Kontrakt E3-6a §3: komponenty bez pól sekretów i pola, których nie wolno im ujawniać.
WD_PUBLIC_COMPONENTS = ("ApiKey", "WdUser", "AuditEntry")
FORBIDDEN_SECRET_PROPERTIES = ("token", "password_hash", "password")  # nazwy pól schematów

_SECRET_KEY = "client_secret"  # noqa: S105 — nazwa pola schematu, nie wartość sekretu


@functools.cache
def _spec() -> dict[str, Any]:
    """Dokument OpenAPI wczytany leniwie, raz (wzorzec ``test_openapi_current.py``)."""
    loaded: dict[str, Any] = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    return loaded


def _operations() -> list[tuple[str, str, dict[str, Any]]]:
    """``(ścieżka, metoda, operacja)`` dla wszystkich operacji dokumentu."""
    return [
        (path, method, path_item[method])
        for path, path_item in _spec()["paths"].items()
        for method in _METHODS
        if method in path_item
    ]


def _wd_operations() -> list[tuple[str, str, dict[str, Any]]]:
    """Operacje przestrzeni ``wd`` (ścieżki z prefiksem ``/api/wd/v1``)."""
    return [item for item in _operations() if item[0].startswith(WD_PREFIX)]


def _wd_operation(operation_id: str) -> tuple[str, str, dict[str, Any]]:
    """Operacja WD o danym ``operationId``; brak w dokumencie to błąd testu."""
    for item in _wd_operations():
        if item[2]["operationId"] == operation_id:
            return item
    raise AssertionError(f"brak operacji {operation_id} w dokumencie")


def _ref(node: dict[str, Any]) -> str | None:
    """``$ref`` schematu albo ``None``."""
    value = node.get("$ref")
    return value if isinstance(value, str) else None


def _json_schema(node: dict[str, Any]) -> dict[str, Any]:
    """Schemat treści ``application/json`` odpowiedzi/żądania (albo pusty słownik)."""
    schema = node.get("content", {}).get("application/json", {}).get("schema", {})
    return schema if isinstance(schema, dict) else {}


def _body_schema_refs(operation: dict[str, Any], key: str) -> set[str]:
    """Nazwy komponentów wskazywanych przez treść ``key`` (``requestBody``/``responses``)."""
    if key == "requestBody":
        ref = _ref(_json_schema(operation.get(key, {})))
        return {ref} if ref else set()
    refs: set[str] = set()
    for response in operation.get(key, {}).values():
        ref = _ref(_json_schema(response))
        if ref:
            refs.add(ref)
    return refs


def _refs(node: Any) -> list[str]:
    """Wszystkie ``$ref`` w (pod)drzewie schematu."""
    if isinstance(node, dict):
        found: list[str] = []
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                found.append(value)
            else:
                found.extend(_refs(value))
        return found
    if isinstance(node, list):
        return [ref for item in node for ref in _refs(item)]
    return []


def _closure(refs: set[str]) -> list[tuple[str, dict[str, Any]]]:
    """Komponenty wskazane przez ``refs`` wraz z domknięciem po ``$ref`` (bez duplikatów)."""
    schemas: dict[str, dict[str, Any]] = _spec()["components"]["schemas"]
    seen: set[str] = set()
    nodes: list[tuple[str, dict[str, Any]]] = []
    stack = list(refs)
    while stack:
        name = stack.pop().rsplit("/", 1)[-1]
        if name in seen:
            continue
        seen.add(name)
        node = schemas.get(name)
        if node is None:
            continue
        nodes.append((name, node))
        stack.extend(_refs(node))
    return nodes


def _wd_component_names(key: str) -> set[str]:
    """Nazwy komponentów użytych w ``key`` którejkolwiek operacji WD."""
    refs: set[str] = set()
    for _, _, operation in _wd_operations():
        refs |= _body_schema_refs(operation, key)
    return refs


def test_wd_operations_match_the_contract_set() -> None:
    """``operationId`` pod ``/api/wd/v1`` == integracje + admin + zadania + import + eksport.

    Zbiór domknięty: żadna operacja spoza kontraktu i żadna z kontraktu nie może brakować;
    licznik pilnuje, by suma zbiorów się nie rozjechała.
    """
    ids = {operation["operationId"] for _, _, operation in _wd_operations()}

    assert len(WD_OPERATION_IDS) == WD_INTEGRATION_OPERATION_COUNT
    assert len(WD_ADMIN_OPERATION_IDS) == WD_ADMIN_OPERATION_COUNT
    assert len(WD_TASK_OPERATION_IDS) == WD_TASK_OPERATION_COUNT
    assert len(WD_IMPORT_OPERATION_IDS) == WD_IMPORT_OPERATION_COUNT
    assert len(WD_EXPORT_OPERATION_IDS) == WD_EXPORT_OPERATION_COUNT
    assert len(WD_USAGE_OPERATION_IDS) == WD_USAGE_OPERATION_COUNT
    expected = (
        WD_OPERATION_IDS
        | WD_ADMIN_OPERATION_IDS
        | WD_TASK_OPERATION_IDS
        | WD_IMPORT_OPERATION_IDS
        | WD_EXPORT_OPERATION_IDS
        | WD_USAGE_OPERATION_IDS
    )
    assert ids == expected
    assert len(ids) == WD_OPERATION_COUNT


def test_operation_ids_are_unique_in_the_whole_document() -> None:
    """Każda operacja ma ``operationId``, a identyfikatory są unikalne w całym pliku."""
    ids = [operation["operationId"] for _, _, operation in _operations()]

    assert all(ids)
    assert len(set(ids)) == len(ids)


def test_wd_operations_are_described_with_the_wd_error_envelope() -> None:
    """Każda operacja WD: ``tags``, brak ``422``, ``400``/``401``/``403`` = ``WdErrorResponse``.

    Kontrakt §0 p. 12: ``400``, ``401`` i ``403`` deklaruje każda trasa (``400`` jako
    ``validation_failed`` na trasie z parametrami albo ciałem — ``stats_get`` ich nie ma).
    """
    for path, method, operation in _wd_operations():
        assert operation["tags"], (path, method)
        responses = operation["responses"]
        assert _FORBIDDEN_CODE not in responses, (path, method)
        if operation["operationId"] in WD_BINARY_OPERATION_IDS:
            # Trasa bez aktora (K19 §3 trasa 5): autoryzuje podpis HMAC, więc nie deklaruje
            # 401 ani 400; wyjątek jak ``BINARY_OPS`` w ``test_openapi_current.py``.
            assert _json_schema(responses["403"]) == _WD_ERROR_REF, (path, method)
            continue
        for code in _AUTH_CODES:
            assert _json_schema(responses[code]) == _WD_ERROR_REF, (path, method, code)
        if operation.get("parameters") or operation.get("requestBody"):
            assert _json_schema(responses.get("400", {})) == _WD_ERROR_REF, (path, method)


def test_wd_success_responses_declare_a_json_schema() -> None:
    """Sukces (``200``/``201``/``202``) ma schemat ``$ref``; ``204`` nie ma treści (kontrakt §4)."""
    for path, method, operation in _wd_operations():
        if operation["operationId"] in WD_BINARY_OPERATION_IDS:
            continue  # 200 to strumień pliku (``application/zip``), nie koperta JSON
        responses = operation["responses"]
        if _NO_CONTENT in responses:
            assert "content" not in responses[_NO_CONTENT], (path, method)
        successes = [code for code in _SUCCESS_CODES if code in responses]
        if not successes:
            assert _NO_CONTENT in responses, (path, method)
        for code in successes:
            assert _ref(_json_schema(responses[code])), (path, method, code)


def test_wd_reset_route_is_not_documented() -> None:
    """``/api/wd/v1/test/reset`` montowane tylko w ``env=test`` — nie ma go w eksporcie (§5)."""
    assert WD_RESET_PATH not in _spec()["paths"]


def test_wd_response_schemas_never_expose_the_secret() -> None:
    """Żaden schemat odpowiedzi WD nie ma właściwości ``client_secret`` (kontrakt §0 p. 7)."""
    names = _wd_component_names("responses")

    assert names
    offenders = [
        name for name, node in _closure(names) if _SECRET_KEY in node.get("properties", {})
    ]
    assert offenders == []


def test_wd_request_schemas_do_carry_the_secret() -> None:
    """Kontrola niepustości zakazu: żądania WD mają pole ``client_secret`` (kontrakt §0 p. 7)."""
    names = _wd_component_names("requestBody")

    assert names
    carriers = [name for name, node in _closure(names) if _SECRET_KEY in node.get("properties", {})]
    assert carriers


def test_wd_list_successes_use_the_envelope() -> None:
    """Sukces ``200`` tras list to koperta ``Envelope_…`` (kontrakt §0 p. 1 i §3)."""
    for operation_id in WD_LIST_OPERATION_IDS:
        path, method, operation = _wd_operation(operation_id)
        ref = _ref(_json_schema(operation["responses"]["200"]))
        assert ref is not None, (path, method)
        assert ref.rsplit("/", 1)[-1].startswith("Envelope_"), (path, method, ref)


def test_admin_response_schemas_never_expose_credentials() -> None:
    """``ApiKey``, ``WdUser`` i ``AuditEntry`` nie mają pól sekretów (kontrakt §3)."""
    schemas = _spec()["components"]["schemas"]
    for name in WD_PUBLIC_COMPONENTS:
        properties = set(schemas[name].get("properties", {}))
        leaked = properties.intersection(FORBIDDEN_SECRET_PROPERTIES)
        assert leaked == set(), (name, leaked)


def test_api_key_created_schema_carries_the_token() -> None:
    """Pełny token jest wyłącznie w ``ApiKeyCreated`` — odpowiedź ``POST`` (kontrakt §3)."""
    properties = _spec()["components"]["schemas"]["ApiKeyCreated"]["properties"]

    assert "token" in properties


def test_api_key_schema_declares_expiry() -> None:
    """``ApiKey.expires_at`` istnieje (DEC-095; kontrakt §3) — w odpowiedziach zawsze ``null``."""
    properties = _spec()["components"]["schemas"]["ApiKey"]["properties"]

    assert "expires_at" in properties


def test_update_me_request_has_no_required_fields() -> None:
    """``UpdateMeRequest`` bez ``required`` — pola opcjonalne też w ``schema.gen.ts`` (T5)."""
    node = _spec()["components"]["schemas"]["UpdateMeRequest"]

    assert node.get("required", []) == []


def _operation(operation_id: str) -> dict[str, Any]:
    """Operacja dokumentu o danym ``operationId`` (dowolna przestrzeń); brak → błąd testu."""
    for _, _, operation in _operations():
        if operation["operationId"] == operation_id:
            return operation
    raise AssertionError(f"brak operacji {operation_id} w dokumencie")


def test_documents_list_declares_metadata_condition_query() -> None:
    """``documents_list`` (T6 E7-H1): opcjonalny ``metadata_condition`` w specyfikacji.

    Kontrakt E6-1b §2: filtr metadanych jedzie jako JSON w ``?metadata_condition=``. Brak tej
    deklaracji w OpenAPI zmuszał front do rzutowania ``as never`` (usunięte w T6).
    """
    operation = _operation("documents_list")
    params = {p["name"]: p for p in operation.get("parameters", []) if p.get("in") == "query"}

    assert "metadata_condition" in params
    param = params["metadata_condition"]
    assert param["required"] is False
    assert param["schema"]["type"] == "string"
