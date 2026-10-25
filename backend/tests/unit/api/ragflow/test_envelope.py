"""Testy koperty odpowiedzi ragflow (C2, przykłady briefu dosłownie)."""

import json

from app.api.ragflow.envelope import argument_error, ok, ok_result, ok_true

_OK = 200


def test_ok_none_includes_null_data() -> None:
    """ok(None) — pole data zawsze obecne, także jako null; HTTP 200."""
    response = ok(None)
    assert response.status_code == _OK
    assert json.loads(response.body) == {"code": 0, "message": "success", "data": None}


def test_ok_result_none_has_only_code_and_message() -> None:
    """ok_result(None) — bez pól data i total_datasets."""
    assert json.loads(ok_result(None).body) == {"code": 0, "message": "success"}


def test_ok_result_data_and_total_key_order() -> None:
    """ok_result([1], total=5) — kolejność kluczy: code, message, data, total_datasets."""
    body = json.loads(ok_result([1], total=5).body)
    assert body == {"code": 0, "message": "success", "data": [1], "total_datasets": 5}
    assert list(body.keys()) == ["code", "message", "data", "total_datasets"]


def test_ok_result_total_without_data_omits_data() -> None:
    """total bez data — pole data pominięte, total_datasets obecne."""
    body = json.loads(ok_result(total=2).body)
    assert body == {"code": 0, "message": "success", "total_datasets": 2}
    assert list(body.keys()) == ["code", "message", "total_datasets"]


def test_ok_true_returns_boolean_true() -> None:
    """ok_true() — data jako JSON true."""
    assert json.loads(ok_true().body) == {"code": 0, "message": "success", "data": True}


def test_argument_error_has_no_data_key() -> None:
    """argument_error() — HTTP 200, code 101, bez klucza data (``get_error_data_result``)."""
    response = argument_error("`llm_id` no-such-model doesn't exist")
    assert response.status_code == _OK
    assert json.loads(response.body) == {
        "code": 101,
        "message": "`llm_id` no-such-model doesn't exist",
    }
