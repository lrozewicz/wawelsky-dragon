"""Testy ``POST /api/v1/chat/recommendation`` z ``search_id`` (brief T4; CONTRACT §D4/§D7).

Wzorce: ``test_related_questions_auth.py`` (trasa i koperta odmowy), ``test_searches_routes.py``
(klient ASGI, kontener, seedowanie wyszukiwarek). Brama LLM jest owinięta rekorderem, więc
sprawdzamy realne wywołanie na fake-llm (T4 p. 4): model z ``search_config.chat_id`` i parametry
z ``llm_setting``. Złoto: ``tests/contract/golden/v0.27.2/chat__recommendation/searches--26.json``.
"""

import os
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.auth.principal import get_principal
from app.core.config import Settings
from app.core.container import Container
from app.core.error_codes import RetCode
from app.domain.policy import Principal
from app.llm.types import ChatMessage, ChatResult, ModelRef
from app.main import create_app
from tests.integration.chat.conftest import register_think_model, seed_user
from tests.integration.ingest.pipeline_helpers import make_container
from tests.integration.retrieval.conftest import principal_for

pytestmark = [
    pytest.mark.db,
    pytest.mark.fakellm,
    pytest.mark.skipif(
        not os.environ.get("WD_LLM_BASE_URL"),
        reason="fakellm: brak WD_LLM_BASE_URL (eksportuje verify.sh)",
    ),
]

_HTTP_OK = 200
_NO_AUTHORIZATION = "no authorization"
# Koperta odmowy dla brakującej i cudzej wyszukiwarki (CONTRACT §D7, profil chat_recommendation).
_DENIED = {
    "code": RetCode.AUTHENTICATION_ERROR,
    "data": False,
    "message": _NO_AUTHORIZATION,
}
_QUESTION = {"question": "smokwawelski"}
_DEFAULT_MODEL = "fake-chat"
_SEARCH_MODEL = "fake-chat-think"
# Domyślne parametry generacji (LLM_SETTING_DEFAULTS, llm_service.py:36).
_DEFAULT_PARAMS = {"temperature": 0.1, "top_p": 0.3}


class _RecordingGateway:
    """Owija bramę LLM, notując modele i parametry czatu (T4: weryfikacja ``chat_id``)."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls: list[dict[str, Any]] = []

    async def chat(
        self, model: ModelRef, messages: Sequence[ChatMessage], **kwargs: Any
    ) -> ChatResult:
        """Notuje wywołanie i przekazuje je do prawdziwej bramy (fake-llm)."""
        self.calls.append({"model": model.name, **kwargs})
        return await self._inner.chat(model, messages, **kwargs)  # type: ignore[no-any-return]

    def __getattr__(self, name: str) -> Any:
        """Reszta portu (``aclose``, embeddingi) bez zmian."""
        return getattr(self._inner, name)


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener testowy z bramą LLM na fake-llm (wzorzec test_chats_routes.py)."""
    instance = await make_container(migrated_db, tmp_path)
    yield instance
    await instance.aclose()


def _app(container: Container, principal: Principal) -> FastAPI:
    """Aplikacja na życiu kontenerze (bez lifespan) z nadpisanym uwierzytelnianiem."""
    app = create_app(container.settings, container)
    app.dependency_overrides[get_principal] = lambda: principal
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    """Klient ASGI nad aplikacją testową (wzorzec test_searches_routes.py)."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _record(container: Container) -> _RecordingGateway:
    """Podstawia rekorder wokół bramy LLM kontenera (przed pierwszym wywołaniem)."""
    recorder = _RecordingGateway(container.llm)
    container.llm = recorder  # type: ignore[assignment]
    return recorder


async def _create_search(
    client: httpx.AsyncClient, name: str, *, search_config: Mapping[str, Any]
) -> str:
    """Tworzy wyszukiwarkę przez API i zwraca ``search_id``."""
    resp = await client.post(
        "/api/v1/searches", json={"name": name, "search_config": dict(search_config)}
    )
    assert resp.status_code == _HTTP_OK
    body = resp.json()
    assert body["code"] == RetCode.SUCCESS
    return str(body["data"]["search_id"])


async def _post(client: httpx.AsyncClient, path: str, *, search_id: str | None) -> dict[str, Any]:
    """POST rekomendacji z opcjonalnym ``search_id`` i pytaniem."""
    payload: dict[str, Any] = dict(_QUESTION)
    if search_id is not None:
        payload["search_id"] = search_id
    resp = await client.post(path, json=payload)
    assert resp.status_code == _HTTP_OK
    return dict(resp.json())


def _assert_ok_list(body: Mapping[str, Any]) -> None:
    """Złoto zna tylko wariant OK: ``code 0`` i lista w ``data`` (treść zależy od fake-llm)."""
    assert body["code"] == RetCode.SUCCESS, body
    assert isinstance(body["data"], list), body


async def test_own_search_uses_model_and_settings_from_search_config(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Własny ``search_id``: model z ``chat_id``, parametry z ``llm_setting`` (T4 p. 1, 4)."""
    alice_id = await seed_user(sm)
    alice = principal_for(alice_id)
    await register_think_model(sm)
    recorder = _record(container)
    async with _client(_app(container, alice)) as client:
        tuned = await _create_search(
            client,
            "wd_t4_strojona",
            search_config={"chat_id": _SEARCH_MODEL, "llm_setting": {"temperature": 0.9}},
        )
        # ``temperature_enabled: False`` → parametr wraca do stałej domyślnej (upstream).
        off = await _create_search(
            client,
            "wd_t4_wylaczona",
            search_config={
                "chat_id": _SEARCH_MODEL,
                "llm_setting": {"temperature": 0.9, "temperature_enabled": False},
            },
        )
        tuned_body = await _post(client, "/api/v1/chat/recommendation", search_id=tuned)
        off_body = await _post(client, "/api/v1/chat/recommendation", search_id=off)

    _assert_ok_list(tuned_body)
    _assert_ok_list(off_body)
    tuned_call, off_call = recorder.calls
    assert tuned_call["model"] == _SEARCH_MODEL
    assert (tuned_call["temperature"], tuned_call["top_p"]) == (0.9, _DEFAULT_PARAMS["top_p"])
    assert tuned_call["extra"] == {"frequency_penalty": 0.7, "presence_penalty": 0.4}
    assert off_call["temperature"] == _DEFAULT_PARAMS["temperature"]


async def test_own_search_without_chat_id_uses_default_model(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Własny ``search_id`` bez ``chat_id``: model domyślny tenanta, parametry domyślne."""
    alice = principal_for(await seed_user(sm))
    recorder = _record(container)
    async with _client(_app(container, alice)) as client:
        search_id = await _create_search(client, "wd_t4_bez_modelu", search_config={})
        body = await _post(client, "/api/v1/chat/recommendation", search_id=search_id)

    _assert_ok_list(body)
    assert recorder.calls[0]["model"] == _DEFAULT_MODEL
    assert recorder.calls[0]["temperature"] == _DEFAULT_PARAMS["temperature"]


async def test_foreign_and_missing_search_denied_without_llm(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Cudzy i nieistniejący ``search_id`` → koperta odmowy czatu, bez wywołania LLM (§D7)."""
    alice = principal_for(await seed_user(sm))
    recorder = _record(container)
    async with _client(_app(container, alice)) as client:
        owned = await _create_search(client, "wd_t4_cudza", search_config={})
    outsider = _app(container, principal_for(uuid.uuid4().hex))
    async with _client(outsider) as stranger:
        foreign = await _post(stranger, "/api/v1/chat/recommendation", search_id=owned)
        missing = await _post(stranger, "/api/v1/chat/recommendation", search_id=uuid.uuid4().hex)

    assert foreign == _DENIED, foreign
    assert missing == _DENIED, missing
    assert recorder.calls == []


async def test_without_search_id_behaviour_unchanged(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Brak ``search_id`` (i puste ``""``): jak dotąd — model domyślny, lista pytań."""
    alice = principal_for(await seed_user(sm))
    recorder = _record(container)
    async with _client(_app(container, alice)) as client:
        plain = await _post(client, "/api/v1/chat/recommendation", search_id=None)
        empty = await _post(client, "/api/v1/chat/recommendation", search_id="")

    _assert_ok_list(plain)
    assert _assert_ok_list(empty) is None
    assert [call["model"] for call in recorder.calls] == [_DEFAULT_MODEL, _DEFAULT_MODEL]


async def test_related_questions_alias_with_search_id(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Alias ``/sessions/related_questions`` działa identycznie (T4 p. 3)."""
    alice = principal_for(await seed_user(sm))
    await register_think_model(sm)
    recorder = _record(container)
    async with _client(_app(container, alice)) as client:
        search_id = await _create_search(
            client, "wd_t4_alias", search_config={"chat_id": _SEARCH_MODEL}
        )
        body = await _post(client, "/api/v1/sessions/related_questions", search_id=search_id)

    _assert_ok_list(body)
    assert recorder.calls[0]["model"] == _SEARCH_MODEL
