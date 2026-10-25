"""Testy HTTP tras ingestii i embedding/check datasetu (zadanie DS2, E2-1).

Wzorzec: ``tests/integration/api/test_datasets_routes.py`` (TestClient, ``mark.db``).
Stan ingestu zakładamy wierszami (zadanie ``parse_document`` + dokument w ``run='3'``),
bo TestClient nie uruchamia workera; zgodność przepisu embeddingu z ingestem potwierdza
test kontraktowy złota ``datasets_extras--10``.
"""

import json
import re
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.timeutil import from_ms
from app.db.repositories import chunk_vectors
from app.db.repositories import tasks as tasks_repo
from app.db.uow import transaction
from app.llm.openai_gateway import OpenAIGateway
from app.llm.types import ModelRef
from app.services.embed import combine, embed_texts
from tests.integration.api import test_datasets_routes as _api_tests
from tests.integration.api.test_datasets_routes import _bearer, create_dataset

# Fixture'y współdzielone z ``test_datasets_routes``: pytest rejestruje fixture pod nazwą
# atrybutu w TYM module, a zależności (settings, users_svc…) rozwiązuje w łańcuchu tego
# modułu — stąd jawne re-eksporty pod nazwami oryginałów.
settings = _api_tests.settings
users_svc = _api_tests.users_svc
keys_svc = _api_tests.keys_svc
models_seeded = _api_tests.models_seeded
owner = _api_tests.owner
client = _api_tests.client

pytestmark = pytest.mark.db

_OK = 200
_DATA_ERROR = 102
_NOW_MS = 1790157600000
_DURATION_S = 1.25
_TOKEN_NUM = 492
_CHUNK_ID = "a" * 16
_DOC_TEXT = "Legenda o smoku wawelskim należy do najstarszych opowieści Krakowa. " * 4
_DOC_NAME = "ragflow_intro.txt"
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}$")
_EMBEDDING_MODEL = "fake-embed-1024"
_EMBEDDING_DIM = 1024
_GOLDEN = Path(__file__).resolve().parents[3] / "tests" / "contract" / "golden" / "v0.27.2"


def _golden_data(relative: str) -> dict[str, Any]:
    """``body.data`` pliku złota (wzorzec: test_datasets_routes)."""
    loaded: dict[str, Any] = json.loads((_GOLDEN / relative).read_text(encoding="utf-8"))["body"][
        "data"
    ]
    return loaded


def _data(response: Any) -> dict[str, Any]:
    """``data`` z koperty sukcesu (code 0) z asercją HTTP 200."""
    assert response.status_code == _OK, response.text
    payload = response.json()
    assert payload["code"] == 0, payload
    data: dict[str, Any] = payload["data"]
    return data


async def _seed_parsed(
    sm: async_sessionmaker[AsyncSession], client: TestClient, token: str
) -> tuple[str, str, str]:
    """Dataset + dokument po parsowaniu + zadanie parsowania; (dataset_id, document_id, log_id).

    Odpowiednik stanu po ``poll_parse_done`` ze scenariusza: dokument ``run='3'``, liczniki
    datasetu przeliczone, jedno zakończone zadanie ``parse_document`` (tożsamość logu).
    """
    dataset_id = str(create_dataset(client, token, {"name": "wd_ing_ds"})["id"])
    upload = client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        files={"file": (_DOC_NAME, _DOC_TEXT.encode("utf-8"), "text/plain")},
        headers=_bearer(token),
    )
    document_id = str(_data(upload)[0]["id"])
    log_id = uuid.uuid4().hex
    async with transaction(sm) as session:
        await tasks_repo.insert(
            session,
            public_id=log_id,
            task_type="parse_document",
            payload_json="{}",
            document_id=document_id,
            dataset_id=dataset_id,
            priority=0,
            max_attempts=3,
            digest=None,
            next_attempt_at=_NOW_MS,
            now_ms=_NOW_MS,
        )
        await session.execute(
            text(
                "UPDATE documents SET run = '3', progress = 1,"
                " progress_msg = 'Indexing done. Done.', process_begin_at = :ms,"
                " process_duration = :duration, chunk_count = 1, update_time = :ms,"
                " update_date = :date WHERE id = :id"
            ),
            {"ms": _NOW_MS, "duration": _DURATION_S, "date": from_ms(_NOW_MS), "id": document_id},
        )
        await session.execute(
            text(
                "UPDATE datasets SET document_count = 1, chunk_count = 1, token_num = :token_num"
                " WHERE id = :id"
            ),
            {"id": dataset_id, "token_num": _TOKEN_NUM},
        )
    return dataset_id, document_id, log_id


async def _seed_chunk(
    sm: async_sessionmaker[AsyncSession],
    settings: Settings,
    dataset_id: str,
    document_id: str,
) -> None:
    """Wstawia chunk (committed) i wektor zapisany — przepisem embeddingu ingestu (DEC-033 p. 4).

    Wektory liczy bramka LLM w pętli testu (instancja kontenera należy do pętli TestClienta,
    więc nie wolno jej użyć tutaj); test sprawdza trasę (próbkowanie, odczyt wektora,
    cosinus), a sam przepis pilnuje złoto --10.
    """
    async with transaction(sm) as session:
        await session.execute(
            text(
                "INSERT INTO chunks (id, document_id, dataset_id, ordinal, chunk_type,"
                " content, content_ft, content_stem, title_ft, keywords, questions,"
                " important_ft, question_ft, positions, available, committed, token_count,"
                " embed_source, create_time, create_date, update_time, update_date)"
                " VALUES (:id, :document_id, :dataset_id, 0, 'text', :content, :content,"
                " '', '', '[]', '[]', '', '', NULL, 1, 1, 5, 'content', :ms, :date, :ms, :date)"
            ),
            {
                "id": _CHUNK_ID,
                "document_id": document_id,
                "dataset_id": dataset_id,
                "content": _DOC_TEXT,
                "ms": _NOW_MS,
                "date": from_ms(_NOW_MS),
            },
        )
    ref = ModelRef(id=None, name=_EMBEDDING_MODEL, model_type="embedding")
    gateway = OpenAIGateway(settings)
    try:
        title_vec, content_vec = await embed_texts(
            gateway,
            ref,
            [Path(_DOC_NAME).stem, _DOC_TEXT],
            batch_size=2,
            expected_dim=_EMBEDDING_DIM,
        )
    finally:
        await gateway.aclose()
    async with transaction(sm) as session:  # DDL = niejawny COMMIT — osobna transakcja (C2.4)
        await chunk_vectors.ensure_table(session, _EMBEDDING_DIM)
    async with transaction(sm) as session:
        await chunk_vectors.insert_many(
            session, _EMBEDDING_DIM, [(_CHUNK_ID, dataset_id, combine(title_vec, content_vec, 0.1))]
        )


async def test_ingestions_summary_golden_shape(
    sm: async_sessionmaker[AsyncSession], client: TestClient, owner: tuple[str, str]
) -> None:
    """GET …/ingestions/summary → kształt złota --07 i liczby przeliczone po parsie."""
    token, _user_id = owner
    dataset_id, _document_id, _log_id = await _seed_parsed(sm, client, token)
    data = _data(
        client.get(f"/api/v1/datasets/{dataset_id}/ingestions/summary", headers=_bearer(token))
    )
    assert set(data) == set(_golden_data("datasets___ingestions__summary/datasets_extras--07.json"))
    assert data["doc_num"] == 1
    assert data["chunk_num"] == 1
    assert data["token_num"] == _TOKEN_NUM
    assert data["status"] == {
        "cancel_count": 0,
        "done_count": 1,
        "fail_count": 0,
        "running_count": 0,
        "unstart_count": 0,
    }


async def test_ingestions_list_file_log(
    sm: async_sessionmaker[AsyncSession], client: TestClient, owner: tuple[str, str]
) -> None:
    """GET …/ingestions?log_type=file → jeden log pliku w kształcie złota --08."""
    token, _user_id = owner
    dataset_id, document_id, log_id = await _seed_parsed(sm, client, token)
    data = _data(
        client.get(
            f"/api/v1/datasets/{dataset_id}/ingestions",
            params={"page": 1, "page_size": 30, "log_type": "file"},
            headers=_bearer(token),
        )
    )
    golden = _golden_data("datasets___ingestions/datasets_extras--08.json")
    assert set(data) == set(golden)
    assert data["total"] == 1
    log = data["logs"][0]
    assert set(log) == set(golden["logs"][0])
    assert log["id"] == log_id
    assert log["document_id"] == document_id
    assert log["kb_id"] == dataset_id
    assert log["document_name"] == _DOC_NAME
    assert log["document_suffix"] == "txt"
    assert log["document_type"] == "doc"
    assert log["source_from"] == "local"
    assert log["task_type"] == "Parse"
    assert log["operation_status"] == "3"
    assert log["status"] == "1"
    assert log["parser_id"] == "naive" and log["pipeline_title"] == "naive"
    assert log["pipeline_id"] == "" and log["avatar"] == ""
    assert log["progress"] == 1.0
    assert log["process_duration"] == _DURATION_S
    assert log["dsl"] == {}
    assert _DATETIME_RE.match(log["create_date"]) and _DATETIME_RE.match(log["update_date"])
    assert _DATETIME_RE.match(log["process_begin_at"])


async def test_ingestions_list_default_log_type_is_empty(
    sm: async_sessionmaker[AsyncSession], client: TestClient, owner: tuple[str, str]
) -> None:
    """Bez ``log_type`` (domyślnie ``dataset``) → pusta lista bez logów datasetowych."""
    token, _user_id = owner
    dataset_id, _document_id, _log_id = await _seed_parsed(sm, client, token)
    data = _data(client.get(f"/api/v1/datasets/{dataset_id}/ingestions", headers=_bearer(token)))
    assert data == {"logs": [], "total": 0}


async def test_ingestions_list_invalid_log_type(
    sm: async_sessionmaker[AsyncSession], client: TestClient, owner: tuple[str, str]
) -> None:
    """Nieznany ``log_type`` → code 102 z komunikatem upstream (nie 101)."""
    token, _user_id = owner
    dataset_id, _document_id, _log_id = await _seed_parsed(sm, client, token)
    response = client.get(
        f"/api/v1/datasets/{dataset_id}/ingestions",
        params={"log_type": "bogus"},
        headers=_bearer(token),
    )
    assert response.status_code == _OK
    payload = response.json()
    assert payload["code"] == _DATA_ERROR
    assert payload["message"] == 'Invalid "log_type", expected "dataset" or "file"'


async def test_ingestion_get_golden_shape(
    sm: async_sessionmaker[AsyncSession], client: TestClient, owner: tuple[str, str]
) -> None:
    """GET …/ingestions/{log_id} → ten sam log co na liście, kształt złota --09."""
    token, _user_id = owner
    dataset_id, document_id, log_id = await _seed_parsed(sm, client, token)
    data = _data(
        client.get(f"/api/v1/datasets/{dataset_id}/ingestions/{log_id}", headers=_bearer(token))
    )
    assert set(data) == set(_golden_data("datasets___ingestions___/datasets_extras--09.json"))
    assert data["id"] == log_id
    assert data["document_id"] == document_id
    assert data["kb_id"] == dataset_id


async def test_ingestion_get_unknown_log(
    sm: async_sessionmaker[AsyncSession], client: TestClient, owner: tuple[str, str]
) -> None:
    """Nieistniejący log → HTTP 200, code 102 „Log not found" (jak upstream)."""
    token, _user_id = owner
    dataset_id, _document_id, _log_id = await _seed_parsed(sm, client, token)
    response = client.get(
        f"/api/v1/datasets/{dataset_id}/ingestions/{uuid.uuid4().hex}", headers=_bearer(token)
    )
    assert response.status_code == _OK
    payload = response.json()
    assert payload["code"] == _DATA_ERROR
    assert payload["message"] == "Log not found"


async def test_ingestions_unknown_dataset(client: TestClient, owner: tuple[str, str]) -> None:
    """Nieistniejący dataset → code 102 w każdej z trzech tras odczytu."""
    token, user_id = owner
    unknown = uuid.uuid4().hex
    for path in (
        f"/api/v1/datasets/{unknown}/ingestions/summary",
        f"/api/v1/datasets/{unknown}/ingestions",
        f"/api/v1/datasets/{unknown}/ingestions/{unknown}",
    ):
        response = client.get(path, headers=_bearer(token))
        assert response.status_code == _OK, path
        payload = response.json()
        assert payload["code"] == _DATA_ERROR, path
        assert user_id in payload["message"], path


@pytest.mark.fakellm
async def test_embedding_check_happy_path(
    sm: async_sessionmaker[AsyncSession],
    settings: Settings,
    client: TestClient,
    owner: tuple[str, str],
) -> None:
    """POST …/embedding/check → wektor przeliczony równy zapisanemu (cos_sim 1.0, --10)."""
    token, _user_id = owner
    dataset_id, document_id, _log_id = await _seed_parsed(sm, client, token)
    await _seed_chunk(sm, settings, dataset_id, document_id)
    data = _data(
        client.post(
            f"/api/v1/datasets/{dataset_id}/embedding/check",
            json={"embd_id": _EMBEDDING_MODEL},
            headers=_bearer(token),
        )
    )
    golden = _golden_data("datasets___embedding__check/datasets_extras--10.json")
    assert set(data) == set(golden)
    summary = data["summary"]
    assert set(summary) == set(golden["summary"])
    assert summary["kb_id"] == dataset_id
    assert summary["sampled"] == 1 and summary["valid"] == 1
    assert summary["match_mode"] == "title+content"
    assert summary["avg_cos_sim"] == 1.0
    chunk = data["results"][0]
    assert set(chunk) == set(golden["results"][0])
    assert chunk["chunk_id"] == _CHUNK_ID
    assert chunk["doc_id"] == document_id
    assert chunk["doc_name"] == _DOC_NAME
    assert chunk["vector_field"] == "q_1024_vec"
    assert chunk["vector_dim"] == _EMBEDDING_DIM
    assert chunk["cos_sim"] == 1.0


async def test_embedding_check_requires_embd_id(client: TestClient, owner: tuple[str, str]) -> None:
    """Brak ``embd_id`` → code 102 „`embd_id` is required." (upstream dataset_api.py:1375)."""
    token, _user_id = owner
    dataset_id = str(create_dataset(client, token, {"name": "wd_emb_ds"})["id"])
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/embedding/check", json={}, headers=_bearer(token)
    )
    assert response.status_code == _OK
    payload = response.json()
    assert payload["code"] == _DATA_ERROR
    assert payload["message"] == "`embd_id` is required."


async def test_embedding_check_unknown_dataset(client: TestClient, owner: tuple[str, str]) -> None:
    """Nieistniejący dataset → code 102 (sprawdzenie dostępu przed re-embeddingiem)."""
    token, user_id = owner
    response = client.post(
        f"/api/v1/datasets/{uuid.uuid4().hex}/embedding/check",
        json={"embd_id": _EMBEDDING_MODEL},
        headers=_bearer(token),
    )
    assert response.status_code == _OK
    payload = response.json()
    assert payload["code"] == _DATA_ERROR
    assert user_id in payload["message"]


async def test_embedding_check_no_chunks(
    sm: async_sessionmaker[AsyncSession], client: TestClient, owner: tuple[str, str]
) -> None:
    """Dataset bez chunków → code 102 „No embedded chunks are available to compare."."""
    token, _user_id = owner
    dataset_id, _document_id, _log_id = await _seed_parsed(sm, client, token)
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/embedding/check",
        json={"embd_id": _EMBEDDING_MODEL},
        headers=_bearer(token),
    )
    assert response.status_code == _OK
    payload = response.json()
    assert payload["code"] == _DATA_ERROR
    assert payload["message"] == "No embedded chunks are available to compare."
