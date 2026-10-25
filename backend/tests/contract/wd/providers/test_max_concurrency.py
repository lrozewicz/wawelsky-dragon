"""Walidacja `extra.max_concurrency` w POST/PATCH modelu instancji (K13 poprawka 2026-10-10 p. 1).

Wartość spoza int 1-32 (0, 33, 1.5, "4", None, bool) → 101 z komunikatem dosłownym; brak klucza,
1, 8 i 32 → sukces. PATCH `extra` zastępuje cały obiekt (nie gubi innych kluczy). Kontrakt C5.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, cast

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.container import Container
from app.db.repositories import models as models_repo
from app.db.repositories import provider_instances as provider_instances_repo
from app.db.repositories.models import ModelRow
from app.db.uow import transaction

pytestmark = pytest.mark.contract

OK = 200
ARGUMENT_ERROR = 101

PROVIDER = "litellm"
INSTANCE = "gw1"
GW_URL = "http://gw1.local/v1"
MESSAGE = "extra.max_concurrency must be an integer between 1 and 32"

# Wartości niepoprawne (K13 poprawka 2026-10-10 p. 1): bool i None jawnie, nie tylko poza zakresem.
INVALID = [0, 33, 1.5, "4", None, True, False]
VALID = [1, 8, 32]

SM = async_sessionmaker[AsyncSession]


def _models(instance: str) -> str:
    """Ścieżka listy modeli instancji (K13 §3 p. 7)."""
    return f"/api/v1/providers/{PROVIDER}/instances/{instance}/models"


def _extra(value: object) -> dict[str, object]:
    """Ciało POST/PATCH z `max_concurrency` ustawionym na ``value``."""
    return {"max_concurrency": value}


def _body(response: httpx.Response) -> dict[str, Any]:
    """Koperta ragflow z odpowiedzi HTTP 200 (K13 §2)."""
    assert response.status_code == OK
    return cast(dict[str, Any], response.json())


async def _make_instance(container: Container, name: str = INSTANCE) -> str:
    """Zakłada instancję przez repozytorium (wzór: test_instance_models)."""
    instance_id = uuid.uuid4().hex
    sessionmaker = cast(SM, container.sessionmaker)
    async with transaction(sessionmaker) as session:
        await provider_instances_repo.insert(
            session,
            id=instance_id,
            provider=PROVIDER,
            name=name,
            base_url=GW_URL,
            api_key_enc=None,
            created_by=None,
            now_ms=container.clock.now_ms(),
        )
    return instance_id


async def _rows(sm: SM, instance_id: str | None) -> list[ModelRow]:
    """Wiersze rejestru instancji (None = `instance_id IS NULL`)."""
    async with transaction(sm) as session:
        return await models_repo.list_by_instance(session, instance_id)


async def _post(
    admin: httpx.AsyncClient, instance: str, payload: Mapping[str, Any]
) -> dict[str, Any]:
    """POST modelu do instancji; zwraca kopertę odpowiedzi (K13 §3 p. 8)."""
    return _body(await admin.post(_models(instance), json=dict(payload)))


def _model(name: str = "m-a") -> dict[str, Any]:
    """Ciało POST modelu czatu (typ domyślny w testach)."""
    return {"model_name": name, "model_type": "chat"}


@pytest.mark.parametrize("value", INVALID)
async def test_post_rejects_invalid_max_concurrency(
    admin: httpx.AsyncClient, container: Container, sm: SM, value: object
):
    """POST: `max_concurrency` spoza int 1-32 → 101 z komunikatem dosłownym (K13 p. 1)."""
    instance_id = await _make_instance(container)
    body = await _post(admin, INSTANCE, {**_model(), "extra": _extra(value)})
    assert body["code"] == ARGUMENT_ERROR
    assert body["message"] == MESSAGE
    assert await _rows(sm, instance_id) == []  # odrzucone przed zapisem


@pytest.mark.parametrize("value", INVALID)
async def test_patch_rejects_invalid_max_concurrency(
    admin: httpx.AsyncClient, container: Container, sm: SM, value: object
):
    """PATCH: `max_concurrency` spoza int 1-32 → 101 z komunikatem dosłownym (K13 p. 1)."""
    instance_id = await _make_instance(container)
    assert (await _post(admin, INSTANCE, _model()))["code"] == 0
    body = _body(await admin.patch(f"{_models(INSTANCE)}/m-a", json={"extra": _extra(value)}))
    assert body["code"] == ARGUMENT_ERROR
    assert body["message"] == MESSAGE
    assert (await _rows(sm, instance_id))[0].extra is None  # nic nie zapisano


@pytest.mark.parametrize("value", VALID)
async def test_post_accepts_valid_max_concurrency(
    admin: httpx.AsyncClient, container: Container, sm: SM, value: int
):
    """POST: `max_concurrency` ∈ 1..32 → sukces i zapis klucza (K13 p. 1)."""
    instance_id = await _make_instance(container)
    body = await _post(admin, INSTANCE, {**_model(), "extra": _extra(value)})
    assert body["code"] == 0
    assert (await _rows(sm, instance_id))[0].extra == {"max_concurrency": value}


async def test_post_without_key_succeeds(admin: httpx.AsyncClient, container: Container, sm: SM):
    """POST: brak klucza `max_concurrency` → bez walidacji (K13 p. 1)."""
    instance_id = await _make_instance(container)
    body = await _post(admin, INSTANCE, {**_model(), "extra": {"vision": False}})
    assert body["code"] == 0
    assert (await _rows(sm, instance_id))[0].extra == {"vision": False}


async def test_patch_without_extra_succeeds(admin: httpx.AsyncClient, container: Container, sm: SM):
    """PATCH bez `extra` → bez walidacji (K13 p. 1)."""
    instance_id = await _make_instance(container)
    assert (await _post(admin, INSTANCE, {**_model(), "extra": _extra(8)}))["code"] == 0
    body = _body(await admin.patch(f"{_models(INSTANCE)}/m-a", json={"max_tokens": 128}))
    assert body["code"] == 0
    assert (await _rows(sm, instance_id))[0].extra == {"max_concurrency": 8}


async def test_patch_extra_replaces_whole_object_and_keeps_other_keys(
    admin: httpx.AsyncClient, container: Container, sm: SM
):
    """PATCH `extra` zastępuje cały obiekt, zachowując klucze przekazane razem (K13 p. 1)."""
    instance_id = await _make_instance(container)
    initial = {**_model(), "extra": {"supports_reasoning": True, "extra_body": {"x": 1}}}
    assert (await _post(admin, INSTANCE, initial))["code"] == 0
    patched = {"max_concurrency": 8, "supports_reasoning": True, "extra_body": {"x": 1}}
    body = _body(await admin.patch(f"{_models(INSTANCE)}/m-a", json={"extra": patched}))
    assert body["code"] == 0
    assert (await _rows(sm, instance_id))[0].extra == patched


async def test_patch_valid_max_concurrency_accepted(
    admin: httpx.AsyncClient, container: Container, sm: SM
):
    """PATCH: `max_concurrency` ∈ 1..32 → sukces i zapis (K13 p. 1)."""
    instance_id = await _make_instance(container)
    assert (await _post(admin, INSTANCE, _model()))["code"] == 0
    body = _body(await admin.patch(f"{_models(INSTANCE)}/m-a", json={"extra": _extra(32)}))
    assert body["code"] == 0
    assert (await _rows(sm, instance_id))[0].extra == {"max_concurrency": 32}
