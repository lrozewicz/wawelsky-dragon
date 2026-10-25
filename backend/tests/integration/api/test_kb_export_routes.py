"""Testy HTTP tras eksportu ``.wdkb.zip`` (K19 §3 trasy 1, 2 i 5; zadanie E7-1a-T1).

Zakres: podgląd (liczby z DB, szacunek wg CONTRACT §4), start (202 ``TaskRef`` + wiersz
``tasks`` ``export_dataset``, 409 ``export_in_progress``, 413 ``package_too_large``, wyścig dwóch
równoległych ``POST``), uprawnienia (właściciel/superuser OK, członek zespołu 403 ``forbidden``,
obcy 404) oraz pobranie podpisanym linkiem (200 ``application/zip``, 403 ``invalid_signature``,
410 ``export_expired``). Trasa 5 działa bez aktora — ``_app(container, None)`` i brak nagłówka.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.auth.principal import get_principal
from app.core.config import Settings
from app.core.container import Container
from app.db.repositories.chunks import chunk_id
from app.db.repositories.datasets import DatasetRow
from app.db.repositories.task_payload import patch_payload
from app.db.uow import transaction
from app.domain.policy import Principal
from app.main import create_app
from app.services.kb_export_link import (
    EXPORT_LINK_TTL_S,
    download_path,
    export_package_path,
    sign_export,
)
from app.worker.queue import DbTaskQueue, NewTask
from tests.integration.chat.conftest import seed_user
from tests.integration.ingest.conftest import seed_dataset
from tests.integration.ingest.pipeline_helpers import make_container
from tests.integration.retrieval.conftest import principal_for

pytestmark = pytest.mark.db

_WORKER_ID = "w:1:0"
_TIME_MS = 1_790_157_600_000
_TIME_DATE = "2026-09-27 00:00:00.000"
_SEED_TASK_ID = "a" * 32  # public_id użyty przy deterministycznych id chunków
_FILE_NAME = "korpus.wdkb.zip"

# Seed podglądu: 3 dokumenty, 7 chunków ``committed=1`` (dim 1536) + 1 niezacommitowany.
_DIM = 1536
_DOC_SIZES = (1000, 2000, 3000)
_CHUNK_CONTENT_LEN = 10
_COMMITTED_CHUNKS = 7
_UNCOMMITTED_CONTENT_LEN = 1000
_DEFAULT_MAX_BYTES = 2_147_483_648
_ID_HEX_LEN = 32
_MAX_ATTEMPTS = 3

_HTTP_OK = 200
_HTTP_ACCEPTED = 202
_HTTP_FORBIDDEN = 403
_HTTP_NOT_FOUND = 404
_HTTP_CONFLICT = 409
_HTTP_EXPIRED = 410
_HTTP_TOO_LARGE = 413

# Oczekiwane liczby podglądu (CONTRACT §4, model E7-H1/T5) z powyższego seedu.
# Bez wektorów = rozmiar plików (1:1) + tekst po DEFLATE (wsp. 0,25); wektory = chunki·dim·4
# + jeden nagłówek NPY (128 B, jedna część).
_FILE_BYTES = sum(_DOC_SIZES)
_CONTENT_BYTES = _COMMITTED_CHUNKS * _CHUNK_CONTENT_LEN
_ESTIMATED_BYTES = _FILE_BYTES + round(0.25 * _CONTENT_BYTES)
_ESTIMATED_WITH_VECTORS = _ESTIMATED_BYTES + _COMMITTED_CHUNKS * _DIM * 4 + 128


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener ze magazynem w tmp_path i modelami fake-llm (wzorzec tests/integration/api)."""
    instance = await make_container(migrated_db, tmp_path)
    yield instance
    await instance.aclose()


def _sm(container: Container) -> async_sessionmaker[AsyncSession]:
    """Fabryka sesji z kontenera (istnieje po ``start()``)."""
    sessionmaker = cast("async_sessionmaker[AsyncSession] | None", container.sessionmaker)
    assert sessionmaker is not None, "container nie wystartował"
    return sessionmaker


def _app(container: Container, principal: Principal | None) -> FastAPI:
    """Aplikacja na żywym kontenerze; ``principal=None`` → brak nadpisania (trasa bez aktora)."""
    app = create_app(container.settings, container)
    if principal is not None:
        app.dependency_overrides[get_principal] = lambda: principal
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    """Klient ASGI nad aplikacją testową (bez nagłówka Authorization)."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _queue(container: Container) -> DbTaskQueue:
    """Kolejka na usługach kontenera (enqueue/claim/complete/snapshot)."""
    return DbTaskQueue(_sm(container), container.clock, container.id_gen)


def _secret(container: Container) -> str:
    """Sekret linku pobrania — jak w usłudze (``settings.secret_key``)."""
    return container.settings.secret_key.get_secret_value()


# --- seed ----------------------------------------------------------------------------------------


async def _insert_document(
    sm: async_sessionmaker[AsyncSession], dataset_id: str, name: str, size: int
) -> str:
    """Wstawia dokument (suwaki surowe SQL) i zwraca jego id."""
    document_id = uuid.uuid4().hex
    suffix = name.rsplit(".", 1)[-1]
    async with transaction(sm) as session:
        await session.execute(
            text(
                "INSERT INTO documents (id, dataset_id, created_by, name, suffix, type, size,"
                " location, content_hash, chunk_method, parser_config, create_time, create_date,"
                " update_time, update_date)"
                " VALUES (:id, :ds, :ds, :name, :suffix, 'doc', :size, :location, '', 'naive',"
                " '{}', :time_ms, :time, :time_ms, :time)"
            ),
            {
                "id": document_id,
                "ds": dataset_id,
                "name": name,
                "suffix": suffix,
                "size": size,
                "location": f"{dataset_id}/{document_id}.{suffix}",
                "time_ms": _TIME_MS,
                "time": _TIME_DATE,
            },
        )
    return document_id


async def _insert_chunk(  # noqa: PLR0913 — pełny wiersz chunka seedu
    sm: async_sessionmaker[AsyncSession],
    dataset_id: str,
    document_id: str,
    ordinal: int,
    content: str,
    *,
    committed: bool,
) -> None:
    """Wstawia chunk z jawnym ``committed`` (podgląd liczy tylko ``committed=1``)."""
    async with transaction(sm) as session:
        await session.execute(
            text(
                "INSERT INTO chunks (id, document_id, dataset_id, ordinal, chunk_type, content,"
                " content_ft, committed, available, create_time, create_date, update_time,"
                " update_date)"
                " VALUES (:id, :doc, :ds, :ordinal, 'text', :content, :content_ft, :committed, 1,"
                " :time_ms, :time, :time_ms, :time)"
            ),
            {
                "id": chunk_id(document_id, _SEED_TASK_ID, ordinal),
                "doc": document_id,
                "ds": dataset_id,
                "ordinal": ordinal,
                "content": content,
                "content_ft": content,
                "committed": 1 if committed else 0,
                "time_ms": _TIME_MS,
                "time": _TIME_DATE,
            },
        )


async def _seed_dataset(
    sm: async_sessionmaker[AsyncSession], *, permission: str = "me"
) -> DatasetRow:
    """Dataset właściciela z 3 dokumentami i 7 chunktami ``committed=1`` (K19 §2/§4)."""
    record = await seed_dataset(sm, embedding_model="fake-embed-1024", embedding_dim=_DIM)
    if permission != "me":
        await _set_permission(sm, record.id, permission)
    doc_ids = [
        await _insert_document(sm, record.id, f"dok-{i}.txt", size)
        for i, size in enumerate(_DOC_SIZES, start=1)
    ]
    for ordinal in range(_COMMITTED_CHUNKS):
        await _insert_chunk(
            sm, record.id, doc_ids[0], ordinal, "x" * _CHUNK_CONTENT_LEN, committed=True
        )
    await _insert_chunk(
        sm,
        record.id,
        doc_ids[0],
        _COMMITTED_CHUNKS,
        "y" * _UNCOMMITTED_CONTENT_LEN,
        committed=False,
    )
    return record


async def _set_permission(
    sm: async_sessionmaker[AsyncSession], dataset_id: str, permission: str
) -> None:
    """Ustawia ``datasets.permission`` (``team`` → członek zespołu ma READ)."""
    async with transaction(sm) as session:
        await session.execute(
            text("UPDATE datasets SET permission = :p WHERE id = :id"),
            {"p": permission, "id": dataset_id},
        )


def _enqueue_export(container: Container, dataset_id: str, owner_id: str) -> Any:
    """Zleca zadanie ``export_dataset`` datasetu (zwraca korutynę ``enqueue``)."""
    return _queue(container).enqueue(
        NewTask(
            "export_dataset",
            {"actor_id": owner_id, "include_vectors": True},
            dataset_id=dataset_id,
        )
    )


async def _claim_done_export(container: Container, task_id: str) -> None:
    """Domyka zadanie eksportu: claim → ``payload.result`` → ``done`` (plik zakłada test)."""
    queue = _queue(container)
    task = await queue.claim(_WORKER_ID, ["export_dataset"])
    assert task is not None and task.id == task_id, task
    exp = container.clock.now_ms() // 1000 + EXPORT_LINK_TTL_S
    sig = sign_export(_secret(container), task_id, exp)
    result: dict[str, Any] = {
        "download_url": download_path(task_id, exp, sig),
        "expires_at": exp * 1000,
        "size_bytes": 0,
        "file_name": _FILE_NAME,
    }
    async with transaction(_sm(container)) as session:
        await patch_payload(
            session, public_id=task_id, patch={"result": result}, now_ms=container.clock.now_ms()
        )
    await queue.complete(task_id, _WORKER_ID)


async def _make_done_export(
    container: Container,
    dataset_id: str,
    *,
    size: int = 2048,
    write_file: bool = True,
) -> tuple[str, int, str, bytes]:
    """Zadanie ``done`` z wynikiem i (opcjonalnie) plikiem; zwraca ``(id, exp, sig, bajty)``."""
    task_id = await _enqueue_export(container, dataset_id, "o" * _ID_HEX_LEN)
    await _claim_done_export(container, task_id)
    data = b"PK\x03\x04" + b"x" * (size - 4)
    if write_file:
        path = export_package_path(container.settings.storage_root, task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    exp = container.clock.now_ms() // 1000 + EXPORT_LINK_TTL_S
    sig = sign_export(_secret(container), task_id, exp)
    return task_id, exp, sig, data


async def _task_row_count(container: Container, dataset_id: str) -> int:
    """Liczba zadań ``export_dataset`` tego datasetu (dowód pojedynczego startu)."""
    async with transaction(_sm(container)) as session:
        found = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM tasks WHERE task_type = 'export_dataset'"
                    " AND dataset_id = :ds"
                ),
                {"ds": dataset_id},
            )
        ).scalar_one()
    return int(found)


# --- trasa 1: podgląd ----------------------------------------------------------------------------


async def test_preview_owner_returns_the_contract_shape(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Właściciel: 200 ``ExportPreview`` z liczbami z DB i szacunkiem wg CONTRACT §4."""
    dataset = await _seed_dataset(sm)

    async with _client(_app(container, principal_for(dataset.tenant_id))) as client:
        response = await client.get(f"/api/wd/v1/datasets/{dataset.id}/export/preview")

    assert response.status_code == _HTTP_OK, response.text
    data = response.json()["data"]
    assert set(data) == {
        "dataset_id",
        "name",
        "documents",
        "chunks",
        "estimated_bytes",
        "estimated_bytes_with_vectors",
        "embedding",
        "max_bytes",
    }
    assert (data["dataset_id"], data["documents"], data["chunks"]) == (
        dataset.id,
        len(_DOC_SIZES),
        _COMMITTED_CHUNKS,
    )
    assert data["embedding"]["dimension"] == _DIM
    assert data["estimated_bytes"] == _ESTIMATED_BYTES
    assert data["estimated_bytes_with_vectors"] == _ESTIMATED_WITH_VECTORS
    assert data["estimated_bytes_with_vectors"] > data["estimated_bytes"]
    assert data["max_bytes"] == _DEFAULT_MAX_BYTES


async def test_preview_team_member_is_forbidden(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Członek zespołu (``permission=team``, READ tak) nie eksportuje: 403 ``forbidden``."""
    dataset = await _seed_dataset(sm, permission="team")
    member_id = await seed_user(sm)

    async with _client(_app(container, principal_for(member_id))) as client:
        response = await client.get(f"/api/wd/v1/datasets/{dataset.id}/export/preview")

    assert response.status_code == _HTTP_FORBIDDEN, response.text
    assert response.json()["error"]["code"] == "forbidden"


async def test_preview_stranger_gets_not_found(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Obcy bez dostępu (dataset ``permission=me``): 404 ``not_found`` (nie zdradzamy istnienia)."""
    dataset = await _seed_dataset(sm)
    stranger_id = await seed_user(sm)

    async with _client(_app(container, principal_for(stranger_id))) as client:
        response = await client.get(f"/api/wd/v1/datasets/{dataset.id}/export/preview")

    assert response.status_code == _HTTP_NOT_FOUND, response.text
    assert response.json()["error"]["code"] == "not_found"


async def test_preview_missing_dataset_gets_not_found(container: Container) -> None:
    """Nieznany dataset: 404 ``not_found``."""
    async with _client(_app(container, principal_for(uuid.uuid4().hex))) as client:
        response = await client.get(f"/api/wd/v1/datasets/{uuid.uuid4().hex}/export/preview")
    assert response.status_code == _HTTP_NOT_FOUND, response.text


async def test_preview_superuser_is_allowed(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Superuser eksportuje cudzy dataset: 200 (K19 §Uprawnienia 1-2)."""
    dataset = await _seed_dataset(sm)

    async with _client(_app(container, principal_for(uuid.uuid4().hex, superuser=True))) as client:
        response = await client.get(f"/api/wd/v1/datasets/{dataset.id}/export/preview")

    assert response.status_code == _HTTP_OK, response.text


# --- trasa 2: start ------------------------------------------------------------------------------


async def test_start_owner_queues_the_export_task(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Właściciel: 202 ``TaskRef`` i wiersz ``tasks`` ``export_dataset`` (``queued``)."""
    dataset = await _seed_dataset(sm)

    async with _client(_app(container, principal_for(dataset.tenant_id))) as client:
        response = await client.post(
            f"/api/wd/v1/datasets/{dataset.id}/export", json={"include_vectors": True}
        )

    assert response.status_code == _HTTP_ACCEPTED, response.text
    data = response.json()["data"]
    assert set(data) == {"task_id", "status"}
    assert data["status"] == "queued"
    task_id = data["task_id"]
    assert len(task_id) == _ID_HEX_LEN
    async with transaction(sm) as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT task_type, dataset_id, status, payload, max_attempts"
                        " FROM tasks WHERE public_id = :id"
                    ),
                    {"id": task_id},
                )
            )
            .mappings()
            .one()
        )
    assert row["task_type"] == "export_dataset"
    assert row["dataset_id"] == dataset.id
    assert row["status"] == "queued"
    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    assert payload["actor_id"] == dataset.tenant_id
    assert payload["include_vectors"] is True
    assert int(row["max_attempts"]) == _MAX_ATTEMPTS


async def test_start_include_vectors_false_is_recorded(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """``include_vectors: false`` trafia do payloadu zadania (K19 §3, trasa 2)."""
    dataset = await _seed_dataset(sm)

    async with _client(_app(container, principal_for(dataset.tenant_id))) as client:
        response = await client.post(
            f"/api/wd/v1/datasets/{dataset.id}/export", json={"include_vectors": False}
        )

    assert response.status_code == _HTTP_ACCEPTED, response.text
    snapshot = await _queue(container).snapshot(response.json()["data"]["task_id"])
    assert snapshot is not None
    assert snapshot.payload["include_vectors"] is False


async def test_start_team_member_is_forbidden(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Członek zespołu: 403 ``forbidden`` (brief, przykład wejście→wyjście)."""
    dataset = await _seed_dataset(sm, permission="team")
    member_id = await seed_user(sm)

    async with _client(_app(container, principal_for(member_id))) as client:
        response = await client.post(f"/api/wd/v1/datasets/{dataset.id}/export", json={})

    assert response.status_code == _HTTP_FORBIDDEN, response.text
    assert response.json()["error"]["code"] == "forbidden"


async def test_start_stranger_gets_not_found(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Obcy bez dostępu: 404 ``not_found``."""
    dataset = await _seed_dataset(sm)
    stranger_id = await seed_user(sm)

    async with _client(_app(container, principal_for(stranger_id))) as client:
        response = await client.post(f"/api/wd/v1/datasets/{dataset.id}/export", json={})

    assert response.status_code == _HTTP_NOT_FOUND, response.text


async def test_start_while_another_export_is_queued_conflicts(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Zadanie ``queued`` dla datasetu: 409 ``export_in_progress`` z ``details.task_id``."""
    dataset = await _seed_dataset(sm)
    first = await _enqueue_export(container, dataset.id, dataset.tenant_id)

    async with _client(_app(container, principal_for(dataset.tenant_id))) as client:
        response = await client.post(f"/api/wd/v1/datasets/{dataset.id}/export", json={})

    assert response.status_code == _HTTP_CONFLICT, response.text
    error = response.json()["error"]
    assert error["code"] == "export_in_progress"
    assert error["details"]["task_id"] == first


async def test_start_race_accepts_exactly_one(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Dwa równoległe ``POST``: dokładnie jedno 202, drugie 409; jeden wiersz zadania."""
    dataset = await _seed_dataset(sm)
    url = f"/api/wd/v1/datasets/{dataset.id}/export"

    async with _client(_app(container, principal_for(dataset.tenant_id))) as client:
        first, second = await asyncio.gather(client.post(url, json={}), client.post(url, json={}))

    assert sorted([first.status_code, second.status_code]) == [_HTTP_ACCEPTED, _HTTP_CONFLICT]
    assert await _task_row_count(container, dataset.id) == 1


async def test_start_package_too_large_is_rejected(
    migrated_db: Settings, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Szacunek > ``export_max_bytes``: 413 ``package_too_large`` (limit ze Settings)."""
    dataset = await _seed_dataset(sm)
    small = await make_container(migrated_db, tmp_path, settings_overrides={"export_max_bytes": 16})
    try:
        async with _client(_app(small, principal_for(dataset.tenant_id))) as client:
            response = await client.post(f"/api/wd/v1/datasets/{dataset.id}/export", json={})
    finally:
        await small.aclose()

    assert response.status_code == _HTTP_TOO_LARGE, response.text
    assert response.json()["error"]["code"] == "package_too_large"


# --- trasa 5: pobranie ---------------------------------------------------------------------------


async def test_download_valid_link_streams_the_package(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Poprawny link bez aktora: 200 ``application/zip`` z nazwą, długością i bajtami pliku."""
    dataset = await _seed_dataset(sm)
    task_id, exp, sig, data = await _make_done_export(container, dataset.id)

    async with _client(_app(container, None)) as client:
        response = await client.get(
            f"/api/wd/v1/exports/{task_id}/download", params={"exp": exp, "sig": sig}
        )

    assert response.status_code == _HTTP_OK, response.text
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-disposition"] == f'attachment; filename="{_FILE_NAME}"'
    assert response.headers["content-length"] == str(len(data))
    assert response.content == data
    assert "set-cookie" not in response.headers


async def test_download_bad_signature_is_forbidden(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Zły ``sig``: 403 ``invalid_signature`` (bez ujawniania czegokolwiek)."""
    dataset = await _seed_dataset(sm)
    task_id, exp, _sig, _data = await _make_done_export(container, dataset.id)

    async with _client(_app(container, None)) as client:
        response = await client.get(
            f"/api/wd/v1/exports/{task_id}/download", params={"exp": exp, "sig": "0" * 64}
        )

    assert response.status_code == _HTTP_FORBIDDEN, response.text
    assert response.json()["error"]["code"] == "invalid_signature"


async def test_download_changed_exp_is_forbidden(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Podpis pasuje do innego ``exp``: 403 ``invalid_signature``."""
    dataset = await _seed_dataset(sm)
    task_id, exp, sig, _data = await _make_done_export(container, dataset.id)

    async with _client(_app(container, None)) as client:
        response = await client.get(
            f"/api/wd/v1/exports/{task_id}/download", params={"exp": exp + 1, "sig": sig}
        )

    assert response.status_code == _HTTP_FORBIDDEN, response.text


async def test_download_missing_params_is_forbidden(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Brak ``exp``/``sig``: 403 ``invalid_signature``."""
    dataset = await _seed_dataset(sm)
    task_id, _exp, _sig, _data = await _make_done_export(container, dataset.id)

    async with _client(_app(container, None)) as client:
        without_sig = await client.get(f"/api/wd/v1/exports/{task_id}/download")
        only_sig = await client.get(
            f"/api/wd/v1/exports/{task_id}/download", params={"sig": "0" * 64}
        )

    assert without_sig.status_code == _HTTP_FORBIDDEN, without_sig.text
    assert without_sig.json()["error"]["code"] == "invalid_signature"
    assert only_sig.status_code == _HTTP_FORBIDDEN, only_sig.text


async def test_download_expired_link_is_gone(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Poprawny podpis, ``exp`` w przeszłości: 410 ``export_expired``."""
    dataset = await _seed_dataset(sm)
    task_id, _exp, _sig, _data = await _make_done_export(container, dataset.id)
    past = container.clock.now_ms() // 1000 - 10
    sig = sign_export(_secret(container), task_id, past)

    async with _client(_app(container, None)) as client:
        response = await client.get(
            f"/api/wd/v1/exports/{task_id}/download", params={"exp": past, "sig": sig}
        )

    assert response.status_code == _HTTP_EXPIRED, response.text
    assert response.json()["error"]["code"] == "export_expired"


async def test_download_missing_file_is_gone(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Zadanie ``done``, ale plik usunięty: 410 ``export_expired``."""
    dataset = await _seed_dataset(sm)
    task_id, exp, sig, _data = await _make_done_export(container, dataset.id, write_file=False)

    async with _client(_app(container, None)) as client:
        response = await client.get(
            f"/api/wd/v1/exports/{task_id}/download", params={"exp": exp, "sig": sig}
        )

    assert response.status_code == _HTTP_EXPIRED, response.text


async def test_download_unfinished_task_is_gone(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Zadanie wciąż ``queued`` (i nieznane id): 410 ``export_expired``."""
    dataset = await _seed_dataset(sm)
    task_id = await _enqueue_export(container, dataset.id, "o" * _ID_HEX_LEN)
    exp = container.clock.now_ms() // 1000 + EXPORT_LINK_TTL_S
    sig = sign_export(_secret(container), task_id, exp)
    unknown = uuid.uuid4().hex
    unknown_sig = sign_export(_secret(container), unknown, exp)

    async with _client(_app(container, None)) as client:
        queued = await client.get(
            f"/api/wd/v1/exports/{task_id}/download", params={"exp": exp, "sig": sig}
        )
        missing_task = await client.get(
            f"/api/wd/v1/exports/{unknown}/download", params={"exp": exp, "sig": unknown_sig}
        )

    assert queued.status_code == _HTTP_EXPIRED, queued.text
    assert missing_task.status_code == _HTTP_EXPIRED, missing_task.text


async def test_download_task_of_another_type_is_gone(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Zadanie ``done`` innego typu niż ``export_dataset``: 410 ``export_expired`` (K19 §3 trasa 5).

    Plik paczki leży pod ``exports/<task_id>.wdkb.zip``, więc 410 nie może pochodzić z jego braku —
    rozstrzyga typ zadania (``KbExportService._download_file_name``). Bez tego warunku podpisany
    link do cudzego zadania odsłoniłby plik o tej samej nazwie w ``exports/``.
    """
    dataset = await _seed_dataset(sm)
    queue = _queue(container)
    task_id = await queue.enqueue(
        NewTask("parse_document", {"actor_id": dataset.tenant_id}, dataset_id=dataset.id)
    )
    task = await queue.claim(_WORKER_ID, ["parse_document"])
    assert task is not None and task.id == task_id, task
    exp = container.clock.now_ms() // 1000 + EXPORT_LINK_TTL_S
    sig = sign_export(_secret(container), task_id, exp)
    result: dict[str, Any] = {
        "download_url": download_path(task_id, exp, sig),
        "expires_at": exp * 1000,
        "size_bytes": 0,
        "file_name": _FILE_NAME,
    }
    async with transaction(_sm(container)) as session:
        await patch_payload(
            session, public_id=task_id, patch={"result": result}, now_ms=container.clock.now_ms()
        )
    await queue.complete(task_id, _WORKER_ID)
    path = export_package_path(container.settings.storage_root, task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"PK\x03\x04" + b"x" * 12)

    async with _client(_app(container, None)) as client:
        response = await client.get(
            f"/api/wd/v1/exports/{task_id}/download", params={"exp": exp, "sig": sig}
        )

    assert path.is_file(), "plik istnieje — 410 musi wynikać z typu zadania, nie z braku pliku"
    assert response.status_code == _HTTP_EXPIRED, response.text
    assert response.json()["error"]["code"] == "export_expired"
