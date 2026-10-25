"""Testy HTTP trasy ``POST /api/v1/searches/{id}/completions`` (brief T3; CONTRACT E4-4a §D7).

Wzorzec: ``tests/integration/api/test_sessions_ask.py`` (httpx ASGI, fake-llm, dataset
z zaindeksowanym dokumentem) i ``test_searches_routes.py`` (dwaj użytkownicy). Kształt ramek
porównywany ze złotem ``tests/contract/golden/v0.27.2/searches___completions/searches--21.sse``.
"""

import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.auth.principal import get_principal
from app.api.ragflow.sse import TERMINATOR
from app.core.config import Settings
from app.core.container import Container
from app.core.error_codes import RetCode
from app.domain.policy import Principal
from app.main import create_app
from tests.integration.ingest.conftest import seed_dataset
from tests.integration.ingest.pipeline_helpers import make_container
from tests.integration.retrieval.conftest import ingest_text, principal_for

pytestmark = [pytest.mark.db, pytest.mark.fakellm]

# Dokument i pytanie dzielą słowa → tryb termowy gwarantuje trafienie (retrieval completion).
_DOC = "Wawelski smok mieszkał w jamie pod Wawelem i ział ogniem na mieszkańców."
_QUESTION = "smok wawelski mieszkał w jamie pod Wawelem"
# Pytanie bez słów dokumentu → 0 chunków (brief T1); model ma być mimo to wołany (async_ask).
_QUESTION_NO_HITS = "zzz qqq nieistniejące słowa"
_HTTP_OK = 200
_NO_AUTHORIZATION = "no authorization"
_KB_IDS_REQUIRED = "`kb_ids` is required."
_NO_QUESTION = "required argument are missing: question; "
# Klucze koperty ramki SSE (§D7, złoto searches--21): code, message, data.
_ENVELOPE_KEYS = ["code", "message", "data"]
# Złoto v0.27.2 scenariusza searches, krok completion — wzorzec struktury ramek.
_GOLDEN_COMPLETION_SSE = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "contract"
    / "golden"
    / "v0.27.2"
    / "searches___completions"
    / "searches--21.sse"
)


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener testowy (wzór tests/integration/api/test_sessions_ask.py)."""
    instance = await make_container(migrated_db, tmp_path)
    yield instance
    await instance.aclose()


def _app(container: Container, principal: Principal) -> FastAPI:
    """Aplikacja na żywym kontenerze z nadpisanym uwierzytelnianiem."""
    app = create_app(container.settings, container)
    app.dependency_overrides[get_principal] = lambda: principal
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    """Klient ASGI nad aplikacją testową (wzorzec test_searches_routes.py)."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _frames(content: bytes) -> list[bytes]:
    """Ramki SSE: podział po b"\\n\\n"; treść musi kończyć się TERMINATORem."""
    parts = content.split(b"\n\n")
    assert parts[-1] == b""
    return parts[:-1]


def _json_frames(content: bytes) -> list[dict[str, Any]]:
    """Ramki SSE jako obiekty JSON (prefiks ``b"data:"`` bez spacji, jak w złocie)."""
    frames = _frames(content)
    assert all(frame.startswith(b"data:") and not frame.startswith(b"data: ") for frame in frames)
    return [json.loads(frame[len(b"data:") :]) for frame in frames]


async def _create_search(
    client: httpx.AsyncClient, name: str, *, search_config: dict[str, Any]
) -> str:
    """Tworzy wyszukiwarkę przez API i zwraca jej id (trasy CRUD z T2b)."""
    resp = await client.post(
        "/api/v1/searches", json={"name": name, "search_config": search_config}
    )
    assert resp.status_code == _HTTP_OK
    body = resp.json()
    assert body["code"] == RetCode.SUCCESS
    return str(body["data"]["search_id"])


def _assert_stream_shape(resp: httpx.Response) -> list[dict[str, Any]]:
    """Wspólne asercje strumienia: nagłówki, koperta każdej ramki, terminator; zwraca ramki."""
    assert resp.status_code == _HTTP_OK
    assert resp.headers["content-type"] == "text/event-stream; charset=utf-8"
    assert resp.headers["cache-control"] == "no-cache"
    assert resp.headers["x-accel-buffering"] == "no"
    assert _frames(resp.content)[-1] + b"\n\n" == TERMINATOR
    objects = _json_frames(resp.content)
    for obj in objects:
        assert list(obj) == _ENVELOPE_KEYS
        assert obj["code"] == 0
        assert obj["message"] == ""
    return objects


def _assert_deltas_and_final(objects: list[dict[str, Any]]) -> None:
    """Delty ``final:false`` z pustą referencją, potem finalna z niepustymi chunkami (§D7)."""
    deltas = objects[:-2]
    assert deltas
    for obj in deltas:
        assert obj["data"]["final"] is False
        assert obj["data"]["reference"] == {}
    final = objects[-2]["data"]
    assert final["final"] is True
    assert final["answer"] == ""
    assert final["reference"]["chunks"]
    assert final["reference"]["total"] >= 1
    assert objects[-1]["data"] is True


async def test_completion_streams_answer_with_reference(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Właściciel bez ``chat_id``: 200 SSE, delty, final z chunkami, terminator (złoto --21)."""
    dataset = await seed_dataset(sm)
    await ingest_text(container, dataset, "wawel.txt", _DOC)
    async with _client(_app(container, principal_for(dataset.tenant_id))) as client:
        search_id = await _create_search(
            client, "wd_e4a_ask", search_config={"kb_ids": [dataset.id]}
        )
        resp = await client.post(
            f"/api/v1/searches/{search_id}/completions", json={"question": _QUESTION}
        )

    _assert_deltas_and_final(_assert_stream_shape(resp))


async def _set_meta(
    client: httpx.AsyncClient, dataset_id: str, document_id: str, key: str, value: str
) -> None:
    """Ustawia metadane dokumentu przez ``PATCH …/documents/metadatas`` (E2-1 DS3)."""
    resp = await client.patch(
        f"/api/v1/datasets/{dataset_id}/documents/metadatas",
        json={
            "selector": {"document_ids": [document_id]},
            "updates": [{"key": key, "value": value}],
            "deletes": [],
        },
    )
    assert resp.json()["code"] == RetCode.SUCCESS


async def test_completion_applies_search_config_meta_data_filter_auto(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """``search_config.meta_data_filter`` auto (model czatu) zawęża retrieval wyszukiwarki.

    Dwa dokumenty z różnymi wartościami metadanej; pytanie zawiera wartość jednego z nich →
    fake-llm generuje warunek → referencja tylko z tego dokumentu (K11 §10f p. 5). Bez gałęzi
    auto filtr byłby po cichu ignorowany i referencja miałaby dwa chunki.
    """
    dataset = await seed_dataset(sm)
    old = await ingest_text(container, dataset, "old.txt", _DOC)
    new = await ingest_text(container, dataset, "new.txt", _DOC)
    async with _client(_app(container, principal_for(dataset.tenant_id))) as client:
        await _set_meta(client, dataset.id, old, "temat", "wawelski")
        await _set_meta(client, dataset.id, new, "temat", "krakow")
        search_id = await _create_search(
            client,
            "wd_e6_meta_filter_auto",
            search_config={"kb_ids": [dataset.id], "meta_data_filter": {"method": "auto"}},
        )
        resp = await client.post(
            f"/api/v1/searches/{search_id}/completions", json={"question": _QUESTION}
        )

    final = _assert_stream_shape(resp)[-2]["data"]
    assert final["final"] is True
    assert final["reference"]["total"] == 1


async def test_completion_applies_search_config_meta_data_filter(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """``search_config.meta_data_filter`` (manual) zawęża retrieval wyszukiwarki (K11 §10f p. 5).

    Filtr na nieistniejącym kluczu metadanych → brak trafień → pusta referencja; bez filtra
    ten sam korpus dawałby 1 chunk (złoto ``metadata_e6--42`` — zbiór pusty, nie brak zawężenia).
    """
    dataset = await seed_dataset(sm)
    await ingest_text(container, dataset, "wawel.txt", _DOC)
    async with _client(_app(container, principal_for(dataset.tenant_id))) as client:
        search_id = await _create_search(
            client,
            "wd_e6_meta_filter",
            search_config={
                "kb_ids": [dataset.id],
                "meta_data_filter": {
                    "method": "manual",
                    "manual": [{"key": "author", "op": "=", "value": "Z"}],
                },
            },
        )
        resp = await client.post(
            f"/api/v1/searches/{search_id}/completions", json={"question": _QUESTION}
        )

    final = _assert_stream_shape(resp)[-2]["data"]
    assert final["final"] is True
    assert final["reference"]["chunks"] == []
    assert final["reference"]["total"] == 0


async def test_completion_without_hits_calls_model(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """0 trafień: model wołany (delty niepuste), final z pustą referencją (C1/C2 ``async_ask``)."""
    dataset = await seed_dataset(sm)
    await ingest_text(container, dataset, "wawel.txt", _DOC)
    async with _client(_app(container, principal_for(dataset.tenant_id))) as client:
        search_id = await _create_search(
            client, "wd_e4h2_pusto", search_config={"kb_ids": [dataset.id]}
        )
        resp = await client.post(
            f"/api/v1/searches/{search_id}/completions",
            json={"question": _QUESTION_NO_HITS},
        )

    objects = _assert_stream_shape(resp)
    deltas = objects[:-2]
    assert any(obj["data"]["final"] is False and obj["data"]["answer"] != "" for obj in deltas)
    final = objects[-2]["data"]
    assert final["final"] is True
    assert final["answer"] == ""
    assert final["reference"]["chunks"] == []
    assert final["reference"]["total"] == 0
    assert objects[-1]["data"] is True


async def test_completion_with_empty_chat_id_uses_default_model(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Puste ``chat_id`` → model domyślny użytkownika i normalny strumień (DEC-174 p. 1)."""
    dataset = await seed_dataset(sm)
    await ingest_text(container, dataset, "wawel.txt", _DOC)
    async with _client(_app(container, principal_for(dataset.tenant_id))) as client:
        search_id = await _create_search(
            client, "wd_e4a_domyslny", search_config={"kb_ids": [dataset.id], "chat_id": ""}
        )
        resp = await client.post(
            f"/api/v1/searches/{search_id}/completions", json={"question": _QUESTION}
        )

    _assert_deltas_and_final(_assert_stream_shape(resp))


async def test_completion_alias_path_streams(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Alias ``/completion`` obsługuje ten sam handler co ``/completions`` (§D6)."""
    dataset = await seed_dataset(sm)
    await ingest_text(container, dataset, "wawel.txt", _DOC)
    async with _client(_app(container, principal_for(dataset.tenant_id))) as client:
        search_id = await _create_search(
            client, "wd_e4a_alias", search_config={"kb_ids": [dataset.id]}
        )
        resp = await client.post(
            f"/api/v1/searches/{search_id}/completion", json={"question": _QUESTION}
        )

    _assert_deltas_and_final(_assert_stream_shape(resp))


async def test_completion_body_kb_ids_used_when_search_unbound(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Wyszukiwarka bez wiązań + ``kb_ids`` w ciele żądania → strumień (§D7)."""
    dataset = await seed_dataset(sm)
    await ingest_text(container, dataset, "wawel.txt", _DOC)
    async with _client(_app(container, principal_for(dataset.tenant_id))) as client:
        search_id = await _create_search(client, "wd_e4a_ciało", search_config={})
        resp = await client.post(
            f"/api/v1/searches/{search_id}/completions",
            json={"question": _QUESTION, "kb_ids": [dataset.id]},
        )

    _assert_deltas_and_final(_assert_stream_shape(resp))


async def test_completion_missing_question_gives_101(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Brak ``question`` → 101 ``data:null`` (złoto searches--22)."""
    dataset = await seed_dataset(sm)
    async with _client(_app(container, principal_for(dataset.tenant_id))) as client:
        search_id = await _create_search(client, "wd_e4a_101", search_config={})
        resp = await client.post(f"/api/v1/searches/{search_id}/completions", json={})

    assert resp.status_code == _HTTP_OK
    assert resp.json() == {
        "code": RetCode.ARGUMENT_ERROR,
        "data": None,
        "message": _NO_QUESTION,
    }


async def test_completion_without_dataset_ids_gives_102(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Wyszukiwarka bez wiązań i bez ``kb_ids`` w ciele → 102 (złoto searches--24)."""
    dataset = await seed_dataset(sm)
    async with _client(_app(container, principal_for(dataset.tenant_id))) as client:
        search_id = await _create_search(client, "wd_e4a_102", search_config={})
        resp = await client.post(
            f"/api/v1/searches/{search_id}/completions", json={"question": _QUESTION}
        )

    assert resp.status_code == _HTTP_OK
    assert resp.json() == {"code": RetCode.DATA_ERROR, "message": _KB_IDS_REQUIRED}
    assert b"data:" not in resp.content


async def test_completion_foreign_dataset_in_body_gives_102(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Cudzy dataset w ``kb_ids`` ciała → 102 z jego id (złoto searches--25)."""
    own = await seed_dataset(sm)
    foreign = await seed_dataset(sm)
    async with _client(_app(container, principal_for(own.tenant_id))) as client:
        search_id = await _create_search(client, "wd_e4a_cudzy", search_config={})
        resp = await client.post(
            f"/api/v1/searches/{search_id}/completions",
            json={"question": _QUESTION, "kb_ids": [foreign.id]},
        )

    assert resp.status_code == _HTTP_OK
    assert resp.json() == {
        "code": RetCode.DATA_ERROR,
        "message": f"You don't own the dataset {foreign.id}",
    }


async def test_completion_foreign_search_refused(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Cudza wyszukiwarka → 109 ``no authorization`` ``data: false`` (złoto searches--23)."""
    dataset = await seed_dataset(sm)
    await ingest_text(container, dataset, "wawel.txt", _DOC)
    async with _client(_app(container, principal_for(dataset.tenant_id))) as client:
        search_id = await _create_search(
            client, "wd_e4a_obca", search_config={"kb_ids": [dataset.id]}
        )
    stranger_app = _app(container, principal_for(uuid.uuid4().hex))
    async with _client(stranger_app) as stranger:
        resp = await stranger.post(
            f"/api/v1/searches/{search_id}/completions", json={"question": _QUESTION}
        )

    assert resp.status_code == _HTTP_OK
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json() == {
        "code": RetCode.AUTHENTICATION_ERROR,
        "data": False,
        "message": _NO_AUTHORIZATION,
    }
    assert b"data:" not in resp.content


async def test_completion_frame_structure_matches_golden(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Struktura ramek zgodna ze złotem ``searches--21.sse`` (§D7, wymaganie 6).

    Porównujemy kopertę i listę kluczy ``data`` (delta, finalna, terminator). Wnętrze chunków
    (``row_id``/``document_metadata``) ma kształt v0.27 (``sse.search_reference``, §D7); różnice
    treści ramek rejestruje ``deviations/searches.yaml`` (T5).
    """
    dataset = await seed_dataset(sm)
    await ingest_text(container, dataset, "wawel.txt", _DOC)
    async with _client(_app(container, principal_for(dataset.tenant_id))) as client:
        search_id = await _create_search(
            client, "wd_e4a_ksztalt", search_config={"kb_ids": [dataset.id]}
        )
        resp = await client.post(
            f"/api/v1/searches/{search_id}/completions", json={"question": _QUESTION}
        )

    actual = _json_frames(resp.content)
    golden = _json_frames(_GOLDEN_COMPLETION_SSE.read_bytes())
    for obj in actual:
        assert list(obj) == list(golden[0])
    assert list(actual[0]["data"]) == list(golden[0]["data"])
    assert list(actual[-2]["data"]) == list(golden[-2]["data"])
    assert list(actual[-2]["data"]["reference"]) == list(golden[-2]["data"]["reference"])
    assert actual[-2]["data"]["reference"]["chunks"]
    assert actual[-1]["data"] is True
