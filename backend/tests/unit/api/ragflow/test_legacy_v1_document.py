"""Testy tras legacy ``/v1/document/*`` (E2-2a T4) — kształty i odmowy.

Kształt ``data`` uploadu bierzemy DOSŁOWNIE z pliku złota v0.24.0 scenariusza
``documents_extras`` (krok 26): test czyta klucze prezentera i porównuje je z ``body.data``,
tak jak ``test_legacy_v1_system.py``. Trasy ``/v1/document/*`` nie mają w złocie plików odmowy
(upstream ``document_app.py`` zwraca „No authorization." tylko dla ``run`` i ``change_status``,
a ``get``/``thumbnails`` nie sprawdzają właściciela wcale), więc odmowę sprawdzamy na wpisach
``PROFILES_V024`` i kopercie budowanej przez ``refuse`` (CONTRACT C0 p. 5 i p. 9).
"""

import json
import sys
from pathlib import Path
from typing import Any, cast

from starlette.requests import Request

from app.api.ragflow.present.documents_files import uploaded_file
from app.api.ragflow.refusals import refuse
from app.api.ragflow.refusals_v024 import PROFILES_V024
from app.domain.policy import Principal
from app.services.documents_files import UploadedFile

GOLDEN = Path(__file__).resolve().parents[3] / "contract" / "golden" / "v0.24.0"

LACK_PERMISSION = 108
HTTP_OK = 200
USER_ID = "1" * 32
DOCUMENT_ID = "d" * 32
CREATED_AT = 1_730_000_000.0
# Fixture ``fixtures/ragflow_intro.txt`` ma 1319 B (tyle podaje ``content-length`` złota kroku 30),
# a złoto kroku 26 ma ``size`` 1352 — bo upstream liczy ``sys.getsizeof`` treści (DOC:823).
BLOB_BYTES = 1319
BLOB_SIZE = sys.getsizeof(bytes(BLOB_BYTES))

# Klucze tras /v1/document/*, które muszą odmawiać na cudzym dokumencie (CONTRACT C0 p. 9).
DOCUMENT_REFUSAL_KEYS: tuple[str, ...] = (
    "v1_document_change_status",
    "v1_document_run",
    "v1_document_get",
    "v1_document_thumbnails",
)

_PRINCIPAL = Principal(USER_ID, "bob@x.pl", is_superuser=False, is_service=False, auth_kind="jwt")


def _upload_info_golden_data() -> dict[str, Any]:
    """``body.data`` złota kroku 26 (``POST /v1/document/upload_info``)."""
    path = GOLDEN / "v1__document__upload_info" / "documents_extras--26.json"
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8"))["body"]["data"])


def _request() -> Request:
    """Żądanie z parametrem ścieżki ``document_id`` (bez I/O)."""
    scope: dict[str, Any] = {
        "type": "http",
        "path": f"/v1/document/get/{DOCUMENT_ID}",
        "path_params": {"document_id": DOCUMENT_ID},
    }
    return Request(scope)


def _uploaded() -> UploadedFile:
    """Plik wgrany bez datasetu — te same pola, co zwraca usługa uploadu (DOC:811-829)."""
    return UploadedFile(
        id="f" * 32,
        name="ragflow_intro.txt",
        size=BLOB_SIZE,
        extension="txt",
        mime_type="text/plain",
        created_by=USER_ID,
        created_at=CREATED_AT,
    )


def test_refusal_profiles_cover_document_routes() -> None:
    """Cztery trasy z dokumentem mają wpis odmowy 108 z komunikatem upstreamu (C0 p. 5 i 9)."""
    for key in DOCUMENT_REFUSAL_KEYS:
        profile = PROFILES_V024[key]
        assert profile.code == LACK_PERMISSION, key
        assert profile.message == "No authorization.", key


def test_document_refusal_envelope_is_code_and_message_only() -> None:
    """Koperta odmowy tych tras: ``{code, message}`` bez ``data`` (koperty v0.24, C2)."""
    for key in DOCUMENT_REFUSAL_KEYS:
        response = refuse(_request(), _PRINCIPAL, key, None, compat="ragflow_0_24")
        assert response.status_code == HTTP_OK
        assert json.loads(bytes(response.body)) == {
            "code": LACK_PERMISSION,
            "message": "No authorization.",
        }, key


def test_upload_info_body_matches_golden_keys_and_values() -> None:
    """``data`` upload_info ma osiem kluczy złota --26, w tym ``preview_url: null`` i ``size``."""
    golden = _upload_info_golden_data()
    body = uploaded_file(_uploaded())
    assert set(body) == set(golden)
    assert body["name"] == golden["name"] == "ragflow_intro.txt"
    assert body["extension"] == golden["extension"] == "txt"
    assert body["mime_type"] == golden["mime_type"] == "text/plain"
    assert body["size"] == golden["size"] == BLOB_SIZE
    assert body["preview_url"] is None
    assert golden["preview_url"] is None
