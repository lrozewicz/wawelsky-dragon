"""Testy HTTP trasy ``POST /api/v1/sessions/ask`` (brief T6a p. 5; CONTRACT E2-2b C4).

Wzorzec: ``tests/integration/api/test_completions_routes.py`` (httpx ASGI, fake-llm, dataset
z zaindeksowanym dokumentem). Profil zgodności ``_app`` domyślnie ustawia na ``ragflow_0_24`` —
``sessions_ask`` ma wpis odmowy tylko w tej mapie (C4 p. 2); brak uwierzytelnienia → 401.
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
from app.api.ragflow.compat import CompatProfile, get_compat_profile
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

# Dokument i pytanie dzielą słowa → tryb termowy gwarantuje trafienie (retrieval ask).
_DOC = "Wawelski smok mieszkał w jamie pod Wawelem i ział ogniem na mieszkańców."
_QUESTION = "smok wawelski mieszkał w jamie pod Wawelem"
# Pytanie bez słów dokumentu → 0 trafień; model ma być mimo to wołany (upstream ``async_ask``, C1).
_QUESTION_NO_HITS = "zzz qqq nieistniejące słowa"
_HTTP_OK = 200
_HTTP_UNAUTHORIZED = 401

# Złoto v0.24.0 scenariusza chat_extras, krok ask (C0 p. 6) — wzorzec struktury ramek.
_GOLDEN_ASK_SSE = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "contract"
    / "golden"
    / "v0.24.0"
    / "sessions__ask"
    / "chat_extras--18.sse"
)


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener testowy (wzór tests/integration/chat/conftest.py)."""
    instance = await make_container(migrated_db, tmp_path)
    yield instance
    await instance.aclose()


def _app(
    container: Container, principal: Principal | None, profile: CompatProfile = "ragflow_0_24"
) -> FastAPI:
    """Aplikacja na żywym kontenerze; ``principal=None`` → brak nadpisania auth (test 401).

    Profil zgodności domyślnie ``ragflow_0_24`` (jedyny wpis odmowy ``sessions_ask``).
    """
    app = create_app(container.settings, container)
    if principal is not None:
        app.dependency_overrides[get_principal] = lambda: principal
    app.dependency_overrides[get_compat_profile] = lambda: profile
    return app


def _frames(content: bytes) -> list[bytes]:
    """Ramki SSE: podział po b"\\n\\n"; treść musi kończyć się TERMINATORem."""
    parts = content.split(b"\n\n")
    assert parts[-1] == b""
    return parts[:-1]


def _json_frames(content: bytes) -> list[dict[str, Any]]:
    """Ramki SSE jako obiekty JSON (podział po ``b"\\n\\n"``, prefiks ``b"data:"`` bez spacji)."""
    frames = _frames(content)
    # ``json.loads`` przepuściłby ``data: {...}`` (spacja), a złoto v0.24 ma ``data:{"..."}``.
    assert all(f.startswith(b"data:") and not f.startswith(b"data: ") for f in frames)
    return [json.loads(frame[len(b"data:") :]) for frame in frames]


async def test_ask_streams_answer_with_reference(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """(a) właściciel: 200 SSE, delty parsowalne, final z niepustą referencją, terminator."""
    dataset = await seed_dataset(sm)
    await ingest_text(container, dataset, "wawel.txt", _DOC)
    app = _app(container, principal_for(dataset.tenant_id))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/sessions/ask",
            json={"question": _QUESTION, "dataset_ids": [dataset.id]},
        )
    assert resp.status_code == _HTTP_OK
    assert resp.headers["content-type"] == "text/event-stream; charset=utf-8"
    assert resp.headers["cache-control"] == "no-cache"
    assert resp.headers["x-accel-buffering"] == "no"
    frames = _frames(resp.content)
    assert frames[-1] + b"\n\n" == TERMINATOR
    for frame in frames:
        assert frame.startswith(b"data:")
    final = json.loads(frames[-2][5:])["data"]
    assert final["final"] is True
    assert final["answer"] == ""
    assert final["reference"]["chunks"]
    assert final["reference"]["total"] >= 1
    # Delty: ``reference:{}`` i ``final:false`` (C0 p. 6).
    deltas = [json.loads(frame[5:])["data"] for frame in frames[:-2]]
    assert deltas
    assert all(delta["final"] is False and delta["reference"] == {} for delta in deltas)


@pytest.mark.parametrize(
    "profile",
    ["ragflow_0_27", "ragflow_0_24"],
    ids=["v0.27", "v0.24-shim"],
)
async def test_ask_without_hits_calls_model(
    container: Container,
    sm: async_sessionmaker[AsyncSession],
    profile: CompatProfile,
) -> None:
    """(d) 0 trafień: model wołany (delty niepuste), final z pustą referencją (C1/C2).

    Upstream ``async_ask`` nie ma skrótu ``empty_response`` — ``chat_pipeline`` przy 0 chunkach
    i pustym ``empty_response`` woła LLM i oddaje ``reference={"chunks": []}``, które
    ``sse.ask_reference`` uzupełnia do ``total:0, chunks:[], doc_aggs:[]``. Sprawdzamy oba
    profile zgodności: v0.27 (natywny) i v0.24 (shim ``/sessions/ask``).
    """
    dataset = await seed_dataset(sm)
    await ingest_text(container, dataset, "wawel.txt", _DOC)
    app = _app(container, principal_for(dataset.tenant_id), profile=profile)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/sessions/ask",
            json={"question": _QUESTION_NO_HITS, "dataset_ids": [dataset.id]},
        )
    assert resp.status_code == _HTTP_OK
    assert _frames(resp.content)[-1] + b"\n\n" == TERMINATOR
    objects = _json_frames(resp.content)
    # ≥1 delta z niepustym ``answer`` → model został wołany (brak skrótu empty_response).
    deltas = objects[:-2]
    assert any(obj["data"]["final"] is False and obj["data"]["answer"] != "" for obj in deltas)
    final = objects[-2]["data"]
    assert final["final"] is True
    assert final["answer"] == ""
    assert final["reference"] == {"total": 0, "chunks": [], "doc_aggs": []}
    assert objects[-1]["data"] is True


async def test_ask_foreign_dataset_refused(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """(b) cudzy dataset: 200 JSON code 102, komunikat z id, brak treści dokumentu."""
    dataset = await seed_dataset(sm)
    await ingest_text(container, dataset, "wawel.txt", _DOC)
    app = _app(container, principal_for(uuid.uuid4().hex))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/sessions/ask",
            json={"question": _QUESTION, "dataset_ids": [dataset.id]},
        )
    assert resp.status_code == _HTTP_OK
    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    assert body["code"] == RetCode.DATA_ERROR
    assert "You don't own the dataset" in body["message"]
    assert dataset.id in body["message"]
    assert b"data:" not in resp.content
    assert _DOC.encode() not in resp.content


async def test_ask_requires_auth(container: Container) -> None:
    """(c) bez nagłówka Authorization i bez nagłówka zgodności → HTTP 401."""
    app = _app(container, None)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/sessions/ask",
            json={"question": _QUESTION, "dataset_ids": ["x"]},
        )
    assert resp.status_code == _HTTP_UNAUTHORIZED


async def test_ask_frame_structure_matches_golden(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Struktura ramek ``/sessions/ask`` zgodna ze złotem ``chat_extras--18.sse`` (C0 p. 6).

    Odchyłka ``deviations/v0.24.0/chat_extras.yaml`` zdejmuje z porównania treść delt i chunku
    ([fake-llm]/[chunker]); ten test pokrywa to, czego odchyłka nie widzi: kopertę i listę kluczy
    każdej ramki. Liczba delt zależy od długości odpowiedzi (fake-llm tnie po 5 znaków), więc
    porównujemy kształt, nie liczbę ramek.
    """
    dataset = await seed_dataset(sm)
    await ingest_text(container, dataset, "wawel.txt", _DOC)
    app = _app(container, principal_for(dataset.tenant_id))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/sessions/ask",
            json={"question": _QUESTION, "dataset_ids": [dataset.id]},
        )
    assert resp.status_code == _HTTP_OK
    actual = _json_frames(resp.content)
    golden = _json_frames(_GOLDEN_ASK_SSE.read_bytes())
    # Koperta każdej ramki: klucze, code:0 i message:"" (C0 p. 6; brief T6b p. 2).
    for obj in actual:
        assert list(obj) == list(golden[0])
        assert obj["code"] == 0
        assert obj["message"] == ""
    # Pierwsza delta: klucze ``data`` jak w złocie, pusta referencja.
    assert list(actual[0]["data"]) == list(golden[0]["data"])
    assert actual[0]["data"]["final"] is False
    assert actual[0]["data"]["reference"] == {}
    # Ramka finalna: klucze ``data``, ``reference`` i chunku jak w złocie.
    assert list(actual[-2]["data"]) == list(golden[-2]["data"])
    assert actual[-2]["data"]["final"] is True
    assert list(actual[-2]["data"]["reference"]) == list(golden[-2]["data"]["reference"])
    chunks = actual[-2]["data"]["reference"]["chunks"]
    assert chunks
    assert list(chunks[0]) == list(golden[-2]["data"]["reference"]["chunks"][0])
    # Terminator: ``data: true`` w kopercie z ``message`` (C0 p. 6).
    assert actual[-1]["data"] is True
    assert golden[-1]["data"] is True
    # Każda środkowa ramka to delta o kształcie pierwszej delty złota.
    for obj in actual[1:-2]:
        assert list(obj["data"]) == list(golden[0]["data"])
        assert obj["data"]["final"] is False
        assert obj["data"]["reference"] == {}
