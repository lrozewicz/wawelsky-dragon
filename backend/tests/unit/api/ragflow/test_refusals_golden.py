"""Test tablicowy prezenterą odmów wobec złota obu profili (kontrakt E2-2f C2/C3).

Każdy wiersz to trójka (profil, klucz trasy w mapie, plik złota). Dla wpisów bez własnego
szablonu (``message is None``) komunikat bierze się z wyjątku trasy, więc test buduje go
z komunikatu złota, podmieniając tokeny ``<ID:…>`` na identyfikatory wstrzyknięte do żądania.
Porównanie komunikatów normalizuje tokeny złota i identyfikatory po obu stronach do ``<ID>``.

Pliki złota (kontrakt E2-2f):
- C2 — mapa ``PROFILES_V024`` (v0.24.0), bez ``documents_upload`` (złoto kroku 13 to sukces
  upstream — POMIJANE w teście tablicowym).
- C3 — istniejące ``PROFILES`` (v0.27.2); drugi plik klucza daje osobny wiersz.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest
from starlette.requests import Request

from app.api.ragflow.refusals import PROFILES, refuse
from app.api.ragflow.refusals_v024 import PROFILES_V024
from app.core.errors import NotFound, PermissionDenied
from app.domain.policy import Principal

GOLDEN = Path(__file__).resolve().parents[3] / "contract" / "golden"

_OK = 200
_LACK_PERMISSION = 108

_USER_ID = "USER0"
_DATASET_ID = "DSET0"
_CHAT_ID = "CHAT0"
_DOCUMENT_ID = "DOC00"

# Identyfikatory podmieniane na tokeny normalizacji (kolejność jak w briefie T1a).
_ID_PATTERN = f"{_USER_ID}|{_DATASET_ID}|{_CHAT_ID}|{_DOCUMENT_ID}"
_GOLDEN_ID_RE = r"<ID:[^>]*>"

# Tokeny złota → identyfikatory wstrzykiwane do żądania (te same, co podmienia normalizacja).
_TOKENS = {
    "<ID:id#1>": _USER_ID,
    "<ID:dataset#1>": _DATASET_ID,
    "<ID:chat#1>": _CHAT_ID,
    "<ID:document#1>": _DOCUMENT_ID,
    "<ID:id#3>": _DATASET_ID,
}

_MAPS = {"ragflow_0_27": PROFILES, "ragflow_0_24": PROFILES_V024}

_ZEROS = "0" * 32

# Wiersze tabeli: (profil, klucz, ścieżka złota względem backend/tests/contract/golden).
_ROWS: list[tuple[str, str, str]] = [
    # --- v0.24.0 (C2) ---
    ("ragflow_0_24", "datasets_list", "v0.24.0/datasets/errors_access--12.json"),
    ("ragflow_0_24", "datasets_update", "v0.24.0/datasets___/errors_access--10.json"),
    ("ragflow_0_24", "datasets_delete", "v0.24.0/datasets/errors_access--53.json"),
    ("ragflow_0_24", "documents_list", "v0.24.0/datasets___documents/errors_access--14.json"),
    (
        "ragflow_0_24",
        "documents_list",
        f"v0.24.0/datasets__{_ZEROS}__documents/errors_access--44.json",
    ),
    ("ragflow_0_24", "documents_delete", "v0.24.0/datasets___documents/errors_access--50.json"),
    (
        "ragflow_0_24",
        "documents_download",
        "v0.24.0/datasets___documents___/errors_access--15.json",
    ),
    (
        "ragflow_0_24",
        "documents_download_missing_document",
        f"v0.24.0/datasets___documents__{_ZEROS}/errors_access--47.json",
    ),
    (
        "ragflow_0_24",
        "documents_update",
        "v0.24.0/datasets___documents___/errors_access--17.json",
    ),
    ("ragflow_0_24", "documents_parse", "v0.24.0/datasets___chunks/errors_access--18.json"),
    ("ragflow_0_24", "documents_stop", "v0.24.0/datasets___chunks/errors_access--20.json"),
    (
        "ragflow_0_24",
        "chunks_list",
        "v0.24.0/datasets___documents___chunks/errors_access--22.json",
    ),
    (
        "ragflow_0_24",
        "chunks_list_missing_document",
        f"v0.24.0/datasets___documents__{_ZEROS}__chunks/errors_access--48.json",
    ),
    (
        "ragflow_0_24",
        "chunks_create",
        "v0.24.0/datasets___documents___chunks/errors_access--23.json",
    ),
    (
        "ragflow_0_24",
        "chunks_delete",
        "v0.24.0/datasets___documents___chunks/errors_access--49.json",
    ),
    ("ragflow_0_24", "retrieval_query", "v0.24.0/retrieval/errors_access--24.json"),
    ("ragflow_0_24", "chats_update", "v0.24.0/chats___/errors_access--26.json"),
    ("ragflow_0_24", "chats_update", f"v0.24.0/chats__{_ZEROS}/errors_access--45.json"),
    ("ragflow_0_24", "chats_delete_many", "v0.24.0/chats/errors_access--52.json"),
    ("ragflow_0_24", "chats_completions", "v0.24.0/chats___completions/errors_access--33.json"),
    ("ragflow_0_24", "sessions_create", "v0.24.0/chats___sessions/errors_access--28.json"),
    ("ragflow_0_24", "sessions_list", "v0.24.0/chats___sessions/errors_access--29.json"),
    ("ragflow_0_24", "sessions_list", f"v0.24.0/chats__{_ZEROS}__sessions/errors_access--46.json"),
    ("ragflow_0_24", "sessions_rename", "v0.24.0/chats___sessions___/errors_access--32.json"),
    ("ragflow_0_24", "sessions_delete", "v0.24.0/chats___sessions/errors_access--51.json"),
    # --- v0.27.2 (C3) ---
    ("ragflow_0_27", "datasets_update", "v0.27.2/datasets___/errors_access--10.json"),
    ("ragflow_0_27", "datasets_get", "v0.27.2/datasets___/errors_access--11.json"),
    ("ragflow_0_27", "datasets_list", "v0.27.2/datasets/errors_access--12.json"),
    ("ragflow_0_27", "documents_upload", "v0.27.2/datasets___documents/errors_access--13.json"),
    ("ragflow_0_27", "documents_list", "v0.27.2/datasets___documents/errors_access--14.json"),
    (
        "ragflow_0_27",
        "documents_list",
        f"v0.27.2/datasets__{_ZEROS}__documents/errors_access--44.json",
    ),
    (
        "ragflow_0_27",
        "documents_download",
        "v0.27.2/datasets___documents___/errors_access--15.json",
    ),
    (
        "ragflow_0_27",
        "documents_update",
        "v0.27.2/datasets___documents___/errors_access--16.json",
    ),
    (
        "ragflow_0_27",
        "documents_parse",
        "v0.27.2/datasets___documents__parse/errors_access--19.json",
    ),
    (
        "ragflow_0_27",
        "documents_stop",
        "v0.27.2/datasets___documents__stop/errors_access--21.json",
    ),
    (
        "ragflow_0_27",
        "chunks_list",
        "v0.27.2/datasets___documents___chunks/errors_access--22.json",
    ),
    (
        "ragflow_0_27",
        "chunks_create",
        "v0.27.2/datasets___documents___chunks/errors_access--23.json",
    ),
    ("ragflow_0_27", "retrieval_query", "v0.27.2/retrieval/errors_access--24.json"),
    ("ragflow_0_27", "chats_get", "v0.27.2/chats___/errors_access--25.json"),
    ("ragflow_0_27", "chats_update", "v0.27.2/chats___/errors_access--26.json"),
    ("ragflow_0_27", "chats_update", "v0.27.2/chats___/errors_access--27.json"),
    ("ragflow_0_27", "sessions_create", "v0.27.2/chats___sessions/errors_access--28.json"),
    ("ragflow_0_27", "sessions_list", "v0.27.2/chats___sessions/errors_access--29.json"),
    ("ragflow_0_27", "sessions_get", "v0.27.2/chats___sessions___/errors_access--30.json"),
    ("ragflow_0_27", "sessions_rename", "v0.27.2/chats___sessions___/errors_access--31.json"),
    ("ragflow_0_27", "chats_completions", "v0.27.2/chats___completions/errors_access--33.json"),
    ("ragflow_0_27", "chat_completions", "v0.27.2/chat__completions/errors_access--34.json"),
    ("ragflow_0_27", "sessions_delete", "v0.27.2/chats___sessions/errors_access--51.json"),
    ("ragflow_0_27", "chats_delete_many", "v0.27.2/chats/errors_access--52.json"),
    ("ragflow_0_27", "datasets_delete", "v0.27.2/datasets/errors_access--53.json"),
    ("ragflow_0_27", "documents_delete", "v0.27.2/datasets___documents/errors_access--50.json"),
    (
        "ragflow_0_27",
        "chunks_delete",
        "v0.27.2/datasets___documents___chunks/errors_access--49.json",
    ),
]

_PRINCIPAL = Principal(
    _USER_ID, "bob@x.pl", is_superuser=False, is_service=False, auth_kind="api_key"
)


def _request() -> Request:
    """Żądanie z kompletem parametrów ścieżki używanych przez szablony (bez I/O)."""
    scope: dict[str, Any] = {
        "type": "http",
        "path": "/api/v1/datasets",
        "path_params": {
            "dataset_id": _DATASET_ID,
            "chat_id": _CHAT_ID,
            "document_id": _DOCUMENT_ID,
        },
    }
    return Request(scope)


def _err_for(profile_message: str | None, golden_message: str) -> NotFound | None:
    """Wyjątek trasy dla wpisu bez szablonu: komunikat złota z tokenami → identyfikatory."""
    if profile_message is not None:
        return None
    message = golden_message
    for token, value in _TOKENS.items():
        message = message.replace(token, value)
    return NotFound(message)


def _normalize_golden(message: str) -> str:
    """Token złota ``<ID:…>`` → ``<ID>``."""
    return re.sub(_GOLDEN_ID_RE, "<ID>", message)


def _normalize_ids(message: str) -> str:
    """Identyfikatory żądania → ``<ID>`` (te same, co podmienia złoto)."""
    return re.sub(_ID_PATTERN, "<ID>", message)


@pytest.mark.parametrize(("compat", "route", "golden_name"), _ROWS)
def test_refusal_matches_golden(compat: str, route: str, golden_name: str) -> None:
    """Koperta odmowy (status, kod, obecność/wartość ``data``, komunikat) zgodna ze złotem."""
    golden_body = json.loads((GOLDEN / golden_name).read_text())["body"]
    profile = _MAPS[compat][route]
    err = _err_for(profile.message, golden_body["message"])

    response = refuse(_request(), _PRINCIPAL, route, err, ids=[_DATASET_ID], compat=compat)
    body = json.loads(bytes(response.body))

    assert response.status_code == _OK
    assert body["code"] == golden_body["code"]
    assert ("data" in body) == ("data" in golden_body)
    if "data" in golden_body:
        assert body["data"] == golden_body["data"]
    assert _normalize_ids(body["message"]) == _normalize_golden(golden_body["message"])


def test_v024_key_absent_falls_back_to_108() -> None:
    """Klucz nieobecny w mapie v0.24 → ``PermissionDenied`` (108) z komunikatem wyjątku."""
    err = PermissionDenied("You don't own the chat x")
    with pytest.raises(PermissionDenied) as excinfo:
        refuse(_request(), _PRINCIPAL, "chats_get", err, compat="ragflow_0_24")
    assert excinfo.value.message == "You don't own the chat x"
    assert excinfo.value.code == _LACK_PERMISSION


def test_v024_key_absent_without_err_uses_no_authorization() -> None:
    """Bez wyjątku fallback v0.24 bierze ``no authorization`` (kontrakt E2-2f C1)."""
    with pytest.raises(PermissionDenied) as excinfo:
        refuse(_request(), _PRINCIPAL, "sessions_get", compat="ragflow_0_24")
    assert excinfo.value.message == "no authorization"


def test_v024_documents_upload_same_as_v027() -> None:
    """``documents_upload`` v0.24 to ten sam profil co v0.27 (K11 §10d p. 15)."""
    assert PROFILES_V024["documents_upload"] == PROFILES["documents_upload"]


def test_compat_is_required_keyword() -> None:
    """``compat`` jest obowiązkowy i keyword-only — wołanie bez niego to błąd użycia."""
    with pytest.raises(TypeError):
        refuse(_request(), _PRINCIPAL, "documents_list")  # type: ignore[call-arg]


def test_v024_profiles_codes_are_golden_codes() -> None:
    """Kody profili v0.24 mieszczą się w zbiorze kodów ze złota (102, 108, 109)."""
    assert {profile.code for profile in PROFILES_V024.values()} <= {102, 108, 109}
