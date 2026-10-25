"""Testy HTTP tras OpenAI-compat (brief OD p. 2-3, 4; brief OC p. 2-3).

Zakres OD: błąd nieznanego ``model`` (złoto ``openai_dify--10``), odmowa dla cudzego
czatu (złoto ``errors_access--35``) oraz rozszerzenie ``GET /openai/{chat_id}/models``
(02-api §9, brak złota). Zakres OC: kształt OpenAI (``choices``/``usage``) na ścieżce
sukcesu, ramki SSE ``chat.completion.chunk`` + ``data:[DONE]`` i alias ``/chats_openai/…``
(złoto ``openai_compat--02…--05``). Odpowiedź błędu tych tras nie ma klucza ``data``.
"""

import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.auth.principal import get_principal
from app.core.config import Settings
from app.core.container import Container
from app.domain.policy import Principal
from app.llm.tokens import count_tokens
from app.main import create_app
from tests.integration.chat.conftest import chat_with_doc, seed_chat
from tests.integration.ingest.conftest import seed_dataset
from tests.integration.ingest.pipeline_helpers import make_container
from tests.integration.retrieval.conftest import principal_for

pytestmark = [pytest.mark.db, pytest.mark.fakellm]

_DOC = "Wawelski smok mieszkał w jamie pod Wawelem."
_MESSAGES = [{"role": "user", "content": "smok wawelski"}]
_HTTP_OK = 200
_OWNED_BY = "wawelsky-dragon"
_MODEL_ID_LEN = 32
# Trasa kanoniczna i alias deprecated (E2-1 OC; upstream openai_api.py:237 i :108).
_PATHS = (
    "/api/v1/openai/{chat_id}/chat/completions",
    "/api/v1/chats_openai/{chat_id}/chat/completions",
)
# Profil zgodności jawny: ``CompatDep`` czyta nagłówek tylko dla principala klucza API (C7).
_V024_HEADER = {"X-RAGFlow-Compat": "0.24"}


def _api_key_principal(user_id: str) -> Principal:
    """Principal klucza API — z ``auth_kind="jwt"`` nagłówek profilu byłby zignorowany (C7)."""
    return Principal(
        user_id,
        f"{user_id}@example.com",
        is_superuser=False,
        is_service=False,
        auth_kind="api_key",
    )


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener testowy ze storage w tmp_path (wzór tests/integration/api/test_dify_routes)."""
    instance = await make_container(migrated_db, tmp_path)
    yield instance
    await instance.aclose()


def _app(container: Container, principal: Principal) -> FastAPI:
    """Aplikacja z nadpisanym uwierzytelnianiem (klucz API i JWT dają ten sam principal)."""
    app = create_app(container.settings, container)
    app.dependency_overrides[get_principal] = lambda: principal
    return app


def _body(model: str, **extra: object) -> dict[str, object]:
    """Ciało POST /openai/{chat_id}/chat/completions jak w kroku openai_unknown_model_v0_27."""
    return {"model": model, "messages": _MESSAGES, "stream": False, **extra}


async def test_unknown_model_envelope(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Nieznany ``model`` → HTTP 200, code 101 bez klucza ``data`` (złoto openai_dify--10)."""
    dataset = await seed_dataset(sm)
    chat = await seed_chat(sm, dataset.tenant_id, [dataset.id])
    app = _app(container, principal_for(dataset.tenant_id))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            f"/api/v1/openai/{chat.id}/chat/completions", json=_body("no-such-model")
        )
    assert resp.status_code == _HTTP_OK, resp.text
    assert resp.json() == {"code": 101, "message": "`llm_id` no-such-model doesn't exist"}


@pytest.mark.parametrize("path", _PATHS)
async def test_foreign_chat_denied(
    container: Container, sm: async_sessionmaker[AsyncSession], path: str
) -> None:
    """Cudzy czat → code 102 „You don't own the chat <id>” bez ``data`` (errors_access--35)."""
    dataset = await seed_dataset(sm)
    chat = await seed_chat(sm, dataset.tenant_id, [dataset.id])
    app = _app(container, principal_for("intruder"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(path.format(chat_id=chat.id), json=_body("model"))
    assert resp.status_code == _HTTP_OK, resp.text
    assert resp.json() == {"code": 102, "message": f"You don't own the chat {chat.id}"}


@pytest.mark.parametrize("path", _PATHS)
async def test_placeholder_model_completes(
    container: Container, sm: async_sessionmaker[AsyncSession], path: str
) -> None:
    """``model`` = „model” → kształt OpenAI ``chat.completion`` (złoto openai_compat--02/--04)."""
    chat, _dataset, _doc = await chat_with_doc(container, sm, _DOC)
    app = _app(container, principal_for(chat.tenant_id))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(path.format(chat_id=chat.id), json=_body("model"))
    assert resp.status_code == _HTTP_OK, resp.text
    body = resp.json()
    content = body["choices"][0]["message"]["content"]
    assert content
    assert body["id"] == f"chatcmpl-{chat.id}"
    assert body["object"] == "chat.completion"
    # Placeholder „model” znaczy „model czatu”; na wyjściu id wiersza modelu (K11 §10a p. 4),
    # a nie nazwa trzymana w ``chats.llm_id`` (złoto openai_compat--02: ``<ID:id#2>``).
    assert len(body["model"]) == _MODEL_ID_LEN
    assert body["model"] != chat.llm_id
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["choices"][0]["logprobs"] is None
    assert body["usage"] == {
        "prompt_tokens": count_tokens(_MESSAGES[0]["content"]),
        "completion_tokens": count_tokens(content),
        "total_tokens": count_tokens(_MESSAGES[0]["content"]) + count_tokens(content),
        "completion_tokens_details": {
            "reasoning_tokens": count_tokens(_MESSAGES[0]["content"]),
            "accepted_prediction_tokens": count_tokens(content),
            "rejected_prediction_tokens": 0,
        },
    }


@pytest.mark.parametrize("path", _PATHS)
async def test_stream_chunks_openai_shape(
    container: Container, sm: async_sessionmaker[AsyncSession], path: str
) -> None:
    """``stream=true`` → ramki ``chat.completion.chunk`` z deltą, ``usage`` i ``data:[DONE]``."""
    chat, _dataset, _doc = await chat_with_doc(container, sm, _DOC)
    app = _app(container, principal_for(chat.tenant_id))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(path.format(chat_id=chat.id), json=_body("model", stream=True))
    assert resp.status_code == _HTTP_OK, resp.text
    frames = [frame for frame in resp.text.split("\n\n") if frame]
    assert frames[-1] == "data:[DONE]"
    chunks = [json.loads(frame.removeprefix("data:")) for frame in frames[:-1]]
    assert [chunk["object"] for chunk in chunks] == ["chat.completion.chunk"] * len(chunks)
    deltas = [chunk["choices"][0]["delta"] for chunk in chunks]
    assert deltas[0]["role"] == "assistant"
    content = "".join(str(delta["content"]) for delta in deltas if delta["content"])
    assert content
    # Tokeny liczone per delta (upstream :134) — suma delt nie równa się tokenom całości.
    used = sum(count_tokens(str(delta["content"])) for delta in deltas if delta["content"])
    prompt_tokens = count_tokens(_MESSAGES[0]["content"])
    final = chunks[-1]
    assert final["choices"][0]["finish_reason"] == "stop"
    assert final["choices"][0]["delta"]["content"] is None
    assert final["usage"] == {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": used,
        "total_tokens": prompt_tokens + used,
    }


async def test_models_list(container: Container, sm: async_sessionmaker[AsyncSession]) -> None:
    """GET /openai/{chat_id}/models → kształt OpenAI z modelem czatu (02-api §9)."""
    dataset = await seed_dataset(sm)
    chat = await seed_chat(sm, dataset.tenant_id, [dataset.id], llm_id="fake-chat")
    app = _app(container, principal_for(dataset.tenant_id))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(f"/api/v1/openai/{chat.id}/models")
    assert resp.status_code == _HTTP_OK, resp.text
    assert resp.json() == {
        "object": "list",
        "data": [{"id": "fake-chat", "object": "model", "owned_by": _OWNED_BY}],
    }


async def test_models_list_foreign_chat_denied(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Cudzy czat w GET /models → ten sam kod odmowy 102 (bez ``data``)."""
    dataset = await seed_dataset(sm)
    chat = await seed_chat(sm, dataset.tenant_id, [dataset.id])
    app = _app(container, principal_for("intruder"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(f"/api/v1/openai/{chat.id}/models")
    assert resp.status_code == _HTTP_OK, resp.text
    assert resp.json() == {"code": 102, "message": f"You don't own the chat {chat.id}"}


async def test_models_list_missing_chat(container: Container) -> None:
    """Nieznany czat → ta sama odmowa 102 co dla cudzego (upstream jedno sprawdzenie)."""
    app = _app(container, principal_for("whoever"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/v1/openai/0/models")
    assert resp.status_code == _HTTP_OK, resp.text
    assert resp.json() == {"code": 102, "message": "You don't own the chat 0"}


async def test_validation_before_ownership_in_v024(container: Container) -> None:
    """Profil 0.24: walidacja ``extra_body`` przed odmową właściciela czatu (DEC-092 p. 2).

    Port upstream (``test_chat_completions_openai.py``) pokrywa tylko profil domyślny, więc
    kolejność „walidacja → właściciel" (upstream ``openai_api.py:243-262``) pilnujemy tu
    dodatkowo w 0.24: nieistniejący czat plus zły ``extra_body`` daje komunikat walidacji,
    nie ``You don't own the chat …``.
    """
    app = _app(container, _api_key_principal("intruder"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/openai/invalid_chat_id/chat/completions",
            json=_body("model", extra_body="invalid_extra_body"),
            headers=_V024_HEADER,
        )
    assert resp.status_code == _HTTP_OK, resp.text
    assert resp.json() == {"code": 102, "message": "extra_body must be an object."}


async def test_metadata_condition_must_be_object(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """``extra_body.metadata_condition`` nie-obiekt → 102 po czacie i modelu (upstream :281-283)."""
    dataset = await seed_dataset(sm)
    chat = await seed_chat(sm, dataset.tenant_id, [dataset.id])
    app = _app(container, principal_for(dataset.tenant_id))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            f"/api/v1/openai/{chat.id}/chat/completions",
            json=_body("model", extra_body={"metadata_condition": "invalid"}),
        )
    assert resp.status_code == _HTTP_OK, resp.text
    assert resp.json() == {"code": 102, "message": "metadata_condition must be an object."}
