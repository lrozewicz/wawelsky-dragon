"""Harness testów odtwarzających wywołania hub-compat (brief E2-5 T1, kontrakt „Harness (T1)").

Fixture'y ``settings``/``container``/``app``/``client`` to kopia wzorca z
``tests/integration/api/test_hub_client_v024.py`` (jawnie, bez importu z modułu testowego);
``fresh_db``/``migrated_db``/``auth_settings``/``sm`` przychodzą z ``tests/contract/conftest.py``.

Klucze API zakładamy z ``compat_profile="ragflow_0_24"`` i NIE wysyłamy ``X-RAGFlow-Compat``
— profil zgodności bierze się z klucza, jak u hub-compat (``ragflow.ts:11-16``).
``hub_headers`` zakłada ``Content-Type`` także przy GET/DELETE (A9), ``doc_headers`` go nie ma
(R7 — pobranie bajtów dokumentu).
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.db.repositories import documents as documents_repo
from app.db.uow import transaction
from app.main import create_app
from tests.integration.chat.conftest import (
    chat_with_doc,
    register_think_model,
    seed_chat,
)
from tests.integration.ingest.pipeline_helpers import make_container

# Sekret testowy (K7 §1.7); nigdy nie jest prawdziwym sekretem.
PASSWORD = "Secret-pass1"  # noqa: S105
QUESTION = "Gdzie mieszkał smok wawelski?"
DOC_TEXT = "Wawelski smok mieszkał w jamie pod Wawelem."
# Model czatu fake-llm emitujący blok ``<think>…</think>`` (K10 §4, ``tools/fake-llm``).
_THINK_MODEL = "fake-chat-think"
# Profil zgodności zapisany na kluczu (C7); bez nagłówka X-RAGFlow-Compat.
_COMPAT_V024 = "ragflow_0_24"
_OK = 200
_CODE_SUCCESS = 0

_HUB_EMAIL = "hub-compat@svc.test"
_STRANGER_EMAIL = "stranger@svc.test"
_OWNER_EMAIL = "owner@x.pl"


@dataclass(frozen=True)
class HubAccount:
    """Konto hub-compat z jawnym tokenem klucza API (token, user_id)."""

    token: str
    user_id: str


@dataclass(frozen=True)
class HubChat:
    """Czat + dataset + jeden dokument po ingestii (współdzielony opis dla `hub_chat`)."""

    chat_id: str
    dataset_id: str
    document_id: str
    document_name: str


def hub_headers(token: str) -> dict[str, str]:
    """Nagłówki klucza hub-compat; ``Content-Type`` także przy GET/DELETE (A9)."""
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def doc_headers(token: str) -> dict[str, str]:
    """Nagłówki pobrania pliku dokumentu: tylko ``Authorization`` (R7, bez ``Content-Type``)."""
    return {"Authorization": f"Bearer {token}"}


def ok_data(response: httpx.Response) -> Any:
    """``data`` koperty sukcesu (HTTP 200, ``code`` 0) — inaczej asercja z treścią odpowiedzi."""
    assert response.status_code == _OK, response.text
    payload = response.json()
    assert payload["code"] == _CODE_SUCCESS, payload
    return payload["data"]


@pytest.fixture
def settings(auth_settings: Settings, tmp_path: Path) -> Settings:
    """Ustawienia auth + storage w katalogu tymczasowym (wzór test_hub_client_v024)."""
    return auth_settings.model_copy(update={"storage_root": str(tmp_path)})


@pytest.fixture
async def container(settings: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener testowy (modele fake, storage w tmp_path)."""
    instance = await make_container(settings, tmp_path)
    yield instance
    await instance.aclose()


@pytest.fixture
def app(settings: Settings, container: Container) -> FastAPI:
    """Aplikacja na tym samym kontenerze co test (bez sieci, ASGITransport)."""
    return create_app(settings, container)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Klient ASGI (bez X-RAGFlow-Compat — profil bierze się z klucza)."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def _account(container: Container, email: str, *, superuser: bool) -> HubAccount:
    """Konto + klucz API z ``compat_profile=ragflow_0_24`` (wzór ``test_hub_client_v024``)."""
    assert container.users is not None
    assert container.api_keys is not None
    user = await container.users.create(email=email, password=PASSWORD, is_superuser=superuser)
    key = await container.api_keys.create(
        container.users.principal_of(user), compat_profile=_COMPAT_V024
    )
    return HubAccount(key.token, user.id)


@pytest.fixture
async def hub(container: Container) -> HubAccount:
    """Konto SERWISOWE hub-compat: superuser z kluczem 0.24 (R1 — widzi cudze czaty)."""
    return await _account(container, _HUB_EMAIL, superuser=True)


@pytest.fixture
async def stranger(container: Container) -> HubAccount:
    """Konto zwykłe (nie-superuser) z kluczem 0.24 — cudzego czatu nie widzi (R1)."""
    return await _account(container, _STRANGER_EMAIL, superuser=False)


@pytest.fixture
async def owner(container: Container) -> HubAccount:
    """Właściciel czatu (konto zwykłe) — czat jest cudzy dla `hub` i `stranger`."""
    return await _account(container, _OWNER_EMAIL, superuser=False)


@pytest.fixture
async def hub_chat(
    container: Container, sm: async_sessionmaker[AsyncSession], owner: HubAccount
) -> HubChat:
    """Czat `owner` z datasetem i jednym dokumentem po ingestii (cudzy dla `hub`/`stranger`)."""
    row, dataset, document_id = await chat_with_doc(container, sm, DOC_TEXT, owner=owner.user_id)
    async with transaction(sm) as session:
        document = await documents_repo.get(session, document_id)
    assert document is not None
    return HubChat(row.id, dataset.id, document_id, document.name)


@pytest.fixture
async def reasoning_llm(
    sm: async_sessionmaker[AsyncSession], hub_chat: HubChat, owner: HubAccount
) -> HubChat:
    """Czat z modelem ``fake-chat-think`` (reasoning) na tym samym datasecie — dla T2.

    ``fake-llm`` obsługuje reasoning: model ``fake-chat-think`` poprzedza odpowiedź blokiem
    ``<think>Rozważam pytanie.</think>`` (``tools/fake-llm/fake_llm/answers.py``), a WD
    rozdziela go do ``data.thinking`` (AG-04, R5 — zakres T2).
    """
    await register_think_model(sm)
    row = await seed_chat(sm, owner.user_id, [hub_chat.dataset_id], llm_id=_THINK_MODEL)
    return HubChat(row.id, hub_chat.dataset_id, hub_chat.document_id, hub_chat.document_name)
