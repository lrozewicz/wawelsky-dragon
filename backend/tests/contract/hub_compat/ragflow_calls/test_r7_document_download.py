"""Odtworzenie wywołania hub-compat R7 (AG-28) i odmów R5/R7 dla konta nie-superuser (E2-5 T4).

Żądanie: ``downloadDocument`` (``hub-compat/src/utils/ragflow.ts:158-166``) —
``GET /api/v1/datasets/{ds}/documents/{doc}`` z samym ``Authorization`` (bez ``Content-Type``),
a odpowiedź jest przekazywana przeglądarce w ``documents.ts:27-34``
(``hub-compat/src/routes/api/ragflow/`` — kopiuje nagłówki ``Content-Type``
i ``Content-Disposition``; ``!res.ok`` → 502). Odmowy WD to koperty JSON przy HTTP 200,
więc klient hub-compat widzi tam „sukces”; testy pilnują, że na tych trasach nie lecą bajty
cudzego pliku ani odpowiedź modelu.
"""

import httpx
import pytest

from tests.contract.hub_compat.ragflow_calls.conftest import (
    DOC_TEXT,
    QUESTION,
    HubAccount,
    HubChat,
    doc_headers,
    hub_headers,
    ok_data,
)

pytestmark = [
    pytest.mark.hub_compat,
    pytest.mark.contract,
    pytest.mark.db,
    pytest.mark.fakellm,
]

_HTTP_OK = 200
_CODE_DATA_ERROR = 102
# Profil 0.24 pinuje ten mimetype dla pobrania dokumentu (złoto documents_extras--28).
_OCTET_STREAM = "application/octet-stream"
_JSON = "application/json"
# Identyfikator dokumentu, którego nie ma w bazie (K5 §1: 32 znaki hex).
_ZEROS = "0" * 32


async def _download(
    client: httpx.AsyncClient, token: str, dataset_id: str, document_id: str
) -> httpx.Response:
    """``downloadDocument`` (ragflow.ts:158-166) — GET z samym ``Authorization``."""
    return await client.get(
        f"/api/v1/datasets/{dataset_id}/documents/{document_id}",
        headers=doc_headers(token),
    )


async def _session_count(client: httpx.AsyncClient, token: str, chat_id: str) -> int:
    """``listSessions`` (ragflow.ts:25-30) — liczba sesji czatu (konto ``hub`` widzi cudzy czat)."""
    listed = ok_data(
        await client.get(
            f"/api/v1/chats/{chat_id}/sessions?page_size=100", headers=hub_headers(token)
        )
    )
    assert isinstance(listed, list)
    return len(listed)


def _refusal(response: httpx.Response) -> dict[str, object]:
    """Koperta odmowy: JSON, bez ``detail`` i bez bajtów pliku."""
    assert response.headers["content-type"].startswith(_JSON), response.headers
    body = response.json()
    assert isinstance(body, dict)
    assert "detail" not in body
    return body


async def test_ag28_r7_download_bytes_and_headers(
    client: httpx.AsyncClient, hub: HubAccount, hub_chat: HubChat
) -> None:
    """AG-28/R7: ``hub`` pobiera cudzy dokument — bajty pliku i nagłówki dla przeglądarki.

    Złoto v0.24.0 ``datasets___documents___/documents_extras--28.json``: HTTP 200,
    ``content-type: application/octet-stream`` (profil 0.24 pinuje ten mimetype dla pobrania,
    mimo rozszerzenia ``.txt``) i ``content-length`` równy rozmiarowi pliku. Nazwa pliku
    jedzie w ``Content-Disposition``; 03-hub-compat §3 podaje wariant ``filename=…``, a WD (jak
    upstream) wysyła ``filename*=UTF-8''…`` — rozbieżność prozy i złota zanotowana w raporcie.
    """
    response = await _download(client, hub.token, hub_chat.dataset_id, hub_chat.document_id)
    assert response.status_code == _HTTP_OK, response.text
    # ``ingest_text`` zapisuje ``text.encode()`` (tests/integration/retrieval/conftest.py:145-152).
    assert response.content == DOC_TEXT.encode()
    assert response.headers["content-type"] == _OCTET_STREAM
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment")
    assert hub_chat.document_name in disposition


async def test_ag28_r7_missing_document_returns_json_envelope(
    client: httpx.AsyncClient, hub: HubAccount, hub_chat: HubChat
) -> None:
    """AG-28/R7: nieistniejący dokument → koperta JSON, nie bajty pliku.

    Złoto ``datasets___documents__000…/errors_access--47.json``: HTTP 200, ``application/json``,
    ``{code: 102, message: …}`` — bez ``detail`` (koperta K3, nie błąd FastAPI).
    """
    response = await _download(client, hub.token, hub_chat.dataset_id, _ZEROS)
    assert response.status_code == _HTTP_OK, response.text
    body = _refusal(response)
    assert sorted(body) == ["code", "message"]
    assert body["code"] == _CODE_DATA_ERROR
    assert body["message"]


async def test_r7_stranger_denied_foreign_dataset(
    client: httpx.AsyncClient, stranger: HubAccount, hub_chat: HubChat
) -> None:
    """R7: nie-superuser na cudzym datasecie — odmowa, nigdy bajty cudzego pliku.

    Złoto ``datasets___documents___/errors_access--15.json``: HTTP 200 i
    ``{code: 102, message: "You do not own the dataset <dataset_id>."}``.
    """
    response = await _download(client, stranger.token, hub_chat.dataset_id, hub_chat.document_id)
    assert response.status_code == _HTTP_OK, response.text
    assert _refusal(response) == {
        "code": _CODE_DATA_ERROR,
        "message": f"You do not own the dataset {hub_chat.dataset_id}.",
    }
    assert DOC_TEXT.encode() not in response.content


async def test_r5_stranger_denied_completion_on_foreign_chat(
    client: httpx.AsyncClient, hub: HubAccount, stranger: HubAccount, hub_chat: HubChat
) -> None:
    """R5: cudzy czat — odmowa zamiast odpowiedzi modelu, bez nowej sesji.

    Złoto v0.24.0 ``chats___completions/errors_access--33.json``: HTTP 200,
    ``{code: 102, message: "You don't own the chat <chat_id>"}``; sesje właściciela bez zmian.
    """
    before = await _session_count(client, hub.token, hub_chat.chat_id)
    response = await client.post(
        f"/api/v1/chats/{hub_chat.chat_id}/completions",
        headers=hub_headers(stranger.token),
        json={"question": QUESTION, "stream": False},
    )
    assert response.status_code == _HTTP_OK, response.text
    body = _refusal(response)
    assert body["code"] != 0
    assert body == {
        "code": _CODE_DATA_ERROR,
        "message": f"You don't own the chat {hub_chat.chat_id}",
    }
    data = body.get("data")
    assert not (isinstance(data, dict) and "answer" in data)
    assert await _session_count(client, hub.token, hub_chat.chat_id) == before


async def test_r5_stranger_denied_stream_completion(
    client: httpx.AsyncClient, hub: HubAccount, stranger: HubAccount, hub_chat: HubChat
) -> None:
    """R5: ``stream:true`` na cudzym czacie — odmowa przed strumieniem (JSON, nie SSE).

    Wzorzec: ``test_completions_routes.py::test_other_users_chat_denied_before_stream``
    (``tests/integration/api/``); tutaj profil 0.24 z klucza, więc koperta to 102
    ``You don't own the chat <id>``
    (złoto v0.24.0 ``chats___completions/errors_access--33.json``).
    """
    before = await _session_count(client, hub.token, hub_chat.chat_id)
    response = await client.post(
        f"/api/v1/chats/{hub_chat.chat_id}/completions",
        headers=hub_headers(stranger.token),
        json={"question": QUESTION, "stream": True},
    )
    assert response.status_code == _HTTP_OK, response.text
    assert response.headers["content-type"].startswith(_JSON), response.headers
    body = _refusal(response)
    assert body["code"] != 0
    data = body.get("data")
    assert not (isinstance(data, dict) and "answer" in data)
    assert await _session_count(client, hub.token, hub_chat.chat_id) == before
