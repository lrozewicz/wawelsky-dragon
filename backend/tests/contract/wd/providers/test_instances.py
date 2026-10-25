"""Trasy instancji dostawców ``/api/v1/providers/{name}/instances*`` (K13 §3 p. 1-6, §4 p. 1-4, 9).

Zakres: CRUD i ``/connection`` na stosie testowym (MariaDB + fake-llm). Asercje obejmują
kształty ``ProviderInstance``/``ProviderInstanceDetail``, komunikaty reguł, audyt bez klucza,
brak plaintextu klucza w każdej odpowiedzi oraz odmowę nie-superusera na każdej trasie zapisu.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.ragflow.routes.models import instance_id
from app.core.config import Settings
from app.db.repositories import models as models_repo
from app.db.repositories import provider_instances as instances_repo
from app.db.uow import transaction
from tests.contract.wd.admin_support import ADMIN_EMAIL
from tests.integration.integrations.conftest import seed_dataset_and_user

pytestmark = pytest.mark.contract

OK = 200
ARG_ERROR = 101
DATA_ERROR = 102
PERMISSION_ERROR = 108
PROVIDER = "OpenAI-API-Compatible"
COLUMN = "litellm"
BASE = f"/api/v1/providers/{PROVIDER}/instances"
CONNECTION = f"/api/v1/providers/{PROVIDER}/connection"
NOW = 1_790_157_600_000
SECRET = "sekret-1"  # noqa: S105 — klucz wyłącznie testowy
CONNECT_SECRET = "sekret-2"  # noqa: S105 — klucz wyłącznie testowy
MASK = "********"
DEFAULT_MANAGED = "Instance 'default' is managed by environment configuration"

AuditRows = Callable[[str], Awaitable[list[Any]]]

_CREATED = {"code": 0, "message": "success"}


def _create_body(
    name: str, base_url: str = "http://llm.local/v1", **over: object
) -> dict[str, Any]:
    """Poprawne ciało ``POST …/instances`` (K13 §3 p. 2)."""
    return {"instance_name": name, "base_url": base_url, **over}


async def _create(
    admin: httpx.AsyncClient, name: str, base_url: str = "http://llm.local/v1", **over: object
) -> httpx.Response:
    """Tworzy instancję i zakłada sukces (pomocnik większości testów)."""
    response = await admin.post(BASE, json=_create_body(name, base_url, **over))
    assert response.json() == _CREATED, response.text
    return response


async def _row_id(sm: async_sessionmaker[AsyncSession], name: str) -> str:
    """Id wiersza instancji o nazwie (K13 §1 — kolumna ``litellm``)."""
    async with transaction(sm) as session:
        row = await instances_repo.get_by_name(session, COLUMN, name)
    assert row is not None
    return row.id


async def _insert_instance(
    sm: async_sessionmaker[AsyncSession], *, instance_id_: str, name: str, now_ms: int
) -> None:
    """Wstawia wiersz instancji z zegarem wołającego (kolejność ``create_time DESC``)."""
    async with transaction(sm) as session:
        await instances_repo.insert(
            session,
            id=instance_id_,
            provider=COLUMN,
            name=name,
            base_url="http://llm.local/v1",
            api_key_enc=None,
            created_by=None,
            now_ms=now_ms,
        )


async def _clear_models(sm: async_sessionmaker[AsyncSession]) -> None:
    """Czyści rejestr modeli — kontener testowy seeduje 2 modele (WYROCZNIA testowa)."""
    async with transaction(sm) as session:
        await session.execute(text("DELETE FROM models"))


async def _insert_model(  # noqa: PLR0913 — pomocnik testowy z domyślnymi wartościami
    sm: async_sessionmaker[AsyncSession],
    *,
    model_id: str,
    name: str,
    model_type: str,
    instance_id_: str | None,
    is_default: bool = False,
) -> None:
    """Wstawia model instancji (``base_url``/klucz NULL) opcjonalnie jako domyślny."""
    async with transaction(sm) as session:
        await models_repo.insert_for_instance(
            session,
            id=model_id,
            name=name,
            model_type=model_type,
            instance_id=instance_id_,
            max_tokens=8192,
            dimension=None,
            extra=None,
            created_by=None,
            now_ms=NOW,
        )
        if is_default:
            await session.execute(
                text("UPDATE models SET is_default = 1 WHERE id = :id"), {"id": model_id}
            )


# --- create (K13 §4 p. 1) --------------------------------------------------------


async def test_create_normalizes_base_url(
    admin: httpx.AsyncClient, sm: async_sessionmaker[AsyncSession]
) -> None:
    """POST zapisuje ``base_url`` bez końcowego ``/`` i szyfruje klucz (K13 §2)."""
    response = await admin.post(
        BASE, json=_create_body("gw1", "http://fake-llm:9/v1/", api_key=SECRET)
    )

    assert response.status_code == OK, response.text
    assert response.json() == _CREATED
    async with transaction(sm) as session:
        row = await instances_repo.get_by_name(session, COLUMN, "gw1")
    assert row is not None
    assert row.base_url == "http://fake-llm:9/v1"
    assert row.api_key_enc is not None
    assert SECRET.encode() not in row.api_key_enc


async def test_create_writes_audit_without_the_key(
    admin: httpx.AsyncClient, audit_rows: AuditRows
) -> None:
    """Audyt ``provider_instance_created``: ``target_type``, ``details`` bez klucza (K13 §2)."""
    await _create(admin, "gw1", api_key=SECRET)

    rows = await audit_rows("provider_instance_created")

    assert len(rows) == 1
    entry = rows[0]
    assert entry.target_type == "provider_instance"
    assert entry.actor_label == ADMIN_EMAIL
    assert entry.details == {"name": "gw1", "provider": COLUMN}
    assert SECRET not in json.dumps(entry.details)


async def test_create_rejects_duplicate_and_default_name(admin: httpx.AsyncClient) -> None:
    """Nazwa istniejąca lub ``default`` (dowolna wielkość liter) → 102 (K13 §4 p. 1)."""
    await _create(admin, "gw1")

    response = await admin.post(BASE, json=_create_body("gw1"))
    assert response.json()["code"] == DATA_ERROR
    assert response.json()["message"] == "Instance 'gw1' already exists"

    response = await admin.post(BASE, json=_create_body("DEFAULT"))
    assert response.json()["code"] == DATA_ERROR
    assert response.json()["message"] == "Instance 'DEFAULT' already exists"


async def test_create_race_maps_to_data_error(
    admin: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wyścig między sprawdzeniem nazwy a INSERT-em (unikalny klucz) → 102 (K13 §4 p. 1)."""
    await _create(admin, "gw")

    async def _no_duplicate(session: Any, provider: str, name: str) -> None:
        return None

    monkeypatch.setattr(instances_repo, "get_by_name", _no_duplicate)
    response = await admin.post(BASE, json=_create_body("gw"))

    assert response.json()["code"] == DATA_ERROR
    assert response.json()["message"] == "Instance 'gw' already exists"


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"base_url": "http://llm.local/v1"}, "instance_name is required"),
        ({"instance_name": "x"}, "base_url is required"),
        ({"instance_name": "x", "base_url": ""}, "base_url is required"),
        ({"instance_name": "x", "base_url": "ftp://x"}, "base_url must be an http(s) URL"),
    ],
)
async def test_create_validates_body(
    admin: httpx.AsyncClient, body: dict[str, Any], message: str
) -> None:
    """Błędy argumentów ciała → 101 z komunikatem kontraktu (K13 §4 p. 1)."""
    response = await admin.post(BASE, json=body)

    assert response.status_code == OK
    assert response.json()["code"] == ARG_ERROR
    assert response.json()["message"] == message


# --- get (K13 §3 p. 3, §4 p. 9) --------------------------------------------------


async def test_get_instance_masks_api_key(
    admin: httpx.AsyncClient, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Szczegóły instancji tabeli: maska zamiast klucza, ``wd_managed`` false (K13 §3)."""
    await _create(admin, "gw1", api_key=SECRET)

    response = await admin.get(f"{BASE}/gw1")

    assert response.status_code == OK
    data = response.json()["data"]
    assert set(data) == {
        "id",
        "instance_name",
        "provider_id",
        "region",
        "base_url",
        "api_key",
        "status",
        "wd_managed",
    }
    assert data["id"] == await _row_id(sm, "gw1")
    assert data["instance_name"] == "gw1"
    assert data["base_url"] == "http://llm.local/v1"
    assert data["api_key"] == MASK
    assert data["wd_managed"] is False
    assert data["region"] == "default"
    assert data["status"] == "active"
    assert SECRET not in response.text


async def test_get_instance_by_id(
    admin: httpx.AsyncClient, sm: async_sessionmaker[AsyncSession]
) -> None:
    """``{instance}`` przyjmuje id wiersza (K13 §2)."""
    await _create(admin, "gw1")

    response = await admin.get(f"{BASE}/{await _row_id(sm, 'gw1')}")

    assert response.json()["data"]["instance_name"] == "gw1"


async def test_get_default_instance_is_managed(
    admin: httpx.AsyncClient, settings: Settings
) -> None:
    """Instancja ``default``: ``wd_managed`` true i ``base_url`` ze środowiska (K13 §3)."""
    response = await admin.get(f"{BASE}/default")

    data = response.json()["data"]
    assert data["instance_name"] == "default"
    assert data["wd_managed"] is True
    assert data["base_url"] == settings.llm_base_url
    assert data["api_key"] in ("", MASK)
    secret = settings.llm_api_key.get_secret_value()
    if secret:
        assert secret not in response.text


async def test_get_instance_of_other_provider_is_102(
    admin: httpx.AsyncClient, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Id wiersza innego dostawcy nie jest instancją ``litellm`` (K13 §2)."""
    async with transaction(sm) as session:
        await instances_repo.insert(
            session,
            id="f" * 32,
            provider="other",
            name="gw-other",
            base_url="http://other.local/v1",
            api_key_enc=None,
            created_by=None,
            now_ms=NOW,
        )

    response = await admin.get(f"{BASE}/{'f' * 32}")

    assert response.json()["code"] == DATA_ERROR
    assert response.json()["message"].startswith("No instance found for provider")


async def test_get_unknown_instance_is_102(admin: httpx.AsyncClient) -> None:
    """Brak instancji → 102 ``No instance found …`` z nazwą z ścieżki (K13 §2)."""
    response = await admin.get(f"{BASE}/nope")

    assert response.json()["code"] == DATA_ERROR
    assert (
        response.json()["message"]
        == f"No instance found for provider '{PROVIDER}' and instance 'nope'"
    )


# --- list (K13 §3 p. 1, §0 p. 2) -------------------------------------------------


async def test_list_has_default_first_then_newest(
    admin: httpx.AsyncClient, sm: async_sessionmaker[AsyncSession]
) -> None:
    """``default`` pierwsza (id jak grupa modeli), potem wiersze wg ``create_time`` malejąco."""
    await _insert_instance(sm, instance_id_="a" * 32, name="starsza", now_ms=NOW)
    await _insert_instance(sm, instance_id_="b" * 32, name="nowsza", now_ms=NOW + 1000)

    response = await admin.get(BASE)

    data = response.json()["data"]
    assert [entry["instance_name"] for entry in data] == ["default", "nowsza", "starsza"]
    assert data[0]["id"] == instance_id(COLUMN, None)
    assert [entry["region"] for entry in data] == ["default", "default", "default"]
    assert [entry["status"] for entry in data] == ["active", "active", "active"]
    assert {entry["provider_id"] for entry in data} == {data[0]["provider_id"]}


# --- update (K13 §4 p. 2) --------------------------------------------------------


async def test_update_key_semantics(admin: httpx.AsyncClient) -> None:
    """PUT klucza: brak → bez zmian, ``""`` → usunięty, maska → bez zmian, inny → nowy."""
    await _create(admin, "gw", api_key=SECRET)

    async def key() -> str:
        response = await admin.get(f"{BASE}/gw")
        value: str = response.json()["data"]["api_key"]
        return value

    response = await admin.put(f"{BASE}/gw", json=_create_body("gw", "http://y.local/v1"))
    assert response.json() == _CREATED
    assert await key() == MASK

    await admin.put(f"{BASE}/gw", json=_create_body("gw", "http://y.local/v1", api_key=""))
    assert await key() == ""

    await admin.put(f"{BASE}/gw", json=_create_body("gw", "http://y.local/v1", api_key=MASK))
    assert await key() == ""

    await admin.put(f"{BASE}/gw", json=_create_body("gw", "http://y.local/v1", api_key="nowy"))
    assert await key() == MASK
    detail = (await admin.get(f"{BASE}/gw")).json()["data"]
    assert detail["base_url"] == "http://y.local/v1"


async def test_update_and_delete_write_audit(
    admin: httpx.AsyncClient, audit_rows: AuditRows
) -> None:
    """Akcje ``provider_instance_updated``/``_deleted`` z ``details`` bez klucza (K13 §2)."""
    await _create(admin, "gw")
    await admin.put(f"{BASE}/gw", json=_create_body("gw2"))
    await admin.request("DELETE", BASE, json={"instances": ["gw2"]})

    updated = await audit_rows("provider_instance_updated")
    deleted = await audit_rows("provider_instance_deleted")

    assert [entry.details for entry in updated] == [{"name": "gw2", "provider": COLUMN}]
    assert [entry.details for entry in deleted] == [{"name": "gw2", "provider": COLUMN}]
    assert all(entry.target_type == "provider_instance" for entry in (*updated, *deleted))


async def test_update_validates_and_guards_default(admin: httpx.AsyncClient) -> None:
    """PUT: brakujące pola → 101, ``default`` → 102, nieznana instancja → 102 (K13 §4 p. 2)."""
    await _create(admin, "gw1")
    await _create(admin, "gw2")

    response = await admin.put(f"{BASE}/gw1", json={"instance_name": "gw1"})
    assert response.json()["code"] == ARG_ERROR
    assert response.json()["message"] == "Missing required fields: base_url"

    response = await admin.put(f"{BASE}/gw1", json={"base_url": "http://llm.local/v1"})
    assert response.json()["code"] == ARG_ERROR
    assert response.json()["message"] == "Missing required fields: instance_name"

    response = await admin.put(
        f"{BASE}/gw1", json=_create_body("gw1", "http://llm.local/v1", api_key=123)
    )
    assert response.json()["code"] == ARG_ERROR
    assert response.json()["message"] == "api_key must be a string"

    response = await admin.put(
        f"{BASE}/default", json=_create_body("default", "http://llm.local/v1")
    )
    assert response.json()["code"] == DATA_ERROR
    assert response.json()["message"] == DEFAULT_MANAGED

    response = await admin.put(f"{BASE}/gw1", json=_create_body("DEFAULT"))
    assert response.json()["code"] == DATA_ERROR
    assert response.json()["message"] == "Instance 'DEFAULT' already exists"

    response = await admin.put(f"{BASE}/gw1", json=_create_body("gw2"))
    assert response.json()["message"] == "Instance 'gw2' already exists"

    response = await admin.put(f"{BASE}/nope", json=_create_body("x"))
    assert response.json()["code"] == DATA_ERROR
    assert (
        response.json()["message"]
        == f"No instance found for provider '{PROVIDER}' and instance 'nope'"
    )


async def test_update_allows_case_only_rename(admin: httpx.AsyncClient) -> None:
    """Zmiana tylko wielkości liter własnej nazwy nie jest konfliktem (K13 §4 p. 2)."""
    await _create(admin, "gw1")

    response = await admin.put(f"{BASE}/gw1", json=_create_body("GW1"))

    assert response.json() == _CREATED


# --- delete (K13 §4 p. 3) --------------------------------------------------------


async def test_delete_removes_instance_with_its_models(
    admin: httpx.AsyncClient, sm: async_sessionmaker[AsyncSession]
) -> None:
    """DELETE usuwa instancję i jej modele w jednej transakcji (K13 §4 p. 3)."""
    await _create(admin, "gw")
    instance = await _row_id(sm, "gw")
    await _insert_model(
        sm, model_id="1" * 32, name="m-chat", model_type="chat", instance_id_=instance
    )

    response = await admin.request("DELETE", BASE, json={"instances": ["gw"]})

    assert response.json() == _CREATED
    async with transaction(sm) as session:
        assert await instances_repo.get_by_id(session, instance) is None
        assert await models_repo.list_by_instance(session, instance) == []


async def test_delete_blocked_by_default_model(
    admin: httpx.AsyncClient, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Model ``is_default = 1`` blokuje DELETE i nic nie jest usuwane (K13 §4 p. 3/8)."""
    await _create(admin, "gw")
    instance = await _row_id(sm, "gw")
    await _insert_model(
        sm,
        model_id="2" * 32,
        name="m-rerank",
        model_type="rerank",
        instance_id_=instance,
        is_default=True,
    )

    response = await admin.request("DELETE", BASE, json={"instances": ["gw"]})

    assert response.json()["code"] == DATA_ERROR
    assert response.json()["message"] == (
        "Model 'm-rerank' is a default model; set another default model first"
        " (PUT /api/v1/system/models/default or Settings → Models) and retry"
    )
    async with transaction(sm) as session:
        assert await instances_repo.get_by_id(session, instance) is not None
        assert len(await models_repo.list_by_instance(session, instance)) == 1


async def test_delete_blocked_by_dataset_usage(
    admin: httpx.AsyncClient, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Embedding wskazany przez dataset blokuje DELETE i nic nie jest usuwane (K13 §4 p. 3/8)."""
    await _create(admin, "gw")
    instance = await _row_id(sm, "gw")
    await _insert_model(
        sm, model_id="3" * 32, name="m-embed", model_type="embedding", instance_id_=instance
    )
    _, dataset_id = await seed_dataset_and_user(sm)
    async with transaction(sm) as session:
        await session.execute(
            text("UPDATE datasets SET embedding_model = :name WHERE id = :id"),
            {"name": "m-embed", "id": dataset_id},
        )

    response = await admin.request("DELETE", BASE, json={"instances": ["gw"]})

    assert response.json()["code"] == DATA_ERROR
    assert response.json()["message"] == "Model 'm-embed' is used by 1 dataset(s)"
    async with transaction(sm) as session:
        assert await instances_repo.get_by_id(session, instance) is not None


@pytest.mark.parametrize("body", [{}, {"instances": []}, {"instances": [""]}])
async def test_delete_requires_instances(admin: httpx.AsyncClient, body: dict[str, Any]) -> None:
    """Brak/pusta lista ``instances`` → 101 (K13 §4 p. 3)."""
    response = await admin.request("DELETE", BASE, json=body)

    assert response.json()["code"] == ARG_ERROR
    assert response.json()["message"] == "instances is required"


async def test_delete_many_with_and_without_models(
    admin: httpx.AsyncClient, sm: async_sessionmaker[AsyncSession]
) -> None:
    """DELETE wielu instancji: każda kasuje swoje modele (także brak modeli) (K13 §4 p. 3)."""
    await _create(admin, "gw1")
    await _create(admin, "gw2")
    instance = await _row_id(sm, "gw1")
    await _insert_model(
        sm, model_id="4" * 32, name="m-chat", model_type="chat", instance_id_=instance
    )

    response = await admin.request("DELETE", BASE, json={"instances": ["gw1", "gw2"]})

    assert response.json() == _CREATED
    async with transaction(sm) as session:
        assert await instances_repo.list_by_provider(session, COLUMN) == []
        assert await models_repo.list_by_instance(session, instance) == []


async def test_delete_deduplicates_repeated_names(
    admin: httpx.AsyncClient, audit_rows: AuditRows
) -> None:
    """Powtórzona nazwa w ``instances`` = jedno usunięcie i jeden wpis audytu (K13 §4 p. 3)."""
    await _create(admin, "gw")

    response = await admin.request("DELETE", BASE, json={"instances": ["gw", "gw"]})

    assert response.json() == _CREATED
    deleted = await audit_rows("provider_instance_deleted")
    assert [entry.details["name"] for entry in deleted] == ["gw"]


async def test_delete_default_is_managed(admin: httpx.AsyncClient) -> None:
    """``default`` na liście → 102 jak w p. 2 (K13 §4 p. 3)."""
    response = await admin.request("DELETE", BASE, json={"instances": ["default"]})

    assert response.json()["code"] == DATA_ERROR
    assert response.json()["message"] == DEFAULT_MANAGED


# --- katalog: dostawca litellm i instancje w odczytach (K13 §0 p. 3, §4 p. 9) ----


async def test_litellm_exists_with_empty_registry(
    admin: httpx.AsyncClient, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Pusty rejestr: ``litellm`` nadal istnieje, ``has_instance=false`` (K13 §0 p. 3)."""
    await _clear_models(sm)

    providers = (await admin.get("/api/v1/providers")).json()["data"]

    assert [entry["name"] for entry in providers] == [PROVIDER]
    assert providers[0]["has_instance"] is False
    assert providers[0]["url"]["default"] == ""

    detail = (await admin.get(f"/api/v1/providers/{PROVIDER}")).json()["data"]
    assert detail["name"] == PROVIDER
    assert detail["total_models"] == 0

    instances = (await admin.get(BASE)).json()["data"]
    assert [entry["instance_name"] for entry in instances] == ["default"]


async def test_has_instance_tracks_models_and_instances(
    admin: httpx.AsyncClient, sm: async_sessionmaker[AsyncSession]
) -> None:
    """``has_instance=true``: model bez instancji albo instancja tabeli (K13 §0 p. 3)."""
    await _clear_models(sm)
    assert (await admin.get("/api/v1/providers")).json()["data"][0]["has_instance"] is False

    await _insert_model(sm, model_id="d" * 32, name="m-def", model_type="chat", instance_id_=None)
    assert (await admin.get("/api/v1/providers")).json()["data"][0]["has_instance"] is True

    await _clear_models(sm)
    await _insert_instance(sm, instance_id_="a" * 32, name="gw1", now_ms=NOW)
    assert (await admin.get("/api/v1/providers")).json()["data"][0]["has_instance"] is True


async def test_unknown_provider_is_102(admin: httpx.AsyncClient) -> None:
    """Inny dostawca → 102 ``Provider <name> not found`` (K13 §0 p. 3)."""
    response = await admin.get("/api/v1/providers/openai/instances")

    assert response.json()["code"] == DATA_ERROR
    assert response.json()["message"] == "Provider openai not found"


async def test_models_report_table_instance(
    admin: httpx.AsyncClient, sm: async_sessionmaker[AsyncSession]
) -> None:
    """``/models``: model instancji tabeli ma jej id/nazwę, ``default`` bez zmian (K13 §4 p. 9)."""
    await _create(admin, "gw")
    instance = await _row_id(sm, "gw")
    await _insert_model(
        sm, model_id="1" * 32, name="m-tab", model_type="chat", instance_id_=instance
    )
    await _insert_model(sm, model_id="2" * 32, name="m-def", model_type="chat", instance_id_=None)

    entries = {entry["name"]: entry for entry in (await admin.get("/api/v1/models")).json()["data"]}

    assert entries["m-tab"]["instance_id"] == instance
    assert entries["m-tab"]["instance_name"] == "gw"
    assert entries["m-def"]["instance_id"] == instance_id(COLUMN, None)
    assert entries["m-def"]["instance_name"] == "default"


async def test_models_default_report_table_instance(
    admin: httpx.AsyncClient, sm: async_sessionmaker[AsyncSession]
) -> None:
    """``/models/default``: ``model_instance`` = nazwa instancji tabeli (K13 §4 p. 9)."""
    await _create(admin, "gw")
    instance = await _row_id(sm, "gw")
    await _insert_model(
        sm,
        model_id="5" * 32,
        name="m-rerank",
        model_type="rerank",
        instance_id_=instance,
        is_default=True,
    )

    data = (await admin.get("/api/v1/models/default")).json()["data"]
    entries = {entry["model_type"]: entry for entry in data["models"]}

    assert entries["rerank"]["model_name"] == "m-rerank"
    assert entries["rerank"]["model_instance"] == "gw"


# --- /connection (K13 §4 p. 4) ---------------------------------------------------


async def test_connection_succeeds_against_fake_llm(
    admin: httpx.AsyncClient, settings: Settings
) -> None:
    """``GET {base_url}/models`` bramki fake-llm → sukces (K13 §4 p. 4)."""
    response = await admin.post(CONNECTION, json={"base_url": settings.llm_base_url})

    assert response.status_code == OK
    assert response.json() == _CREATED


async def test_connection_uses_stored_instance(
    admin: httpx.AsyncClient, settings: Settings
) -> None:
    """``instance_id`` dostarcza ``base_url`` zapisanej instancji (K13 §4 p. 4)."""
    await _create(admin, "gw", settings.llm_base_url)

    response = await admin.post(CONNECTION, json={"instance_id": "gw"})

    assert response.json() == _CREATED


async def test_connection_uses_environment_default(
    admin: httpx.AsyncClient, settings: Settings
) -> None:
    """``instance_id=default`` bierze ``base_url`` ze środowiska (K13 §4 p. 4)."""
    response = await admin.post(CONNECTION, json={"instance_id": "default"})

    assert response.json() == _CREATED


async def test_connection_body_overrides_stored_instance(
    admin: httpx.AsyncClient, settings: Settings
) -> None:
    """Pola ciała mają pierwszeństwo przed zapisaną instancją (K13 §4 p. 4)."""
    await _create(admin, "gw", "http://127.0.0.1:1/v1")

    response = await admin.post(
        CONNECTION,
        json={"instance_id": "gw", "base_url": settings.llm_base_url, "api_key": "klucz-jawny"},
    )

    assert response.json() == _CREATED


async def test_connection_failure_hides_the_key(admin: httpx.AsyncClient) -> None:
    """Porażka sondy → 102 ``Connection failed: …`` bez klucza w komunikacie (K13 §4 p. 4)."""
    response = await admin.post(
        CONNECTION, json={"base_url": "http://127.0.0.1:1/v1", "api_key": CONNECT_SECRET}
    )

    assert response.status_code == OK
    assert response.json()["code"] == DATA_ERROR
    assert response.json()["message"].startswith("Connection failed: ")
    assert CONNECT_SECRET not in response.text


async def test_connection_requires_base_url(admin: httpx.AsyncClient) -> None:
    """Bez ``instance_id`` i bez ``base_url`` → 101 (K13 §4 p. 4)."""
    response = await admin.post(CONNECTION, json={"api_key": "sekret"})

    assert response.json()["code"] == ARG_ERROR
    assert response.json()["message"] == "base_url is required"


async def test_connection_persists_nothing(
    admin: httpx.AsyncClient,
    audit_rows: AuditRows,
    sm: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    """``/connection`` nie zapisuje instancji ani audytu (K13 §4 p. 4)."""
    await admin.post(CONNECTION, json={"base_url": settings.llm_base_url})

    async with transaction(sm) as session:
        assert await instances_repo.list_by_provider(session, COLUMN) == []
    assert await audit_rows("provider_instance_created") == []


# --- strażnik zapisu (K13 §2) ----------------------------------------------------

_WRITE_ROUTES = [
    ("post", BASE, _create_body("gw1")),
    ("put", f"{BASE}/gw1", _create_body("gw1")),
    ("delete", BASE, {"instances": ["gw1"]}),
    ("post", CONNECTION, {"base_url": "http://llm.local/v1"}),
]


@pytest.mark.parametrize(("method", "path", "body"), _WRITE_ROUTES)
async def test_member_cannot_write(
    member: httpx.AsyncClient, method: str, path: str, body: dict[str, Any]
) -> None:
    """Nie-superuser na każdej trasie zapisu → 108 ``No authorization.`` (K13 §2)."""
    response = await member.request(method, path, json=body)

    assert response.status_code == OK
    assert response.json()["code"] == PERMISSION_ERROR
    assert response.json()["message"] == "No authorization."


async def test_member_can_read(member: httpx.AsyncClient) -> None:
    """Odczyt instancji dla każdego zalogowanego (K13 §2)."""
    response = await member.get(BASE)

    assert response.status_code == OK
    assert response.json()["code"] == 0
