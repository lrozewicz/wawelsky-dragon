"""Test integracyjny CAŁEGO przepływu importu paczki ``.wdkb.zip`` przez HTTP (K19 R-KB-02).

Zakres (brief E7-1b-T8): sesja → upload porcjami ``Content-Range`` (z przerwaniem i wznowieniem
od ``details.received_bytes``) → walidacja ``ready`` → ``start`` → wykonanie handlera jak
w workerze (``KB_HANDLERS``) → ``GET /tasks/{id}`` ``done`` → stan datasetu, wektory w
``chunk_vec_d<dim>`` i retrieval przez ``POST /api/v1/retrieval``; wariant reembed (inny wymiar
modelu docelowego), wariant złośliwy (``../x`` → ``unsafe_path``) oraz wariant „drugi użytkownik”
(sesja i dataset niewidoczne dla obcego aktora).

Całość na jednym event loop (httpx ASGITransport + kontener bez lifespan), na MariaDB i fake-llm.
Paczki buduje realny ``PackageWriter`` i przechodzą realny walidator (E7-1f) — tak samo jak
w ``test_kb_import_routes``/``test_kb_import_start``; zadanie importu wykonujemy claimem
z ``DbTaskQueue`` i wywołaniem handlera z ``KB_HANDLERS`` (wzorzec ``test_kb_import_handler``).
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import zipfile
from collections.abc import AsyncIterator, Mapping, Sequence
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
from app.core.error_codes import RetCode
from app.db.uow import transaction
from app.domain.policy import Principal
from app.main import create_app
from app.services.kb_package import format as fmt
from app.services.kb_package.writer import PackageWriter
from app.worker.context import TaskContext
from app.worker.kb_handlers import KB_HANDLERS
from app.worker.queue import DbTaskQueue, TaskRow
from tests.integration.chat.conftest import seed_user
from tests.integration.datasets.conftest import exec_sql
from tests.integration.ingest.pipeline_helpers import make_container
from tests.integration.retrieval.conftest import principal_for

pytestmark = [pytest.mark.db, pytest.mark.fakellm]

MAX_BYTES = 100 * 1024 * 1024
MAX_RATIO = 100
DIM = 1024  # fake-embed-1024 — model paczki 1:1 i model docelowy reembed
SOURCE_DIM = 3072  # fake-embed-3072 — model paczki w wariancie reembed
EMBED_MODEL = "fake-embed-1024"
PACKAGE_MODEL = "fake-embed-3072"
CHUNK = 4096  # rozmiar porcji uploadu w testach (paczka cięta po ~4 KB)
PACKAGE_CHUNKS = 12  # chunki w paczce (K19 R-KB-02, brief p. 1)
TOKEN_COUNT = 3  # token_count każdego chunka → estimated_reembed_tokens = 36
DOCUMENTS = 2
COMP = 1.0 / 32.0  # 1/sqrt(1024) — składowa znormalizowanego wektora „z paczki"
FLOAT_TOLERANCE = 1e-6  # tolerancja porównania wektora float32 z paczki
MIN_PIECES = 3  # minimalna liczba porcji paczki (pokazuje wznowienie uploadu)
WORKER_ID = "flow-host:1:0"
PACKAGE_NAME = "Rocznik GUS"
IMPORT_NAME = "Import rocznika"
UNIQUE_WORD = "kwarcowy-wzorzec"  # słowo unikatowe chunka z edytowaną treścią
DISABLED_WORD = "znacznikwylaczony"  # słowo chunka wyłączonego (available=false)
PARSER_CONFIG: dict[str, Any] = {"chunk_token_num": 128, "delimiter": "\n"}
DOC_BLOB_1 = os.urandom(20_000)  # nieściśliwy plik → paczka ma co najmniej kilka porcji
DOC_BLOB_2 = os.urandom(20_000)
IMAGE_DATA = b"\x89PNG\r\n\x1a\n obraz chunka importu"
ID_HEX_LEN = 32
_HTTP_OK = 200
_HTTP_CREATED = 201
_HTTP_ACCEPTED = 202
_HTTP_NOT_FOUND = 404
_HTTP_CONFLICT = 409


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener ze magazynem w tmp_path i modelami fake-llm (wzorzec ``tests/integration/api``)."""
    instance = await make_container(migrated_db, tmp_path)
    yield instance
    await instance.aclose()


async def _models(sm: async_sessionmaker[AsyncSession]) -> None:
    """Wymiar modelu domyślnego ``fake-embed-1024`` (make_container wpisuje go bez wymiaru)."""
    await exec_sql(sm, "UPDATE models SET dimension = 1024 WHERE name = 'fake-embed-1024'")


def _app(container: Container, principal: Principal | None) -> FastAPI:
    """Aplikacja na żywym kontenerze; ``principal=None`` → brak nadpisania (ścieżka 401)."""
    app = create_app(container.settings, container)
    if principal is not None:
        app.dependency_overrides[get_principal] = lambda: principal
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    """Klient ASGI nad aplikacją testową (jeden event loop, jak w ``test_kb_import_routes``)."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _queue(container: Container) -> DbTaskQueue:
    """Kolejka na usługach kontenera (enqueue/claim/complete)."""
    return DbTaskQueue(
        cast("async_sessionmaker[AsyncSession]", container.sessionmaker),
        container.clock,
        container.id_gen,
    )


# --- builder paczki K19 R-KB-02 --------------------------------------------------------------


def _document(ref: str, name: str, blob: bytes) -> dict[str, Any]:
    """Linia ``documents.jsonl`` wg K19 §2 (dokument z plikiem, ``run`` DONE = "3")."""
    return {
        "ref": ref,
        "name": name,
        "type": "pdf",
        "suffix": "pdf",
        "size": len(blob),
        "file_sha256": hashlib.sha256(blob).hexdigest(),
        "chunk_method": "naive",
        "parser_config": PARSER_CONFIG,
        "meta_fields": {"tag": ref},
        "run": "3",  # DONE — run surowe (K19 §2)
        "progress_msg": "gotowe",
        "token_num": 10,
        "chunk_num": PACKAGE_CHUNKS // DOCUMENTS,
    }


def _chunk(ref: str, document_ref: str, ordinal: int, **overrides: Any) -> dict[str, Any]:
    """Linia ``chunks.jsonl`` wg K19 §2; pola nadpisywane przez ``overrides``."""
    row: dict[str, Any] = {
        "ref": ref,
        "document_ref": document_ref,
        "ordinal": ordinal,
        "chunk_type": "text",
        "content": f"Treść rocznika GUS w chunku {ref}.",
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
        "embed_source": "content",
        "token_count": TOKEN_COUNT,
    }
    row.update(overrides)
    return row


def _package_chunks() -> list[dict[str, Any]]:
    """12 chunków dwóch dokumentów: jeden wyłączony, jeden z edytowaną treścią, jeden z obrazem."""
    chunks: list[dict[str, Any]] = []
    for index in range(PACKAGE_CHUNKS):
        ref = f"c{index + 1}"
        document_ref = "d1" if index < PACKAGE_CHUNKS // DOCUMENTS else "d2"
        overrides: dict[str, Any] = {}
        if ref == "c5":
            overrides = {"available": False, "content": f"Fragment wyłączony: {DISABLED_WORD}."}
        elif ref == "c7":
            overrides = {
                "content": f"Dokument testowy zawiera słowo {UNIQUE_WORD} do sprawdzenia.",
                "keywords": [UNIQUE_WORD],
            }
        elif ref == "c9":
            overrides = {"image_sha256": hashlib.sha256(IMAGE_DATA).hexdigest()}
        chunks.append(_chunk(ref, document_ref, index, **overrides))
    return chunks


def _jsonl(rows: Sequence[Mapping[str, Any]]) -> bytes:
    """Wpis JSONL z linii modelu."""
    return b"".join(
        json.dumps(dict(row), ensure_ascii=False).encode("utf-8") + b"\n" for row in rows
    )


def _npy(rows: list[list[float]], dim: int) -> bytes:
    """Wektory jako wpis ``vectors/000000.npy`` (NPY 1.0, '<f4', bez numpy)."""
    buffer = io.BytesIO()
    fmt.write_npy(buffer, rows, dim)
    return buffer.getvalue()


def _manifest(*, model_name: str, dim: int, included: bool) -> fmt.Manifest:
    """Manifest paczki testowej (K19 §2) z licznikami R-KB-02."""
    return fmt.Manifest.model_validate(
        {
            "format": fmt.FORMAT_NAME,
            "schema_version": fmt.SCHEMA_VERSION,
            "wd_version": "0.9.0",
            "created_at": "2026-10-12T21:00:00Z",
            "source_instance_id": "0123456789abcdef0123456789abcdef",
            "dataset": {
                "name": PACKAGE_NAME,
                "description": "opis źródła",
                "language": "Polish",
                "chunk_method": "naive",
                "parser_config": PARSER_CONFIG,
                "similarity_threshold": 0.35,
                "vector_similarity_weight": 0.45,
                "pagerank": 2,
            },
            "embedding": {"model_name": model_name, "dimension": dim, "included": included},
            "counts": {
                "documents": DOCUMENTS,
                "chunks": PACKAGE_CHUNKS,
                "vectors": PACKAGE_CHUNKS if included else 0,
            },
            "entries": [],
        }
    )


def _valid_package(tmp_path: Path, *, model_name: str = EMBED_MODEL, dim: int = DIM) -> bytes:
    """Paczka K19 R-KB-02: 2 dokumenty z plikami, 12 chunków, wektory stałe „z paczki".

    Wektory każdego chunka to ten sam, znormalizowany wektor o składowej ``1/sqrt(dim)`` —
    dzięki temu odczytany z ``chunk_vec_d<dim>`` wektor daje się porównać z paczką.
    """
    path = tmp_path / "src.wdkb.zip"
    chunks = _package_chunks()
    vectors = [[COMP] * dim for _ in chunks]
    writer = PackageWriter(path, max_bytes=MAX_BYTES)
    writer.add_bytes(
        fmt.DOCUMENTS_PATH,
        _jsonl(
            [
                _document("d1", "rocznik-1.pdf", DOC_BLOB_1),
                _document("d2", "rocznik-2.pdf", DOC_BLOB_2),
            ]
        ),
    )
    writer.add_bytes(fmt.CHUNKS_PATH, _jsonl(chunks))
    writer.add_bytes(fmt.vector_part_path(0), _npy(vectors, dim))
    writer.add_bytes(f"{fmt.FILES_PREFIX}{hashlib.sha256(DOC_BLOB_1).hexdigest()}", DOC_BLOB_1)
    writer.add_bytes(f"{fmt.FILES_PREFIX}{hashlib.sha256(DOC_BLOB_2).hexdigest()}", DOC_BLOB_2)
    writer.add_bytes(f"{fmt.IMAGES_PREFIX}{hashlib.sha256(IMAGE_DATA).hexdigest()}", IMAGE_DATA)
    writer.finish(_manifest(model_name=model_name, dim=dim, included=True))
    return path.read_bytes()


def _raw_zip(entries: Mapping[str, bytes]) -> bytes:
    """Archiwum ZIP z podanych wpisów (kolejność zachowana) — do paczek złośliwych."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _unsafe_path_package() -> bytes:
    """Paczka z wpisem ``../x`` — walidacja kończy sesję kodem ``unsafe_path``."""
    return _raw_zip({"manifest.json": b"{}", "../x": b"zly wpis"})


# --- wywołania HTTP ---------------------------------------------------------------------------


def _pieces(data: bytes) -> list[tuple[int, int, bytes]]:
    """Paczka pocięta na porcje ``CHUNK``: ``(start, end, bajty)``."""
    result: list[tuple[int, int, bytes]] = []
    for offset in range(0, len(data), CHUNK):
        piece = data[offset : offset + CHUNK]
        result.append((offset, offset + len(piece) - 1, piece))
    return result


async def _put(  # noqa: PLR0913 — zakres i porcja odwzorowują nagłówek Content-Range
    client: httpx.AsyncClient, import_id: str, *, total: int, start: int, end: int, piece: bytes
) -> httpx.Response:
    """Wysyła porcję z nagłówkiem ``Content-Range``."""
    return await client.put(
        f"/api/wd/v1/dataset-imports/{import_id}/content",
        content=piece,
        headers={
            "Content-Range": f"bytes {start}-{end}/{total}",
            "Content-Type": "application/octet-stream",
        },
    )


async def _create(client: httpx.AsyncClient, data: bytes) -> dict[str, Any]:
    """Zakłada sesję importu dla paczki ``data``; zwraca ``data`` koperty (stan ``uploading``)."""
    response = await client.post(
        "/api/wd/v1/dataset-imports",
        json={"file_name": "rocznik.wdkb.zip", "size_bytes": len(data)},
    )
    assert response.status_code == _HTTP_CREATED, response.text
    return response.json()["data"]


async def _upload_with_resume(
    client: httpx.AsyncClient, import_id: str, data: bytes
) -> dict[str, Any]:
    """Wysyła paczkę porcjami, symuluje przerwanie (zły offset) i wznawia od ``received_bytes``.

    Zwraca ``data`` koperty ostatniej (kończącej) porcji — po niej sesja jest ``ready``/``invalid``.
    """
    pieces = _pieces(data)
    first = pieces[0]
    assert len(pieces) >= MIN_PIECES, "paczka musi mieć kilka porcji, żeby pokazać wznowienie"
    assert (
        await _put(client, import_id, total=len(data), start=first[0], end=first[1], piece=first[2])
    ).status_code == _HTTP_OK
    # Porcja 2 z błędnym offsetem (klient przeskoczył porcję) → 409 offset_mismatch.
    jump_start = len(first[2]) + len(pieces[1][2])
    jump = await _put(
        client,
        import_id,
        total=len(data),
        start=jump_start,
        end=jump_start + len(pieces[1][2]) - 1,
        piece=pieces[1][2],
    )
    assert jump.status_code == _HTTP_CONFLICT, jump.text
    error = jump.json()["error"]
    assert error["code"] == "offset_mismatch"
    received = int(error["details"]["received_bytes"])
    assert received == len(first[2])
    response: httpx.Response | None = None
    for start, end, piece in pieces[1:]:
        response = await _put(client, import_id, total=len(data), start=start, end=end, piece=piece)
        assert response.status_code == _HTTP_OK, response.text
    assert response is not None
    return response.json()["data"]


async def _upload_all(client: httpx.AsyncClient, import_id: str, data: bytes) -> httpx.Response:
    """Wysyła całą paczkę porcjami; zwraca odpowiedź ostatniej porcji."""
    response: httpx.Response | None = None
    for start, end, piece in _pieces(data):
        response = await _put(client, import_id, total=len(data), start=start, end=end, piece=piece)
        assert response.status_code == _HTTP_OK, response.text
    assert response is not None
    return response


async def _start(
    client: httpx.AsyncClient, import_id: str, *, name: str, embedding_model: str | None = None
) -> httpx.Response:
    """Wysyła ``POST .../start`` z podanym ciałem."""
    return await client.post(
        f"/api/wd/v1/dataset-imports/{import_id}/start",
        json={"name": name, "embedding_model": embedding_model},
    )


# --- wykonanie zadania jak w workerze ---------------------------------------------------------


def _ctx(container: Container, task: TaskRow) -> TaskContext:
    """Kontekst zadania dla handlera (logger bez handlera, kolejka z kontenera)."""
    queue = _queue(container)
    logger: logging.LoggerAdapter[logging.Logger] = logging.LoggerAdapter(
        logging.getLogger("test.import_flow"), {"task_id": task.id}
    )
    return TaskContext(
        task=task, worker_id=WORKER_ID, container=container, logger=logger, queue=queue
    )


async def _run_import_task(container: Container, task_id: str) -> None:
    """Claim zadania ``import_dataset`` i wykonanie handlera z ``KB_HANDLERS`` (jak worker)."""
    queue = _queue(container)
    task = await queue.claim(WORKER_ID, ["import_dataset"])
    assert task is not None and task.id == task_id, "zadanie importu musi być do wzięcia"
    await KB_HANDLERS["import_dataset"](task, _ctx(container, task))
    await queue.complete(task.id, WORKER_ID)


# --- odczyty testowe --------------------------------------------------------------------------


async def _count(sm: async_sessionmaker[AsyncSession], sql: str, **params: object) -> int:
    """Liczba wierszy zapytania (odczyt testowy w osobnej transakcji)."""
    async with transaction(sm) as session:
        return int((await session.execute(text(sql), params)).scalar_one())


async def _document_runs(sm: async_sessionmaker[AsyncSession], dataset_id: str) -> list[str]:
    """Kody ``run`` dokumentów datasetu (kolejność nazw)."""
    async with transaction(sm) as session:
        rows = (
            (
                await session.execute(
                    text("SELECT name, run FROM documents WHERE dataset_id = :ds ORDER BY name"),
                    {"ds": dataset_id},
                )
            )
            .mappings()
            .all()
        )
    return [str(row["run"]) for row in rows]


async def _chunk_row(
    sm: async_sessionmaker[AsyncSession], sql: str, **params: object
) -> dict[str, Any] | None:
    """Pierwszy wiersz zapytania o chunki (odczyt testowy)."""
    async with transaction(sm) as session:
        row = (await session.execute(text(sql), params)).mappings().first()
    return dict(row) if row is not None else None


def _table_rows(dim: int, dataset_id: str) -> str:
    """SQL licznika wektorów datasetu w ``chunk_vec_d<dim>`` (nazwa z walidowanego int)."""
    return (
        f"SELECT COUNT(*) FROM chunk_vec_d{dim} v"  # noqa: S608
        " JOIN chunks c ON c.id = v.chunk_id WHERE c.dataset_id = :ds"
    )


# --- p. 1: przepływ end-to-end (K19 R-KB-02) --------------------------------------------------


async def test_import_flow_end_to_end(  # noqa: PLR0915 — cały scenariusz R-KB-02 w jednym teście
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """R-KB-02: sesja → porcje z przerwaniem → ready → start → handler → done → retrieval."""
    await _models(sm)
    alice = await seed_user(sm)
    data = _valid_package(tmp_path)

    async with _client(_app(container, principal_for(alice))) as client:
        created = await _create(client, data)
        import_id = created["import_id"]
        assert len(import_id) == ID_HEX_LEN

        final = await _upload_with_resume(client, import_id, data)
        assert final["state"] == "ready", final
        assert final["received_bytes"] == len(data)
        summary = final["summary"]
        assert summary["name"] == PACKAGE_NAME
        assert summary["documents"] == DOCUMENTS
        assert summary["chunks"] == PACKAGE_CHUNKS
        # Literał z K19 §2 (schema_version: 1), nie stała z kodu — inaczej mutacja stałej
        # ``fmt.SCHEMA_VERSION`` przechodzi test mimo zmiany formatu paczki (review-misses.md).
        assert summary["schema_version"] == 1
        assert summary["embedding"] == {
            "model_name": EMBED_MODEL,
            "dimension": DIM,
            "included": True,
        }
        assert summary["target"]["compatible"] is True
        assert summary["target"]["default_model"] == EMBED_MODEL
        assert summary["name_taken"] is False
        assert summary["suggested_name"] == PACKAGE_NAME
        assert summary["estimated_reembed_tokens"] == PACKAGE_CHUNKS * TOKEN_COUNT

        started = await _start(client, import_id, name=IMPORT_NAME)
        assert started.status_code == _HTTP_ACCEPTED, started.text
        task_id = started.json()["data"]["task_id"]
        assert started.json()["data"]["status"] == "queued"

        # Zadanie wykonane jak w workerze (claim + handler), potem stan przez trasę WD.
        await _run_import_task(container, task_id)

        task_body = (await client.get(f"/api/wd/v1/tasks/{task_id}")).json()
        task = task_body["data"]
        assert task["kind"] == "import", task
        assert task["status"] == "done", task
        result = task["result"]
        assert result["documents"] == DOCUMENTS
        assert result["chunks"] == PACKAGE_CHUNKS
        assert result["reembedded"] is False
        dataset_id = result["dataset_id"]
        assert len(dataset_id) == ID_HEX_LEN

        # Retrieval: chunk z edytowaną treścią wraca z poprawnym document_id; wyłączony NIE wraca.
        matched = await _chunk_row(
            sm,
            "SELECT id, document_id FROM chunks WHERE dataset_id = :ds AND content LIKE :word",
            ds=dataset_id,
            word=f"%{UNIQUE_WORD}%",
        )
        assert matched is not None
        retrieved = (
            await client.post(
                "/api/v1/retrieval",
                json={"question": UNIQUE_WORD, "dataset_ids": [dataset_id]},
            )
        ).json()
        assert retrieved["code"] == 0, retrieved
        hits = retrieved["data"]["chunks"]
        assert retrieved["data"]["total"] >= 1
        assert any(UNIQUE_WORD in chunk["content"] for chunk in hits), hits
        word_hits = [chunk for chunk in hits if UNIQUE_WORD in chunk["content"]]
        assert word_hits[0]["document_id"] == matched["document_id"]

        disabled = (
            await client.post(
                "/api/v1/retrieval",
                json={"question": DISABLED_WORD, "dataset_ids": [dataset_id]},
            )
        ).json()
        assert disabled["code"] == 0, disabled
        assert disabled["data"]["total"] == 0, disabled

        # Obraz chunka dostępny trasą obrazów dokumentu (id = ``{dataset_id}-{sha}``).
        image_id = f"{dataset_id}-{hashlib.sha256(IMAGE_DATA).hexdigest()}"
        image = await client.get(f"/api/v1/documents/images/{image_id}")
        assert image.status_code == _HTTP_OK, image.text
        assert image.content == IMAGE_DATA

    # Dokumenty datasetu „zakończone" (run DONE z paczki), wektory z paczki w chunk_vec_d<dim>.
    assert await _document_runs(sm, dataset_id) == ["3", "3"]
    assert await _count(sm, _table_rows(DIM, dataset_id), ds=dataset_id) == PACKAGE_CHUNKS
    stored = await _chunk_row(
        sm,
        f"SELECT VEC_ToText(v.embedding) AS v FROM chunk_vec_d{DIM} v"  # noqa: S608
        " JOIN chunks c ON c.id = v.chunk_id WHERE c.dataset_id = :ds"
        " AND c.content LIKE :word",
        ds=dataset_id,
        word=f"%{UNIQUE_WORD}%",
    )
    assert stored is not None
    vector = json.loads(str(stored["v"]))
    assert len(vector) == DIM
    assert all(abs(component - COMP) < FLOAT_TOLERANCE for component in vector)


# --- p. 2: wariant reembed --------------------------------------------------------------------


async def test_reembed_flow_end_to_end(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Paczka z modelem o innym wymiarze → ``reembed=true`` i wektory nowego wymiaru."""
    await _models(sm)
    alice = await seed_user(sm)
    data = _valid_package(tmp_path, model_name=PACKAGE_MODEL, dim=SOURCE_DIM)

    async with _client(_app(container, principal_for(alice))) as client:
        created = await _create(client, data)
        final = (await _upload_all(client, created["import_id"], data)).json()["data"]
        assert final["state"] == "ready", final
        assert final["summary"]["target"]["compatible"] is False
        assert final["summary"]["target"]["default_model"] == EMBED_MODEL

        started = await _start(client, created["import_id"], name="Import reembed")
        assert started.status_code == _HTTP_ACCEPTED, started.text
        task_id = started.json()["data"]["task_id"]
        await _run_import_task(container, task_id)

        task = (await client.get(f"/api/wd/v1/tasks/{task_id}")).json()["data"]

    assert task["status"] == "done", task
    assert task["result"]["reembedded"] is True
    assert task["result"]["chunks"] == PACKAGE_CHUNKS
    dataset_id = task["result"]["dataset_id"]
    # Wektory policzone od nowa modelem docelowym (DIM); paczkowe (SOURCE_DIM) nieużyte.
    assert await _count(sm, _table_rows(DIM, dataset_id), ds=dataset_id) == PACKAGE_CHUNKS
    assert await _document_runs(sm, dataset_id) == ["3", "3"]


# --- p. 3: wariant złośliwy (E7-1f, mutacja k19-zip-path-traversal) ---------------------------


async def test_malicious_package_flow_is_invalid(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Paczka ``../x`` przez trasę → ``invalid`` ``unsafe_path``; ``start`` → 409; brak datasetu."""
    alice = await seed_user(sm)
    corrupt = _unsafe_path_package()

    async with _client(_app(container, principal_for(alice))) as client:
        created = await _create(client, corrupt)
        import_id = created["import_id"]
        final = (await _upload_all(client, import_id, corrupt)).json()["data"]
        started = await _start(client, import_id, name="Zepsuty import")

    assert final["state"] == "invalid", final
    assert final["errors"][0]["code"] == "unsafe_path", final["errors"]
    assert final["summary"] is None
    assert started.status_code == _HTTP_CONFLICT, started.text
    assert started.json()["error"]["code"] == "import_not_ready"
    assert started.json()["error"]["details"]["state"] == "invalid"
    # W storage nie powstał ani dataset, ani plik paczki (usunięty po walidacji).
    assert await _count(sm, "SELECT COUNT(*) FROM datasets") == 0
    assert not (tmp_path / "imports" / f"{import_id}.wdkb.zip").exists()
    assert not (tmp_path / "files").exists()


# --- p. 4: wariant „drugi użytkownik" (mutacja k19-import-owner) ------------------------------


async def test_foreign_user_cannot_see_session_or_dataset(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Sesja i dataset użytkownika B niewidoczne dla A: 404 na trasach 6-10 i brak dostępu."""
    await _models(sm)
    bob = await seed_user(sm)
    alice = await seed_user(sm)
    data = _valid_package(tmp_path)

    async with _client(_app(container, principal_for(bob))) as client:
        created = await _create(client, data)
        import_id = created["import_id"]
        await _upload_all(client, import_id, data)
        started = await _start(client, import_id, name="Import Boba")
        assert started.status_code == _HTTP_ACCEPTED, started.text
        task_id = started.json()["data"]["task_id"]
        await _run_import_task(container, task_id)
        dataset_id = (await client.get(f"/api/wd/v1/tasks/{task_id}")).json()["data"]["result"][
            "dataset_id"
        ]

    # Obcy (A) nie widzi sesji B na żadnej z tras 6-10 (404, bez zdradzania istnienia).
    async with _client(_app(container, principal_for(alice))) as client:
        get = await client.get(f"/api/wd/v1/dataset-imports/{import_id}")
        put = await _put(client, import_id, total=len(data), start=0, end=0, piece=b"x")
        start = await _start(client, import_id, name="Obcy start")
        delete = await client.delete(f"/api/wd/v1/dataset-imports/{import_id}")

    for response in (get, put, start, delete):
        assert response.status_code == _HTTP_NOT_FOUND, response.text
        assert response.json()["error"]["code"] == "not_found"

    # Dataset powstał w tenancie B i A nie ma do niego dostępu (retrieval: koperta 102).
    assert (
        await _count(
            sm,
            "SELECT COUNT(*) FROM datasets WHERE id = :ds AND tenant_id = :tenant",
            ds=dataset_id,
            tenant=bob,
        )
        == 1
    )
    async with _client(_app(container, principal_for(alice))) as client:
        denied = (
            await client.post(
                "/api/v1/retrieval",
                json={"question": "cokolwiek", "dataset_ids": [dataset_id]},
            )
        ).json()
    assert denied["code"] == RetCode.DATA_ERROR, denied
