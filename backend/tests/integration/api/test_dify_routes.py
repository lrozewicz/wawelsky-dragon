"""Testy HTTP tras Dify (brief OD p. 1, 4): /dify/retrieval POST+GET i /dify/retrieval/health.

Złoto v0.27.2 (``dify__retrieval/openai_dify--11..14.json``, ``dify__retrieval__health/…--15``)
odtwarza test scenariusza; tutaj sprawdzamy zachowanie tras bezpośrednio — w tym odmowy,
których złoto nie nagrywa: nieistniejąca baza (404) i baza cudza (109).
"""

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.auth.principal import get_principal
from app.core.config import Settings
from app.core.container import Container
from app.core.error_codes import RetCode
from app.domain.policy import Principal
from app.main import create_app
from tests.integration.ingest.conftest import seed_dataset
from tests.integration.ingest.pipeline_helpers import make_container
from tests.integration.retrieval.conftest import ingest_text, principal_for

pytestmark = [pytest.mark.db, pytest.mark.fakellm]

_DOC = "Legenda o smoku wawelskim: smok mieszkał w jaskini pod Wawelem."
_QUESTION = "smok wawelski"
_HTTP_OK = 200
_HTTP_NOT_FOUND = 404
_HTTP_FORBIDDEN = 403
_HTTP_BAD_REQUEST = 400


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener testowy ze storage w tmp_path (wzór tests/integration/api/test_retrieval_routes)."""
    instance = await make_container(migrated_db, tmp_path)
    yield instance
    await instance.aclose()


def _app(container: Container, principal: Principal) -> FastAPI:
    """Aplikacja z nadpisanym uwierzytelnianiem (Wariant: klucz API / JWT bez różnicy)."""
    app = create_app(container.settings, container)
    app.dependency_overrides[get_principal] = lambda: principal
    return app


def _body(knowledge_id: str, **extra: object) -> dict[str, object]:
    """Ciało POST /dify/retrieval jak w kroku dify_retrieval_post scenariusza."""
    return {
        "knowledge_id": knowledge_id,
        "query": _QUESTION,
        "retrieval_setting": {"top_k": 10, "score_threshold": 0.0},
        **extra,
    }


async def test_post_returns_records(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """POST: rekordy w kształcie Dify (content/score/title/metadata) — bez koperty code."""
    dataset = await seed_dataset(sm)
    doc_id = await ingest_text(container, dataset, "ragflow_intro.txt", _DOC)
    app = _app(container, principal_for(dataset.tenant_id))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/v1/dify/retrieval", json=_body(dataset.id))
    assert resp.status_code == _HTTP_OK, resp.text
    body = resp.json()
    assert set(body) == {"records"}
    record = body["records"][0]
    assert set(record) == {"content", "metadata", "score", "title"}
    assert record["content"] == _DOC
    assert record["title"] == "ragflow_intro.txt"
    assert isinstance(record["score"], float)
    assert record["metadata"] == {"doc_id": doc_id, "document_id": doc_id}


async def test_get_matches_post(container: Container, sm: async_sessionmaker[AsyncSession]) -> None:
    """GET z parametrami zwraca to samo ciało co POST (upstream jedno ziarno kodu)."""
    dataset = await seed_dataset(sm)
    await ingest_text(container, dataset, "ragflow_intro.txt", _DOC)
    app = _app(container, principal_for(dataset.tenant_id))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        posted = await client.post("/api/v1/dify/retrieval", json=_body(dataset.id))
        fetched = await client.get(
            "/api/v1/dify/retrieval",
            params={
                "knowledge_id": dataset.id,
                "query": _QUESTION,
                "top_k": "10",
                "score_threshold": "0.0",
            },
        )
    assert fetched.status_code == _HTTP_OK, fetched.text
    assert fetched.json() == posted.json()
    assert fetched.json()["records"]


async def test_get_zero_top_k_is_a_value(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """GET ``top_k=0``/``score_threshold=0`` honoruje podane wartości (FIXA p. 4, DEC-037).

    Wartość trafia do retrievalu jako ``page_size``/``top_k`` (upstream ``page_size=top``,
    dify_retrieval_api.py:255-263) i tam kończy się walidacją 101 — WD nie podmienia jej
    na domyślne 1024 ani nie całkiem ignoruje. ``score_threshold=0`` jest wartością progową
    (0.0 = bez odsiewu), więc przy ``top_k=10`` rekordy nadal wracają.
    """
    dataset = await seed_dataset(sm)
    await ingest_text(container, dataset, "ragflow_intro.txt", _DOC)
    app = _app(container, principal_for(dataset.tenant_id))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        zero = await client.get(
            "/api/v1/dify/retrieval",
            params={
                "knowledge_id": dataset.id,
                "query": _QUESTION,
                "top_k": "0",
                "score_threshold": "0",
            },
        )
        threshold_zero = await client.get(
            "/api/v1/dify/retrieval",
            params={
                "knowledge_id": dataset.id,
                "query": _QUESTION,
                "top_k": "10",
                "score_threshold": "0",
            },
        )
    assert zero.status_code == _HTTP_BAD_REQUEST, zero.text
    assert zero.json()["code"] == RetCode.ARGUMENT_ERROR
    assert threshold_zero.status_code == _HTTP_OK, threshold_zero.text
    assert threshold_zero.json()["records"]


async def test_get_zero_top_k_missing_knowledgebase_is_404(container: Container) -> None:
    """``top_k=0`` z nieznaną bazą wiedzy → 404 (autoryzacja przed walidacją top_k, p. 4)."""
    app = _app(container, principal_for("whoever"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/api/v1/dify/retrieval",
            params={
                "knowledge_id": "no-such-knowledge-id-0000",
                "query": _QUESTION,
                "top_k": "0",
            },
        )
    assert resp.status_code == _HTTP_NOT_FOUND, resp.text
    assert resp.json() == {"code": 404, "message": "Knowledgebase not found!"}


async def test_metadata_condition_matches_nothing(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """metadata_condition na nieistniejącym kluczu → pusta lista (złoto openai_dify--12)."""
    dataset = await seed_dataset(sm)
    await ingest_text(container, dataset, "ragflow_intro.txt", _DOC)
    app = _app(container, principal_for(dataset.tenant_id))
    body = _body(
        dataset.id,
        metadata_condition={
            "logic": "and",
            "conditions": [{"name": "author", "comparison_operator": "is", "value": "wd_rec_e2"}],
        },
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/v1/dify/retrieval", json=body)
    assert resp.status_code == _HTTP_OK, resp.text
    assert resp.json() == {"records": []}


async def test_missing_knowledgebase(container: Container) -> None:
    """Nieznana baza wiedzy → HTTP 404, code 404, komunikat upstreamu (złoto --13)."""
    app = _app(container, principal_for("whoever"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/v1/dify/retrieval", json=_body("no-such-knowledge-id"))
    assert resp.status_code == _HTTP_NOT_FOUND, resp.text
    assert resp.json() == {"code": 404, "message": "Knowledgebase not found!"}


async def test_foreign_knowledgebase_denied(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Cudza baza wiedzy → HTTP 403, code 109 „no authorization” (upstream :250-256).

    Test negatywny mutacji ``e2-1-dify-foreign-knowledge.patch``.
    """
    dataset = await seed_dataset(sm)
    await ingest_text(container, dataset, "ragflow_intro.txt", _DOC)
    app = _app(container, principal_for("intruder"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/v1/dify/retrieval", json=_body(dataset.id))
    assert resp.status_code == _HTTP_FORBIDDEN, resp.text
    assert resp.json() == {"code": 109, "message": "no authorization"}


async def test_missing_query_is_malformed(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Brak query → HTTP 400, code 101, komunikat upstreamu (:215-222)."""
    dataset = await seed_dataset(sm)
    app = _app(container, principal_for(dataset.tenant_id))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/v1/dify/retrieval", json={"knowledge_id": dataset.id})
    assert resp.status_code == _HTTP_BAD_REQUEST, resp.text
    assert resp.json() == {
        "code": 101,
        "message": "required arguments are missing: query; ",
    }


async def test_health_without_auth(container: Container) -> None:
    """Health bez nagłówka Authorization → koperta sukcesu z data true (złoto --15)."""
    app = create_app(container.settings, container)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/v1/dify/retrieval/health")
    assert resp.status_code == _HTTP_OK, resp.text
    assert resp.json() == {"code": RetCode.SUCCESS, "message": "success", "data": True}
