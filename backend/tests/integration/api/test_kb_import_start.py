"""Testy HTTP trasy 9 ``POST /api/wd/v1/dataset-imports/{id}/start`` (K19 §3, E7-1b-T6).

Zakres: walidacja nazwy i modelu docelowego (400), przejście ``ready`` → ``started`` i zlecenie
zadania ``import_dataset`` (payload z CONTRACT §3), ``reembed`` wg zgodności modelu z paczką,
konflikt nazwy u aktora (409 ``name_conflict``), stan inny niż ``ready`` (409 ``import_not_ready``),
uprawnienia (obcy → 404, superuser → 202) oraz atomowość przejścia (dwa równoległe ``start``).

Paczki buduje ``PackageWriter`` i przechodzą realny walidator (wzór: ``test_kb_import_routes``
i ``test_kb_import_summary``). Wektory niesie ``fmt.write_npy`` — bez numpy.
"""

from __future__ import annotations

import asyncio
import io
import json
import uuid
import zipfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.auth.principal import get_principal
from app.core.config import Settings
from app.core.container import Container
from app.core.timeutil import from_ms
from app.db.repositories import datasets as datasets_repo
from app.db.uow import transaction
from app.domain.policy import Principal
from app.main import create_app
from app.services.kb_package import format as fmt
from app.services.kb_package.writer import PackageWriter
from app.worker.queue import DbTaskQueue
from tests.integration.chat.conftest import seed_user
from tests.integration.datasets.conftest import exec_sql, seed_model
from tests.integration.ingest.pipeline_helpers import make_container
from tests.integration.retrieval.conftest import principal_for

pytestmark = pytest.mark.db

_HTTP_OK = 200
_HTTP_CREATED = 201
_HTTP_ACCEPTED = 202
_HTTP_BAD_REQUEST = 400
_HTTP_NOT_FOUND = 404
_HTTP_CONFLICT = 409
ID_HEX_LEN = 32

MAX_BYTES = 100 * 1024 * 1024
MAX_RATIO = 100
DIMENSION = 8  # model paczki testowej
OTHER_DIMENSION = 16  # model „inny niż paczki" dla reembed=true
MODEL_NAME = "fake-embed"
PACKAGE_NAME = "Baza importu"


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener ze magazynem w tmp_path i modelami fake-llm (wzorzec ``tests/integration/api``)."""
    instance = await make_container(migrated_db, tmp_path)
    yield instance
    await instance.aclose()


def _app(container: Container, principal: Principal | None) -> FastAPI:
    """Aplikacja na żywym kontenerze; ``principal=None`` → brak nadpisania."""
    app = create_app(container.settings, container)
    if principal is not None:
        app.dependency_overrides[get_principal] = lambda: principal
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    """Klient ASGI nad aplikacją testową."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _queue(container: Container) -> DbTaskQueue:
    """Kolejka na usługach kontenera (snapshot/claim)."""
    return DbTaskQueue(
        cast("async_sessionmaker[AsyncSession]", container.sessionmaker),
        container.clock,
        container.id_gen,
    )


# --- paczka testowa ------------------------------------------------------------------------


def _document() -> dict[str, Any]:
    """Linia ``documents.jsonl`` wg K19 §2 (bez pliku — ``file_sha256`` null)."""
    return {
        "ref": "d1",
        "name": "rocznik.txt",
        "type": "txt",
        "suffix": "txt",
        "size": 12,
        "file_sha256": None,
        "chunk_method": "naive",
        "parser_config": {},
        "meta_fields": {},
        "run": "3",  # DONE — run surowe (K19 §2)
        "progress_msg": "gotowe",
        "token_num": 10,
        "chunk_num": 1,
    }


def _chunk() -> dict[str, Any]:
    """Linia ``chunks.jsonl`` wg K19 §2 (jeden chunk dokumentu)."""
    return {
        "ref": "c1",
        "document_ref": "d1",
        "ordinal": 0,
        "chunk_type": "text",
        "content": "treść c1",
        "content_llm": None,
        "keywords": [],
        "questions": [],
        "tags": {},
        "positions": None,
        "page_from": None,
        "page_to": None,
        "image_sha256": None,
        "parent_ref": None,
        "available": True,
        "embed_source": None,
        "token_count": 10,
    }


def _jsonl(rows: list[dict[str, Any]]) -> bytes:
    """Wpis JSONL z listy słowników."""
    return b"".join(json.dumps(row, ensure_ascii=False).encode("utf-8") + b"\n" for row in rows)


def _npy(rows: list[list[float]], dimension: int = DIMENSION) -> bytes:
    """Wektory jako część ``.npy`` (NPY 1.0, '<f4', bez numpy)."""
    buf = io.BytesIO()
    fmt.write_npy(buf, rows, dimension)
    return buf.getvalue()


def _valid_package(
    tmp_path: Path,
    *,
    included: bool = True,
    model_name: str = MODEL_NAME,
    dimension: int = DIMENSION,
) -> bytes:
    """Paczka z jednym dokumentem, chunkiem i (opcjonalnie) wektorem; zwraca jej bajty."""
    path = tmp_path / "src.wdkb.zip"
    documents = [_document()]
    chunks = [_chunk()]
    blobs: dict[str, bytes] = {
        fmt.DOCUMENTS_PATH: _jsonl(documents),
        fmt.CHUNKS_PATH: _jsonl(chunks),
    }
    if included:
        blobs[fmt.vector_part_path(0)] = _npy([[0.0] * dimension for _ in chunks], dimension)
    writer = PackageWriter(path, max_bytes=MAX_BYTES)
    for entry_path, data in blobs.items():
        writer.add_bytes(entry_path, data)
    writer.finish(
        fmt.Manifest.model_validate(
            {
                "format": fmt.FORMAT_NAME,
                "schema_version": fmt.SCHEMA_VERSION,
                "wd_version": "0.9.0",
                "created_at": "2026-10-12T21:00:00Z",
                "source_instance_id": "0123456789abcdef0123456789abcdef",
                "dataset": {
                    "name": PACKAGE_NAME,
                    "description": None,
                    "language": "Polish",
                    "chunk_method": "naive",
                    "parser_config": {},
                    "similarity_threshold": 0.2,
                    "vector_similarity_weight": 0.3,
                    "pagerank": 0,
                },
                "embedding": {
                    "model_name": model_name,
                    "dimension": dimension,
                    "included": included,
                },
                "counts": {
                    "documents": len(documents),
                    "chunks": len(chunks),
                    "vectors": len(chunks) if included else 0,
                },
                "entries": [],
            }
        )
    )
    return path.read_bytes()


def _unsafe_path_package() -> bytes:
    """Paczka z wpisem ``../x`` — walidacja kończy sesję stanem ``invalid``."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", b"{}")
        archive.writestr("../x", b"zly wpis")
    return buffer.getvalue()


# --- wywołania HTTP ------------------------------------------------------------------------


async def _ready_session(
    client: httpx.AsyncClient,
    tmp_path: Path,
    *,
    model_name: str = MODEL_NAME,
    dimension: int = DIMENSION,
    included: bool = True,
) -> dict[str, Any]:
    """Zakłada sesję i wysyła całą paczkę jedną porcją; zwraca ``data`` (stan ``ready``)."""
    data = _valid_package(tmp_path, included=included, model_name=model_name, dimension=dimension)
    created = (
        await client.post(
            "/api/wd/v1/dataset-imports", json={"file_name": "k.wdkb.zip", "size_bytes": len(data)}
        )
    ).json()["data"]
    import_id = created["import_id"]
    response = await client.put(
        f"/api/wd/v1/dataset-imports/{import_id}/content",
        content=data,
        headers={
            "Content-Range": f"bytes 0-{len(data) - 1}/{len(data)}",
            "Content-Type": "application/octet-stream",
        },
    )
    assert response.status_code == _HTTP_OK, response.text
    assert response.json()["data"]["state"] == "ready"
    return {**response.json()["data"], "import_id": import_id}


async def _start(
    client: httpx.AsyncClient, import_id: str, *, name: str, embedding_model: str | None = None
) -> httpx.Response:
    """Wysyła ``POST .../start`` z podanym ciałem."""
    return await client.post(
        f"/api/wd/v1/dataset-imports/{import_id}/start",
        json={"name": name, "embedding_model": embedding_model},
    )


# --- trasa 9: sukces i reembed -------------------------------------------------------------


async def test_start_without_model_schedules_import(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """202 z ``TaskRef``; model z paczki (zgodny) → ``reembed=false``; sesja ``started``."""
    alice = await seed_user(sm)
    await seed_model(sm, MODEL_NAME, "embedding", dimension=DIMENSION, is_default=False)

    async with _client(_app(container, principal_for(alice))) as client:
        ready = await _ready_session(client, tmp_path)
        assert ready["summary"]["target"]["default_model"] == MODEL_NAME
        response = await _start(client, ready["import_id"], name="Import 2026")
        detail = (await client.get(f"/api/wd/v1/dataset-imports/{ready['import_id']}")).json()[
            "data"
        ]

    assert response.status_code == _HTTP_ACCEPTED, response.text
    task_ref = response.json()["data"]
    assert task_ref["status"] == "queued"
    assert len(task_ref["task_id"]) == ID_HEX_LEN

    snapshot = await _queue(container).snapshot(task_ref["task_id"])
    assert snapshot is not None
    assert snapshot.task_type == "import_dataset"
    assert snapshot.payload["reembed"] is False
    assert snapshot.payload["embedding_model"] == MODEL_NAME
    assert snapshot.payload["import_id"] == ready["import_id"]
    assert snapshot.payload["actor_id"] == alice
    assert len(str(snapshot.payload["dataset_id"])) == ID_HEX_LEN

    assert detail["state"] == "started"
    assert detail["task_id"] == task_ref["task_id"]
    assert detail["summary"] is not None  # podsumowanie zachowane (set_state z summary)


async def test_start_without_model_uses_probed_dimension(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """DEC-342: świeży domyślny ``fake-embed-1024`` (``dimension NULL``) po sondzie zgodny z paczką.

    Po podsumowaniu (upload) sonda zapisuje wymiar 1024, więc start bez ``embedding_model``
    wybiera model domyślny zgodny z paczką → ``reembed=false`` (bez zbędnego reembeddingu).
    """
    alice = await seed_user(sm)
    # ``make_container`` zasiewa fake-embed-1024 jako domyślny embedding bez wymiaru (świeża inst.).
    async with _client(_app(container, principal_for(alice))) as client:
        ready = await _ready_session(client, tmp_path, model_name="fake-embed-1024", dimension=1024)
        assert ready["summary"]["target"]["default_model"] == "fake-embed-1024"
        assert ready["summary"]["target"]["models"] == [
            {"name": "fake-embed-1024", "dimension": 1024}
        ]
        response = await _start(client, ready["import_id"], name="Import świeży")

    assert response.status_code == _HTTP_ACCEPTED, response.text
    snapshot = await _queue(container).snapshot(response.json()["data"]["task_id"])
    assert snapshot is not None
    assert snapshot.payload["reembed"] is False
    assert snapshot.payload["embedding_model"] == "fake-embed-1024"


async def test_summary_probe_failure_keeps_session_ready(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """DEC-342 p. 3: błąd sondy nie psuje uploadu — sesja ``ready`` bez modelu, start → 400.

    Bramka nieosiągalna (URL z kluczem) → podsumowanie bez modelu i ``default_model=null``;
    start bez ``embedding_model`` zwraca ``embedding_model_required``.
    """
    alice = await seed_user(sm)
    await exec_sql(
        sm,
        "UPDATE models SET base_url = :url WHERE name = :name",
        url="http://sekret-probe-key@127.0.0.1:1/v1",
        name="fake-embed-1024",
    )

    async with _client(_app(container, principal_for(alice))) as client:
        ready = await _ready_session(client, tmp_path)  # state=ready mimo błędu sondy
        assert ready["summary"]["target"]["default_model"] is None
        assert ready["summary"]["target"]["models"] == []
        response = await _start(client, ready["import_id"], name="Bez modelu po błędzie")

    assert response.status_code == _HTTP_BAD_REQUEST, response.text
    assert response.json()["error"]["code"] == "embedding_model_required"


async def test_start_with_other_model_reembeds(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Model docelowy inny niż paczki (inny wymiar w DB) → ``reembed=true``."""
    alice = await seed_user(sm)
    await seed_model(sm, "alt-embed", "embedding", dimension=OTHER_DIMENSION, is_default=False)

    async with _client(_app(container, principal_for(alice))) as client:
        ready = await _ready_session(client, tmp_path)
        response = await _start(
            client, ready["import_id"], name="Import reembed", embedding_model="alt-embed"
        )

    assert response.status_code == _HTTP_ACCEPTED, response.text
    snapshot = await _queue(container).snapshot(response.json()["data"]["task_id"])
    assert snapshot is not None
    assert snapshot.payload["reembed"] is True
    assert snapshot.payload["embedding_model"] == "alt-embed"


async def test_start_without_target_model_is_required(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Brak modelu domyślnego i paczka niezgodna → 400 ``embedding_model_required``."""
    alice = await seed_user(sm)
    # Zdejmij domyślność jedynemu modelowi embeddingów (fake-embed-1024 z make_container).
    await exec_sql(sm, "UPDATE models SET is_default = 0 WHERE model_type = 'embedding'")

    async with _client(_app(container, principal_for(alice))) as client:
        ready = await _ready_session(client, tmp_path)
        assert ready["summary"]["target"]["default_model"] is None
        response = await _start(client, ready["import_id"], name="Bez modelu")

    assert response.status_code == _HTTP_BAD_REQUEST, response.text
    assert response.json()["error"]["code"] == "embedding_model_required"


async def test_start_with_unknown_model_is_unknown(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Zmyślona nazwa modelu → 400 ``embedding_model_unknown``."""
    alice = await seed_user(sm)

    async with _client(_app(container, principal_for(alice))) as client:
        ready = await _ready_session(client, tmp_path)
        response = await _start(
            client, ready["import_id"], name="Zły model", embedding_model="no-such-model"
        )

    assert response.status_code == _HTTP_BAD_REQUEST, response.text
    assert response.json()["error"]["code"] == "embedding_model_unknown"


@pytest.mark.parametrize("name", ["", "x" * 129])
async def test_start_rejects_invalid_name(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path, name: str
) -> None:
    """Nazwa poza 1..128 znaków → 400 ``validation_failed`` (K19 §3, trasa 9)."""
    alice = await seed_user(sm)

    async with _client(_app(container, principal_for(alice))) as client:
        ready = await _ready_session(client, tmp_path)
        response = await _start(client, ready["import_id"], name=name)

    assert response.status_code == _HTTP_BAD_REQUEST, response.text
    assert response.json()["error"]["code"] == "validation_failed"


async def test_start_with_taken_name_conflicts(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Nazwa zajęta u aktora (bez wielkości liter) → 409 ``name_conflict`` z propozycją."""
    alice = await seed_user(sm)
    existing = "Zajęta baza"
    async with transaction(cast("async_sessionmaker[AsyncSession]", container.sessionmaker)) as s:
        await datasets_repo.insert(
            s,
            id=uuid.uuid4().hex,
            tenant_id=alice,
            created_by=alice,
            name=existing,
            description=None,
            avatar=None,
            language="Polish",
            embedding_model=MODEL_NAME,
            embedding_dim=DIMENSION,
            permission="me",
            chunk_method="naive",
            parser_config={},
            now_ms=container.clock.now_ms(),
        )

    async with _client(_app(container, principal_for(alice))) as client:
        ready = await _ready_session(client, tmp_path)
        # Inna wielkość liter — kolacja ``uq_datasets_tenant_name_ci`` i tak wykrywa konflikt;
        # propozycja bazuje na nazwie z żądania (dosłownie), jak ``suggested_name`` w K19 §3.
        requested = existing.lower()
        response = await _start(client, ready["import_id"], name=requested)

    assert response.status_code == _HTTP_CONFLICT, response.text
    error = response.json()["error"]
    assert error["code"] == "name_conflict"
    date_str = from_ms(container.clock.now_ms()).strftime("%Y-%m-%d")
    assert error["details"]["suggested_name"] == f"{requested} (import {date_str})"


async def test_start_name_with_surrounding_spaces_is_not_a_conflict(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Spacje wiodące/końcowe nie tworzą konfliktu — unikat DB to ``LOWER(name)`` bez ``strip``.

    Konflikt liczy ten sam helper co ``_suggest_name``/``build_summary`` (MINOR T6), więc nazwa
    różniąca się od zajętej samymi spacjami przechodzi jak w ``uq_datasets_tenant_name_ci``.
    """
    alice = await seed_user(sm)
    existing = "Baza spacji"
    async with transaction(cast("async_sessionmaker[AsyncSession]", container.sessionmaker)) as s:
        await datasets_repo.insert(
            s,
            id=uuid.uuid4().hex,
            tenant_id=alice,
            created_by=alice,
            name=existing,
            description=None,
            avatar=None,
            language="Polish",
            embedding_model=MODEL_NAME,
            embedding_dim=DIMENSION,
            permission="me",
            chunk_method="naive",
            parser_config={},
            now_ms=container.clock.now_ms(),
        )

    async with _client(_app(container, principal_for(alice))) as client:
        ready = await _ready_session(client, tmp_path)
        response = await _start(client, ready["import_id"], name=f"  {existing.lower()}  ")

    assert response.status_code == _HTTP_ACCEPTED, response.text


# --- trasa 9: stan i atomowość -------------------------------------------------------------


async def test_start_twice_is_conflict(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Drugie ``start`` (sesja ``started``) → 409 ``import_not_ready`` z ``details.state``."""
    alice = await seed_user(sm)

    async with _client(_app(container, principal_for(alice))) as client:
        ready = await _ready_session(client, tmp_path)
        first = await _start(client, ready["import_id"], name="Import raz")
        second = await _start(client, ready["import_id"], name="Import dwa")

    assert first.status_code == _HTTP_ACCEPTED, first.text
    assert second.status_code == _HTTP_CONFLICT, second.text
    error = second.json()["error"]
    assert error["code"] == "import_not_ready"
    assert error["details"]["state"] == "started"


async def test_start_not_ready_states_are_conflict(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Sesja ``uploading`` i ``invalid`` → 409 ``import_not_ready`` z ``details.state``."""
    alice = await seed_user(sm)

    async with _client(_app(container, principal_for(alice))) as client:
        uploading = (
            await client.post(
                "/api/wd/v1/dataset-imports", json={"file_name": "k.wdkb.zip", "size_bytes": 2048}
            )
        ).json()["data"]
        from_uploading = await _start(client, uploading["import_id"], name="Za wcześnie")

        corrupt = _unsafe_path_package()
        created = (
            await client.post(
                "/api/wd/v1/dataset-imports",
                json={"file_name": "k.wdkb.zip", "size_bytes": len(corrupt)},
            )
        ).json()["data"]
        uploaded = await client.put(
            f"/api/wd/v1/dataset-imports/{created['import_id']}/content",
            content=corrupt,
            headers={
                "Content-Range": f"bytes 0-{len(corrupt) - 1}/{len(corrupt)}",
                "Content-Type": "application/octet-stream",
            },
        )
        assert uploaded.json()["data"]["state"] == "invalid"
        from_invalid = await _start(client, created["import_id"], name="Zepsuta")

    assert from_uploading.status_code == _HTTP_CONFLICT, from_uploading.text
    assert from_uploading.json()["error"]["details"]["state"] == "uploading"
    assert from_invalid.status_code == _HTTP_CONFLICT, from_invalid.text
    assert from_invalid.json()["error"]["details"]["state"] == "invalid"


async def test_parallel_start_one_wins(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Dwa równoległe ``start`` tej samej sesji: jedno 202, drugie 409 (CONTRACT §3)."""
    alice = await seed_user(sm)

    async with _client(_app(container, principal_for(alice))) as client:
        ready = await _ready_session(client, tmp_path)
        first, second = await asyncio.gather(
            _start(client, ready["import_id"], name="Równolegle A"),
            _start(client, ready["import_id"], name="Równolegle B"),
        )

    assert sorted((first.status_code, second.status_code)) == [_HTTP_ACCEPTED, _HTTP_CONFLICT]
    loser = second if second.status_code == _HTTP_CONFLICT else first
    assert loser.json()["error"]["code"] == "import_not_ready"


# --- uprawnienia ---------------------------------------------------------------------------


async def test_foreign_user_not_found_superuser_ok(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Obcy użytkownik → 404; superuser → 202 (K19 §Uprawnienia 6-10)."""
    owner = await seed_user(sm)
    stranger = await seed_user(sm)
    admin = await seed_user(sm)

    async with _client(_app(container, principal_for(owner))) as client:
        ready = await _ready_session(client, tmp_path)

    async with _client(_app(container, principal_for(stranger))) as client:
        foreign = await _start(client, ready["import_id"], name="Obcy")

    assert foreign.status_code == _HTTP_NOT_FOUND, foreign.text
    assert foreign.json()["error"]["code"] == "not_found"

    async with _client(_app(container, principal_for(admin, superuser=True))) as client:
        accepted = await _start(client, ready["import_id"], name="Admin")

    assert accepted.status_code == _HTTP_ACCEPTED, accepted.text
