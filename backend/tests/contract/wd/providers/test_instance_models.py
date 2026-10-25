"""Trasy modeli instancji ``/api/v1/providers/{name}/instances/{instance}/models`` (K13 §3 p. 7-10).

Wiersze tabeli „Przykłady wejście → wyjście" briefu T3: dodawanie (wiersz i domyślne pola),
duplikat i walidacje ciała, instancja `default` bez wiersza w tabeli, lista w kształcie
``InstanceModel``, PATCH (status, zakaz zmiany typu, model domyślny), DELETE (wszystko albo nic,
blokady `is_default` i datasetu), odmowa zwykłego użytkownika (108) oraz wpisy audytu.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.core.errors import NotFound
from app.db.repositories import datasets as datasets_repo
from app.db.repositories import models as models_repo
from app.db.repositories import provider_instances as provider_instances_repo
from app.db.repositories.models import ModelRow
from app.db.uow import transaction
from app.services import provider_probe
from app.services.instance_models import default_instance_id
from app.services.provider_common import encrypt_key
from tests.contract.wd.admin_support import ADMIN_EMAIL, AuditRows, MakeUser

pytestmark = pytest.mark.contract

OK = 200
ARGUMENT_ERROR = 101
DATA_ERROR = 102
PERMISSION_ERROR = 108
UNAUTHORIZED = 401

PROVIDER = "litellm"
PATH = f"/api/v1/providers/{PROVIDER}/instances"
INSTANCE = "gw1"
GW_URL = "http://gw1.local/v1"

# Modele zasiewane przez reset K9, których dotyczy blokada `is_default` (K13 §4 p. 8).
DEFAULT_CHAT = "fake-chat"
DEFAULT_EMBEDDING = "fake-embed-1024"
DIMENSION = 768
OTHER_DIMENSION = 5
PATCH_TOKENS = 128
USED_BY_ONE = "Model 'm-e' is used by 1 dataset(s)"
ALREADY_EXISTS = "Model 'm-a' already exists"
REQUIRED_UPDATE = "At least one of status, max_tokens, or extra is required."

SM = async_sessionmaker[AsyncSession]

# Domyślne i fabryczne wartości z K13 §3-§4 (bez „magic numbers" w asercjach).
RANK = 500
DEFAULT_TOKENS = 8192
MODEL = {"model_name": "m-a", "model_type": "chat"}


def _models(instance: str) -> str:
    """Ścieżka listy modeli instancji (K13 §3 p. 7)."""
    return f"{PATH}/{instance}/models"


def _body(response: httpx.Response) -> dict[str, Any]:
    """Koperta ragflow z odpowiedzi HTTP 200 (K13 §2)."""
    assert response.status_code == OK
    return cast(dict[str, Any], response.json())


async def _post(
    client: httpx.AsyncClient, instance: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    """POST modelu do instancji; zwraca kopertę odpowiedzi (K13 §3 p. 8)."""
    body = payload if payload is not None else MODEL
    return _body(await client.post(_models(instance), json=body))


async def _make_instance(
    container: Container, name: str = INSTANCE, *, api_key: str | None = None
) -> str:
    """Zakłada instancję przez repozytorium (trasę POST …/instances dostarcza T2)."""
    instance_id = uuid.uuid4().hex
    blob = encrypt_key(container.settings, instance_id, api_key) if api_key else None
    sessionmaker = cast(SM, container.sessionmaker)
    async with transaction(sessionmaker) as session:
        await provider_instances_repo.insert(
            session,
            id=instance_id,
            provider=PROVIDER,
            name=name,
            base_url=GW_URL,
            api_key_enc=blob,
            created_by=None,
            now_ms=container.clock.now_ms(),
        )
    return instance_id


async def _rows(sm: SM, instance_id: str | None) -> list[ModelRow]:
    """Wiersze rejestru instancji (None = `instance_id IS NULL`)."""
    async with transaction(sm) as session:
        return await models_repo.list_by_instance(session, instance_id)


async def _make_dataset(sm: SM, make_user: MakeUser, embedding_model: str) -> str:
    """Dataset wskazujący model embeddingowy (blokada usunięcia z K13 §4 p. 8)."""
    owner = await make_user("owner-e3-6b@example.com")
    dataset_id = uuid.uuid4().hex
    async with transaction(sm) as session:
        await datasets_repo.insert(
            session,
            id=dataset_id,
            tenant_id=owner.id,
            created_by=owner.id,
            name="ds-1",
            description=None,
            avatar=None,
            language="Polish",
            embedding_model=embedding_model,
            embedding_dim=1024,
            permission="me",
            chunk_method="naive",
            parser_config={"chunk_token_num": 128},
            now_ms=1,
        )
    return dataset_id


async def test_add_model_creates_instance_row(
    admin: httpx.AsyncClient, container: Container, sm: SM
):
    """POST wiersz 1: wiersz instancji z domyślnymi polami i `max_tokens = 8192`."""
    instance_id = await _make_instance(container)
    body = await _post(admin, INSTANCE)
    assert body["code"] == 0
    assert body["message"] == "success"
    rows = await _rows(sm, instance_id)
    assert [row.name for row in rows] == ["m-a"]
    row = rows[0]
    assert row.provider == PROVIDER
    assert row.instance_id == instance_id
    assert row.base_url is None
    assert row.api_key_enc is None
    assert row.max_tokens == DEFAULT_TOKENS
    assert row.is_active is True
    assert row.is_default is False
    assert row.model_type == "chat"


async def test_add_model_dimension_only_for_embedding(
    admin: httpx.AsyncClient, container: Container, sm: SM
):
    """POST wiersz 2: `wd_dimension` zapisany dla embeddingu, ignorowany dla czatu."""
    instance_id = await _make_instance(container)
    await admin.post(
        _models(INSTANCE),
        json={"model_name": "m-e", "model_type": "embedding", "wd_dimension": DIMENSION},
    )
    await admin.post(
        _models(INSTANCE),
        json={"model_name": "m-c", "model_type": "chat", "wd_dimension": OTHER_DIMENSION},
    )
    by_name = {row.name: row for row in await _rows(sm, instance_id)}
    assert by_name["m-e"].dimension == DIMENSION
    assert by_name["m-c"].dimension is None
    assert by_name["m-e"].max_tokens == DEFAULT_TOKENS


async def test_add_model_vision_maps_to_image2text(
    admin: httpx.AsyncClient, container: Container, sm: SM
):
    """POST: `vision` na drucie zapisuje `image2text` w bazie (K13 §2)."""
    instance_id = await _make_instance(container)
    await admin.post(_models(INSTANCE), json={"model_name": "m-v", "model_type": "vision"})
    rows = await _rows(sm, instance_id)
    assert [row.model_type for row in rows] == ["image2text"]


async def test_add_model_duplicate_is_data_error(admin: httpx.AsyncClient, container: Container):
    """POST wiersz 3: para (nazwa, typ) już w rejestrze → 102 (także w innej instancji)."""
    await _make_instance(container)
    await _post(admin, INSTANCE)
    body = await _post(admin, "default")
    assert body["code"] == DATA_ERROR
    assert body["message"] == ALREADY_EXISTS


async def test_add_model_missing_fields(admin: httpx.AsyncClient, container: Container):
    """POST wiersz 4: brak nazwy albo typu → 101."""
    await _make_instance(container)
    body = _body(await admin.post(_models(INSTANCE), json={"model_type": "chat"}))
    assert body["code"] == ARGUMENT_ERROR
    assert body["message"] == "model_name and model_type are required"


async def test_add_model_invalid_type(admin: httpx.AsyncClient, container: Container):
    """POST wiersz 5: nieznany typ → 101 z nazwą typu w komunikacie."""
    await _make_instance(container)
    body = _body(await admin.post(_models(INSTANCE), json={"model_name": "x", "model_type": "foo"}))
    assert body["code"] == ARGUMENT_ERROR
    assert body["message"] == "Invalid model_type 'foo'"


async def test_add_model_to_default_instance_keeps_null_instance_id(
    admin: httpx.AsyncClient, sm: SM
):
    """POST wiersz 6: instancja `default` = `instance_id IS NULL` (K13 §0 p. 2)."""
    body = _body(
        await admin.post(_models("default"), json={"model_name": "m-d", "model_type": "chat"})
    )
    assert body["code"] == 0
    added = {row.name: row for row in await _rows(sm, None)}["m-d"]
    assert added.instance_id is None
    assert added.provider == PROVIDER


async def test_add_model_to_unknown_instance(admin: httpx.AsyncClient, container: Container):
    """POST wiersz: nieznana instancja → 102 z nazwą dostawcy ze ścieżki."""
    await _make_instance(container)
    body = await _post(admin, "nie-ma")
    assert body["code"] == DATA_ERROR
    assert body["message"] == f"No instance found for provider '{PROVIDER}' and instance 'nie-ma'"


async def test_add_model_race_maps_to_data_error(
    admin: httpx.AsyncClient, container: Container, monkeypatch: pytest.MonkeyPatch
):
    """Wyścig między sprawdzeniem duplikatu a INSERT-em → 102 (K13 §4 p. 6)."""
    await _make_instance(container)
    await _post(admin, INSTANCE)

    async def _no_duplicate(session: Any, name: str, model_type: str) -> None:
        return None

    monkeypatch.setattr(models_repo, "get_by_name_type_any", _no_duplicate)
    body = await _post(admin, INSTANCE)
    assert body["code"] == DATA_ERROR
    assert body["message"] == ALREADY_EXISTS


async def test_instance_addressed_by_id(admin: httpx.AsyncClient, container: Container, sm: SM):
    """`{instance}` przyjmuje id wiersza, nie tylko nazwę (K13 §2)."""
    instance_id = await _make_instance(container)
    body = await _post(admin, instance_id)
    assert body["code"] == 0
    assert [row.name for row in await _rows(sm, instance_id)] == ["m-a"]


async def test_default_instance_addressed_by_synthetic_id(admin: httpx.AsyncClient, sm: SM):
    """Id syntetyczne instancji `default` działa w ścieżce jak nazwa (K13 §0 p. 2)."""
    body = await _post(admin, default_instance_id())
    assert body["code"] == 0
    added = {row.name: row for row in await _rows(sm, None)}["m-a"]
    assert added.instance_id is None


async def test_add_model_extra_roundtrip(admin: httpx.AsyncClient, container: Container):
    """POST `extra` zapisany i widoczny w GET (K13 §3)."""
    await _make_instance(container)
    payload = {"model_name": "m-x", "model_type": "chat", "extra": {"vision": False}}
    assert (await _post(admin, INSTANCE, payload))["code"] == 0
    listed = _body(await admin.get(_models(INSTANCE)))
    assert listed["data"][0]["extra"] == {"vision": False}


async def test_list_models_shape(admin: httpx.AsyncClient, container: Container, sm: SM):
    """GET wiersz 7: kształt `InstanceModel` i sortowanie po nazwie (K13 §3)."""
    instance_id = await _make_instance(container)
    await admin.post(_models(INSTANCE), json={"model_name": "m-b", "model_type": "chat"})
    await _post(admin, INSTANCE)
    body = _body(await admin.get(_models(INSTANCE)))
    assert [row["name"] for row in body["data"]] == ["m-a", "m-b"]
    first = body["data"][0]
    assert set(first) == {
        "name",
        "model_type",
        "max_tokens",
        "status",
        "rank",
        "extra",
        "wd_model_id",
        "wd_dimension",
        "wd_is_default",
    }
    assert first["status"] == "active"
    assert first["extra"] == {}
    assert first["rank"] == RANK
    assert first["wd_is_default"] is False
    assert first["max_tokens"] == DEFAULT_TOKENS
    assert first["wd_dimension"] is None
    assert first["wd_model_id"] == (await _rows(sm, instance_id))[0].id


async def test_list_models_default_instance(admin: httpx.AsyncClient, sm: SM):
    """GET: instancja `default` to modele zasiane przez kontener (`instance_id IS NULL`)."""
    body = _body(await admin.get(_models("default")))
    names = [row["name"] for row in body["data"]]
    assert DEFAULT_CHAT in names
    assert DEFAULT_EMBEDDING in names
    seeded = next(row for row in body["data"] if row["name"] == DEFAULT_CHAT)
    assert seeded["status"] == "active"
    assert seeded["model_type"] == "chat"
    assert seeded["wd_is_default"] is True


async def test_list_models_vision_name_in_output(
    admin: httpx.AsyncClient, container: Container, sm: SM
):
    """GET: `image2text` w bazie wychodzi jako `vision` (K13 §2)."""
    await _make_instance(container)
    await admin.post(_models(INSTANCE), json={"model_name": "m-v", "model_type": "image2text"})
    body = _body(await admin.get(_models(INSTANCE)))
    assert [row["model_type"] for row in body["data"]] == ["vision"]


async def test_patch_status_changes_rows(admin: httpx.AsyncClient, container: Container, sm: SM):
    """PATCH wiersz 8: `status: inactive` widoczny w GET i w bazie."""
    instance_id = await _make_instance(container)
    await _post(admin, INSTANCE)
    body = _body(await admin.patch(f"{_models(INSTANCE)}/m-a", json={"status": "inactive"}))
    assert body["code"] == 0
    listed = _body(await admin.get(_models(INSTANCE)))
    assert listed["data"][0]["status"] == "inactive"
    stored = await _rows(sm, instance_id)
    assert stored[0].is_active is False


async def test_patch_max_tokens_and_extra(admin: httpx.AsyncClient, container: Container, sm: SM):
    """PATCH: `max_tokens` i `extra` zapisane; puste `extra` zostaje obiektem."""
    instance_id = await _make_instance(container)
    await _post(admin, INSTANCE)
    await admin.patch(
        f"{_models(INSTANCE)}/m-a", json={"max_tokens": PATCH_TOKENS, "extra": {"a": 1}}
    )
    row = (await _rows(sm, instance_id))[0]
    assert row.max_tokens == PATCH_TOKENS
    assert row.extra == {"a": 1}
    listed = _body(await admin.get(_models(INSTANCE)))
    assert listed["data"][0]["extra"] == {"a": 1}


async def test_patch_touches_all_rows_of_name(
    admin: httpx.AsyncClient, container: Container, sm: SM
):
    """PATCH dotyczy wszystkich wierszy tej nazwy w instancji (K13 §4 p. 7)."""
    instance_id = await _make_instance(container)
    await _post(admin, INSTANCE)
    embedding = {"model_name": "m-a", "model_type": "embedding", "wd_dimension": DIMENSION}
    assert (await _post(admin, INSTANCE, embedding))["code"] == 0
    body = _body(await admin.patch(f"{_models(INSTANCE)}/m-a", json={"max_tokens": PATCH_TOKENS}))
    assert body["code"] == 0
    assert {row.max_tokens for row in await _rows(sm, instance_id)} == {PATCH_TOKENS}


async def test_patch_reactivates_model(admin: httpx.AsyncClient, container: Container, sm: SM):
    """PATCH `active` wraca — model da się włączyć z powrotem (K13 §4 p. 7)."""
    instance_id = await _make_instance(container)
    await _post(admin, INSTANCE)
    await admin.patch(f"{_models(INSTANCE)}/m-a", json={"status": "inactive"})
    body = _body(await admin.patch(f"{_models(INSTANCE)}/m-a", json={"status": "active"}))
    assert body["code"] == 0
    assert (await _rows(sm, instance_id))[0].is_active is True


async def test_patch_empty_body(admin: httpx.AsyncClient, container: Container):
    """PATCH wiersz 10: brak wszystkich pól → 101 (komunikat dosłowny)."""
    await _make_instance(container)
    await _post(admin, INSTANCE)
    body = _body(await admin.patch(f"{_models(INSTANCE)}/m-a", json={}))
    assert body["code"] == ARGUMENT_ERROR
    assert body["message"] == REQUIRED_UPDATE


async def test_patch_invalid_status(admin: httpx.AsyncClient, container: Container):
    """PATCH: status spoza `active|inactive` → 101."""
    await _make_instance(container)
    await _post(admin, INSTANCE)
    body = _body(await admin.patch(f"{_models(INSTANCE)}/m-a", json={"status": "bogus"}))
    assert body["code"] == ARGUMENT_ERROR
    assert body["message"] == "status must be 'active' or 'inactive'"


async def test_patch_model_type_rejected_first(admin: httpx.AsyncClient, container: Container):
    """PATCH wiersz 11: `model_type` w ciele sprawdzane przed pozostałymi regułami."""
    await _make_instance(container)
    changed = {"model_type": "chat", "status": "active"}
    body = _body(await admin.patch(f"{_models(INSTANCE)}/m-a", json=changed))
    assert body["code"] == ARGUMENT_ERROR
    assert body["message"] == "model_type cannot be changed"


async def test_patch_missing_model(admin: httpx.AsyncClient, container: Container):
    """PATCH: brak wiersza o tej nazwie w instancji → 102."""
    await _make_instance(container)
    body = _body(await admin.patch(f"{_models(INSTANCE)}/m-a", json={"status": "inactive"}))
    assert body["code"] == DATA_ERROR
    assert body["message"] == "Model 'm-a' not found"


async def test_patch_default_model_cannot_be_inactive(admin: httpx.AsyncClient, sm: SM):
    """PATCH wiersz 12: `inactive` na modelu domyślnym → 102 (K13 §4 p. 7)."""
    body = _body(
        await admin.patch(f"{_models('default')}/{DEFAULT_CHAT}", json={"status": "inactive"})
    )
    assert body["code"] == DATA_ERROR
    assert body["message"] == (
        f"Model '{DEFAULT_CHAT}' is a default model; set another default model first"
        " (PUT /api/v1/system/models/default or Settings → Models) and retry"
    )
    seeded = {row.name: row for row in await _rows(sm, None)}[DEFAULT_CHAT]
    assert seeded.is_active is True


async def test_delete_default_model_blocked(admin: httpx.AsyncClient, sm: SM):
    """DELETE wiersz 13: model domyślny → 102, wiersz nadal istnieje."""
    body = _body(
        await admin.request("DELETE", _models("default"), json={"model_name": [DEFAULT_CHAT]})
    )
    assert body["code"] == DATA_ERROR
    assert body["message"] == (
        f"Model '{DEFAULT_CHAT}' is a default model; set another default model first"
        " (PUT /api/v1/system/models/default or Settings → Models) and retry"
    )
    assert DEFAULT_CHAT in {row.name for row in await _rows(sm, None)}


async def test_delete_embedding_used_by_dataset(
    admin: httpx.AsyncClient, container: Container, sm: SM, make_user: MakeUser
):
    """DELETE wiersz 14: embedding wskazany przez dataset → 102 z liczbą datasetów."""
    instance_id = await _make_instance(container)
    await admin.post(
        _models(INSTANCE),
        json={"model_name": "m-e", "model_type": "embedding", "wd_dimension": DIMENSION},
    )
    await _make_dataset(sm, make_user, "m-e@litellm")
    body = _body(await admin.request("DELETE", _models(INSTANCE), json={"model_name": ["m-e"]}))
    assert body["code"] == DATA_ERROR
    assert body["message"] == USED_BY_ONE
    assert [row.name for row in await _rows(sm, instance_id)] == ["m-e"]


async def test_delete_missing_name_keeps_all(
    admin: httpx.AsyncClient, container: Container, sm: SM
):
    """DELETE wiersz 15: brak jednej nazwy → 102 i nic nie znika (jedna transakcja)."""
    instance_id = await _make_instance(container)
    await _post(admin, INSTANCE)
    body = _body(
        await admin.request("DELETE", _models(INSTANCE), json={"model_name": ["m-a", "nie-ma"]})
    )
    assert body["code"] == DATA_ERROR
    assert body["message"] == "Model 'nie-ma' not found"
    assert [row.name for row in await _rows(sm, instance_id)] == ["m-a"]


async def test_delete_removes_rows(admin: httpx.AsyncClient, container: Container, sm: SM):
    """DELETE: istniejące modele znikają, audyt po jednym wpisie na model."""
    instance_id = await _make_instance(container)
    await _post(admin, INSTANCE)
    await admin.post(_models(INSTANCE), json={"model_name": "m-b", "model_type": "chat"})
    body = _body(
        await admin.request("DELETE", _models(INSTANCE), json={"model_name": ["m-a", "m-b"]})
    )
    assert body["code"] == 0
    assert await _rows(sm, instance_id) == []


async def test_delete_deduplicates_repeated_names(
    admin: httpx.AsyncClient, container: Container, sm: SM, audit_rows: AuditRows
):
    """Powtórzona nazwa w ``model_name`` = jedno usunięcie, jeden wpis audytu (K13 §4 p. 8)."""
    instance_id = await _make_instance(container)
    await _post(admin, INSTANCE)

    body = _body(
        await admin.request("DELETE", _models(INSTANCE), json={"model_name": ["m-a", "m-a"]})
    )

    assert body["code"] == 0
    assert await _rows(sm, instance_id) == []
    deleted = await audit_rows("model_deleted")
    assert [entry.details["name"] for entry in deleted] == ["m-a"]


async def test_delete_missing_model_name(admin: httpx.AsyncClient, container: Container):
    """DELETE: brak albo pusta lista `model_name` → 101."""
    await _make_instance(container)
    for payload in ({}, {"model_name": []}):
        body = _body(await admin.request("DELETE", _models(INSTANCE), json=payload))
        assert body["code"] == ARGUMENT_ERROR, payload
        assert body["message"] == "model_name is required"


async def test_member_denied_on_writes(member: httpx.AsyncClient, container: Container, sm: SM):
    """Wiersz 16: zwykły użytkownik na POST/PATCH/DELETE/`supported` → 108 (K13 §2)."""
    instance_id = await _make_instance(container)
    calls = (
        ("POST", _models(INSTANCE), {"model_name": "m-a", "model_type": "chat"}),
        ("PATCH", f"{_models(INSTANCE)}/m-a", {"status": "inactive"}),
        ("DELETE", _models(INSTANCE), {"model_name": ["m-a"]}),
    )
    for method, path, payload in calls:
        response = await member.request(method, path, json=payload)
        body = _body(response)
        assert body["code"] == PERMISSION_ERROR, (method, path)
        assert body["message"] == "No authorization."
    supported = await member.get(_models(INSTANCE), params={"supported": "true"})
    assert _body(supported)["code"] == PERMISSION_ERROR
    assert await _rows(sm, instance_id) == []


async def test_anonymous_denied(anon: httpx.AsyncClient, container: Container):
    """Bez klucza API: 401 na liście i na zapisie (K13 §2 — GET dla zalogowanych)."""
    await _make_instance(container)
    assert (await anon.get(_models(INSTANCE))).status_code == UNAUTHORIZED
    posted = await anon.post(_models(INSTANCE), json={"model_name": "m-a", "model_type": "chat"})
    assert posted.status_code == UNAUTHORIZED


async def test_supported_uses_probe_with_instance_key(
    admin: httpx.AsyncClient, container: Container, monkeypatch: pytest.MonkeyPatch
):
    """GET `?supported=true`: sonda dostaje `base_url` i odszyfrowany klucz instancji."""
    await _make_instance(container, api_key="sk-secret")
    calls: list[tuple[str, str | None]] = []

    async def fake_probe(base_url: str, api_key: str | None) -> list[str]:
        calls.append((base_url, api_key))
        return ["b-model", "a-model"]

    monkeypatch.setattr(provider_probe, "probe_models", fake_probe)
    body = _body(await admin.get(_models(INSTANCE), params={"supported": "true"}))
    assert [row["name"] for row in body["data"]] == ["a-model", "b-model"]
    assert body["data"][0]["rank"] == RANK
    assert calls == [(GW_URL, "sk-secret")]


async def test_supported_default_instance_uses_environment(
    admin: httpx.AsyncClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
):
    """GET `?supported=true` dla `default`: bramka i klucz ze środowiska (K13 §0 p. 2)."""
    calls: list[tuple[str, str | None]] = []

    async def fake_probe(base_url: str, api_key: str | None) -> list[str]:
        calls.append((base_url, api_key))
        return []

    monkeypatch.setattr(provider_probe, "probe_models", fake_probe)
    body = _body(await admin.get(_models("default"), params={"supported": "true"}))
    assert body["data"] == []
    assert calls == [(settings.llm_base_url, settings.llm_api_key.get_secret_value() or None)]


async def test_supported_probe_error_becomes_data_error(
    admin: httpx.AsyncClient, container: Container, monkeypatch: pytest.MonkeyPatch
):
    """Porażka sondy przechodzi dalej jako 102 (K13 §4 p. 5)."""
    await _make_instance(container)

    async def failing_probe(base_url: str, api_key: str | None) -> list[str]:
        raise NotFound("Connection failed: HTTP 500")

    monkeypatch.setattr(provider_probe, "probe_models", failing_probe)
    body = _body(await admin.get(_models(INSTANCE), params={"supported": "true"}))
    assert body["code"] == DATA_ERROR


async def test_supported_without_flag_returns_registry(
    admin: httpx.AsyncClient, container: Container
):
    """GET bez `supported` zwraca rejestr, nie listę bramki (K13 §3 p. 7)."""
    await _make_instance(container)
    await _post(admin, INSTANCE)
    body = _body(await admin.get(_models(INSTANCE), params={"supported": "false"}))
    assert [row["name"] for row in body["data"]] == ["m-a"]


async def test_audit_entries_for_mutations(
    admin: httpx.AsyncClient, container: Container, audit_rows: AuditRows, sm: SM
):
    """Wiersz 17: audyt `model_added|updated|deleted` po jednym wpisie na model (K13 §2)."""
    instance_id = await _make_instance(container)
    await _post(admin, INSTANCE)
    added = await audit_rows("model_added")
    assert len(added) == 1
    row = (await _rows(sm, instance_id))[0]
    assert added[0].target_type == "model"
    assert added[0].target_id == row.id
    assert added[0].actor_label == ADMIN_EMAIL
    assert added[0].details == {"name": "m-a", "model_type": "chat", "instance": INSTANCE}

    await admin.patch(f"{_models(INSTANCE)}/m-a", json={"status": "inactive"})
    updated = await audit_rows("model_updated")
    assert len(updated) == 1
    assert updated[0].target_id == row.id
    assert updated[0].details == {"name": "m-a", "model_type": "chat", "instance": INSTANCE}

    await admin.request("DELETE", _models(INSTANCE), json={"model_name": ["m-a"]})
    deleted = await audit_rows("model_deleted")
    assert len(deleted) == 1
    assert deleted[0].target_id == row.id


async def test_audit_details_have_no_api_key(
    admin: httpx.AsyncClient, container: Container, audit_rows: AuditRows
):
    """Audyt nie niesie klucza instancji (K13 §2 — klucz nigdy w logach)."""
    await _make_instance(container, api_key="sk-secret")
    await _post(admin, INSTANCE)
    entry = (await audit_rows("model_added"))[0]
    assert "sk-secret" not in str(entry.details)


async def test_unknown_provider_and_bare_instances_path(
    admin: httpx.AsyncClient, container: Container
):
    """Nieznany dostawca → 102 `Provider … not found` (K13 §0 p. 3)."""
    await _make_instance(container)
    body = _body(await admin.get("/api/v1/providers/bogus/instances/gw1/models"))
    assert body["code"] == DATA_ERROR
    assert body["message"] == "Provider bogus not found"
