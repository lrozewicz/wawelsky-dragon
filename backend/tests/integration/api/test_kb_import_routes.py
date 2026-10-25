"""Testy HTTP tras importu ``/api/wd/v1/dataset-imports…`` (K19 §3 trasy 6-8 i 10).

Zakres: sesja uploadu (201), porcje ``Content-Range`` dopisywane do pliku paczki, walidacja po
porcji kończącej (``ready``/``invalid``), wznowienie po ``offset_mismatch``, uprawnienia 6-10
(obcy → 404, superuser → 200), limity (413/400), usunięcie sesji i pliku oraz serializacja
równoległych porcji o tym samym ``start`` (CONTRACT E7-1b §4, DEC-327).

Paczki buduje ``PackageWriter`` i przechodzą realny walidator (jak w testach E7-1f/T2); złośliwe
archiwa składamy ``zipfile`` ręcznie — walidator musi je odrzucić.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import threading
import uuid
import zipfile
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.auth.principal import get_principal
from app.api.wd import kb_schemas
from app.core.config import Settings
from app.core.container import Container
from app.db.uow import transaction
from app.domain.policy import Principal
from app.main import create_app
from app.services import kb_import_upload
from app.services.kb_import import UPLOAD_CHUNK_SIZE
from app.services.kb_package import format as fmt
from app.services.kb_package.writer import PackageWriter
from app.worker.queue import DbTaskQueue, NewTask
from tests.integration.chat.conftest import seed_user
from tests.integration.ingest.pipeline_helpers import make_container
from tests.integration.retrieval.conftest import principal_for

pytestmark = pytest.mark.db

_HTTP_OK = 200
_HTTP_CREATED = 201
_HTTP_BAD_REQUEST = 400
_HTTP_UNAUTHORIZED = 401
_HTTP_NOT_FOUND = 404
_HTTP_CONFLICT = 409
_HTTP_TOO_LARGE = 413
_WORKER_ID = "w:1:0"
ID_HEX_LEN = 32  # długość identyfikatora sesji (K19 §3)

MAX_BYTES = 100 * 1024 * 1024
MAX_RATIO = 100
DIMENSION = 1024  # fake-embed-1024 z make_container
CHUNK = 8192  # rozmiar porcji w testach (paczka cięta po 8 KB)
PARSER_CONFIG: dict[str, Any] = {"chunk_token_num": 128, "delimiter": "\n"}
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
# Nieściśliwy plik dokumentu — paczka ma zostać ponad 2 porcje (20 480 B danych z paczki).
FILE_BYTES = os.urandom(20_000)

# K19 §3: klucze ``DatasetImport`` (kolejność nieznacząca — porównujemy zbiór).
_DATASET_IMPORT_KEYS = {
    "import_id",
    "file_name",
    "size_bytes",
    "received_bytes",
    "chunk_size",
    "state",
    "errors",
    "summary",
    "task_id",
    "expires_at",
}


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener ze magazynem w tmp_path i modelami fake-llm (wzorzec ``tests/integration/api``)."""
    instance = await make_container(migrated_db, tmp_path)
    yield instance
    await instance.aclose()


def _app(container: Container, principal: Principal | None) -> FastAPI:
    """Aplikacja na żywym kontenerze; ``principal=None`` → brak nadpisania (ścieżka 401)."""
    app = create_app(container.settings, container)
    if principal is not None:
        app.dependency_overrides[get_principal] = lambda: principal
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    """Klient ASGI nad aplikacją testową."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _queue(container: Container) -> DbTaskQueue:
    """Kolejka na usługach kontenera (enqueue/claim/complete)."""
    return DbTaskQueue(
        cast("async_sessionmaker[AsyncSession]", container.sessionmaker),
        container.clock,
        container.id_gen,
    )


# --- paczki testowe ------------------------------------------------------------------------


def _manifest(documents: int) -> fmt.Manifest:
    """Manifest paczki testowej: bez wektorów, jedna linia na dokument."""
    return fmt.Manifest.model_validate(
        {
            "format": fmt.FORMAT_NAME,
            "schema_version": fmt.SCHEMA_VERSION,
            "wd_version": "0.9.0",
            "created_at": "2026-10-12T21:00:00Z",
            "source_instance_id": "0123456789abcdef0123456789abcdef",
            "dataset": {
                "name": "Baza źródłowa",
                "description": "opis źródła",
                "language": "Polish",
                "chunk_method": "naive",
                "parser_config": PARSER_CONFIG,
                "similarity_threshold": 0.35,
                "vector_similarity_weight": 0.45,
                "pagerank": 2,
            },
            "embedding": {"model_name": "bge-m3", "dimension": DIMENSION, "included": False},
            "counts": {"documents": documents, "chunks": 0, "vectors": 0},
            "entries": [],
        }
    )


def _document(sha: str, size: int) -> dict[str, Any]:
    """Linia ``documents.jsonl`` wg K19 §2 (jeden plik dołączony)."""
    return {
        "ref": "d1",
        "name": "rocznik.pdf",
        "type": "pdf",
        "suffix": "pdf",
        "size": size,
        "file_sha256": sha,
        "chunk_method": "naive",
        "parser_config": PARSER_CONFIG,
        "meta_fields": {"tag": "gus"},
        "run": "3",  # DONE — run surowe (K19 §2)
        "progress_msg": "gotowe",
        "token_num": 10,
        "chunk_num": 1,
    }


def _jsonl(rows: Sequence[dict[str, Any]]) -> bytes:
    """Wpis JSONL z linii dokumentów."""
    return b"".join(json.dumps(row, ensure_ascii=False).encode("utf-8") + b"\n" for row in rows)


def _valid_package(tmp_path: Path) -> bytes:
    """Poprawna paczka z jednym dokumentem i jego plikiem; zwraca jej bajty."""
    path = tmp_path / "src.wdkb.zip"
    sha = hashlib.sha256(FILE_BYTES).hexdigest()
    writer = PackageWriter(path, max_bytes=MAX_BYTES)
    writer.add_bytes(fmt.DOCUMENTS_PATH, _jsonl([_document(sha, len(FILE_BYTES))]))
    writer.add_bytes(fmt.CHUNKS_PATH, b"")
    writer.add_bytes(f"{fmt.FILES_PREFIX}{sha}", FILE_BYTES)
    writer.finish(_manifest(documents=1))
    return path.read_bytes()


def _raw_zip(entries: dict[str, bytes]) -> bytes:
    """Archiwum ZIP z podanych wpisów (kolejność zachowana) — do paczek złośliwych."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _unsafe_path_package() -> bytes:
    """Paczka z wpisem ``../x`` — walidacja ścieżek odrzuca ją jako ``unsafe_path``."""
    return _raw_zip({"manifest.json": b"{}", "../x": b"zly wpis"})


def _checksum_mismatch_package() -> bytes:
    """Paczka z manifestem kłamiącym o sumie ``documents.jsonl`` — ``checksum_mismatch``."""
    documents = _jsonl([_document("0" * 64, 0)])
    manifest = {
        "format": fmt.FORMAT_NAME,
        "schema_version": fmt.SCHEMA_VERSION,
        "wd_version": "0.9.0",
        "created_at": "2026-10-12T21:00:00Z",
        "source_instance_id": "0123456789abcdef0123456789abcdef",
        "dataset": {
            "name": "Baza źródłowa",
            "description": None,
            "language": "Polish",
            "chunk_method": "naive",
            "parser_config": PARSER_CONFIG,
            "similarity_threshold": 0.35,
            "vector_similarity_weight": 0.45,
            "pagerank": 2,
        },
        "embedding": {"model_name": "bge-m3", "dimension": DIMENSION, "included": False},
        "counts": {"documents": 1, "chunks": 0, "vectors": 0},
        "entries": [
            {"path": fmt.DOCUMENTS_PATH, "sha256": "0" * 64, "size": len(documents)},
            {"path": fmt.CHUNKS_PATH, "sha256": EMPTY_SHA256, "size": 0},
        ],
    }
    return _raw_zip(
        {
            "manifest.json": json.dumps(manifest).encode("utf-8"),
            fmt.DOCUMENTS_PATH: documents,
            fmt.CHUNKS_PATH: b"",
        }
    )


# --- wywołania HTTP ------------------------------------------------------------------------


def _ranges(data: bytes) -> list[tuple[int, int, bytes]]:
    """Paczka pocięta na porcje ``CHUNK``: ``(start, end, bajty)``."""
    pieces = []
    for offset in range(0, len(data), CHUNK):
        piece = data[offset : offset + CHUNK]
        pieces.append((offset, offset + len(piece) - 1, piece))
    return pieces


async def _create(
    client: httpx.AsyncClient, *, size_bytes: int, file_name: str = "korpus.wdkb.zip"
) -> dict[str, Any]:
    """Zakłada sesję importu; zwraca ``data`` koperty."""
    response = await client.post(
        "/api/wd/v1/dataset-imports",
        json={"file_name": file_name, "size_bytes": size_bytes},
    )
    assert response.status_code == _HTTP_CREATED, response.text
    return response.json()["data"]


async def _put(  # noqa: PLR0913 — klient, sesja, zakres i porcja odwzorowują nagłówek Content-Range
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


async def _upload_all(client: httpx.AsyncClient, import_id: str, data: bytes) -> httpx.Response:
    """Wysyła całą paczkę porcjami; zwraca odpowiedź ostatniej porcji."""
    response: httpx.Response | None = None
    for start, end, piece in _ranges(data):
        response = await _put(client, import_id, total=len(data), start=start, end=end, piece=piece)
        assert response.status_code == _HTTP_OK, response.text
    assert response is not None  # paczka zawsze ma co najmniej jedną porcję
    return response


def _import_file(tmp_path: Path, import_id: str) -> Path:
    """Ścieżka pliku paczki w storage testowego kontenera."""
    return tmp_path / "imports" / f"{import_id}.wdkb.zip"


async def _set_state(container: Container, import_id: str, *, state: str, task_id: str) -> None:
    """Ustawia stan sesji i ``task_id`` wprost w bazie (stan ``started`` nadaje T6)."""
    async with transaction(container.sessionmaker) as session:
        await session.execute(
            text(
                "UPDATE dataset_imports SET state = :state, task_id = :task_id"
                " WHERE id = CAST(:id AS BINARY)"
            ),
            {"state": state, "task_id": task_id, "id": import_id},
        )


# --- trasa 6: zakładanie sesji -------------------------------------------------------------


def test_upload_chunk_size_matches_the_wire_constant() -> None:
    """Stała porcji usługi jest zgodna z ``kb_schemas.IMPORT_CHUNK_SIZE`` (kontrakt warstw)."""
    assert UPLOAD_CHUNK_SIZE == kb_schemas.IMPORT_CHUNK_SIZE


async def test_create_session_has_the_contract_shape(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """201, pełny zestaw pól ``DatasetImport``, stan ``uploading``, brak podsumowania (trasa 6)."""
    alice = await seed_user(sm)

    async with _client(_app(container, principal_for(alice))) as client:
        data = await _create(client, size_bytes=2048)

    assert set(data) == _DATASET_IMPORT_KEYS
    assert data["file_name"] == "korpus.wdkb.zip"
    assert (data["size_bytes"], data["received_bytes"]) == (2048, 0)
    assert data["chunk_size"] == kb_schemas.IMPORT_CHUNK_SIZE
    assert data["state"] == "uploading"
    assert data["errors"] == [] and data["summary"] is None and data["task_id"] is None
    assert data["expires_at"] > 0
    assert len(data["import_id"]) == ID_HEX_LEN


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"file_name": "", "size_bytes": 10}, _HTTP_BAD_REQUEST),
        ({"file_name": "x" * 256, "size_bytes": 10}, _HTTP_BAD_REQUEST),
        ({"file_name": "p.wdkb.zip", "size_bytes": 0}, _HTTP_BAD_REQUEST),
        ({"file_name": "p.wdkb.zip", "size_bytes": 2_147_483_649}, _HTTP_TOO_LARGE),
    ],
)
async def test_create_rejects_invalid_body(
    container: Container,
    sm: async_sessionmaker[AsyncSession],
    payload: dict[str, Any],
    expected: int,
) -> None:
    """Nazwa poza 1..255 / rozmiar ≤ 0 → 400; rozmiar > ``export_max_bytes`` → 413."""
    alice = await seed_user(sm)

    async with _client(_app(container, principal_for(alice))) as client:
        response = await client.post("/api/wd/v1/dataset-imports", json=payload)

    assert response.status_code == expected, response.text
    code = response.json()["error"]["code"]
    assert code == ("validation_failed" if expected == _HTTP_BAD_REQUEST else "package_too_large")


# --- trasa 7: upload porcjami i walidacja --------------------------------------------------


async def test_three_chunks_reach_ready_and_get_round_trips(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Trzy porcje → ``ready`` z podsumowaniem; plik zgadza się z wysłaną paczką (trasy 7-8)."""
    alice = await seed_user(sm)
    data = _valid_package(tmp_path)
    assert len(data) > 2 * CHUNK, "paczka testowa musi mieć co najmniej 3 porcje"

    async with _client(_app(container, principal_for(alice))) as client:
        created = await _create(client, size_bytes=len(data))
        received: list[int] = []
        for start, end, piece in _ranges(data):
            response = await _put(
                client, created["import_id"], total=len(data), start=start, end=end, piece=piece
            )
            assert response.status_code == _HTTP_OK, response.text
            received.append(response.json()["data"]["received_bytes"])
        final = response.json()["data"]
        detail = (await client.get(f"/api/wd/v1/dataset-imports/{created['import_id']}")).json()[
            "data"
        ]

    assert received == sorted(received) and received[-1] == len(data)
    assert final["state"] == "ready"
    assert final["errors"] == []
    assert final["summary"]["documents"] == 1
    assert final["summary"]["embedding"]["model_name"] == "bge-m3"
    assert final["summary"]["name_taken"] is False
    assert detail == final  # GET zwraca ten sam stan (trasa 8)
    assert _import_file(tmp_path, created["import_id"]).read_bytes() == data


async def test_resume_after_offset_mismatch(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Powtórzona porcja → 409 ``offset_mismatch``; klient wznawia od ``received_bytes``."""
    alice = await seed_user(sm)
    data = _valid_package(tmp_path)
    ranges = _ranges(data)

    async with _client(_app(container, principal_for(alice))) as client:
        created = await _create(client, size_bytes=len(data))
        first = ranges[0]
        ok = await _put(
            client,
            created["import_id"],
            total=len(data),
            start=first[0],
            end=first[1],
            piece=first[2],
        )
        assert ok.status_code == _HTTP_OK, ok.text
        replay = await _put(
            client,
            created["import_id"],
            total=len(data),
            start=first[0],
            end=first[1],
            piece=first[2],
        )
        assert replay.status_code == _HTTP_CONFLICT, replay.text
        error = replay.json()["error"]
        assert error["code"] == "offset_mismatch"
        assert error["details"]["received_bytes"] == len(first[2])
        resumed = await _put(
            client,
            created["import_id"],
            total=len(data),
            start=len(first[2]),
            end=ranges[1][1],
            piece=ranges[1][2],
        )

    assert resumed.status_code == _HTTP_OK, resumed.text
    assert resumed.json()["data"]["received_bytes"] == len(first[2]) + len(ranges[1][2])


async def test_forward_offset_jump_is_rejected(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Porcja zaczęta ZA ``received_bytes`` → 409, plik bez dziury (nie tylko replay).

    Klient z błędem logiki wznawiania wysyła ``start > received_bytes``: musi dostać 409
    z punktem wznowienia, a nie cichy zapis z zerową dziurą (``seek(start)+truncate()``),
    który wyszedłby dopiero przy walidacji jako mylący ``checksum_mismatch``.
    """
    alice = await seed_user(sm)
    data = _valid_package(tmp_path)
    first = _ranges(data)[0]
    piece = b"y" * 1024  # krótszy kawałek, żeby koniec zakresu został wewnątrz paczki

    async with _client(_app(container, principal_for(alice))) as client:
        created = await _create(client, size_bytes=len(data))
        assert (
            await _put(
                client,
                created["import_id"],
                total=len(data),
                start=first[0],
                end=first[1],
                piece=first[2],
            )
        ).status_code == _HTTP_OK
        jump = len(first[2]) + 1024
        response = await _put(
            client,
            created["import_id"],
            total=len(data),
            start=jump,
            end=jump + len(piece) - 1,
            piece=piece,
        )
        detail = (await client.get(f"/api/wd/v1/dataset-imports/{created['import_id']}")).json()[
            "data"
        ]

    assert response.status_code == _HTTP_CONFLICT, response.text
    error = response.json()["error"]
    assert error["code"] == "offset_mismatch"
    assert error["details"]["received_bytes"] == len(first[2])
    assert detail["received_bytes"] == len(first[2])
    assert _import_file(tmp_path, created["import_id"]).stat().st_size == len(first[2])


@pytest.mark.parametrize(
    "content_range",
    [None, "bytes 0-10", "bytes 0-10/9", "bytes 10-5/20", "bytes 0-20/20", "bytes 0-19/20x"],
)
async def test_broken_content_range_is_rejected(
    container: Container,
    sm: async_sessionmaker[AsyncSession],
    content_range: str | None,
) -> None:
    """Brak/zły nagłówek, ``total`` ≠ rozmiar, odwrotny zakres, zakres poza plikiem → 400."""
    alice = await seed_user(sm)

    async with _client(_app(container, principal_for(alice))) as client:
        created = await _create(client, size_bytes=20)
        headers = {"Content-Type": "application/octet-stream"}
        if content_range is not None:
            headers["Content-Range"] = content_range
        response = await client.put(
            f"/api/wd/v1/dataset-imports/{created['import_id']}/content",
            content=b"x" * 20,
            headers=headers,
        )

    assert response.status_code == _HTTP_BAD_REQUEST, response.text
    assert response.json()["error"]["code"] == "validation_failed"


async def test_chunk_over_limit_is_too_large(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Porcja większa niż ``chunk_size`` → 413 (z nagłówka, przed czytaniem ciała)."""
    alice = await seed_user(sm)
    total = 2 * UPLOAD_CHUNK_SIZE

    async with _client(_app(container, principal_for(alice))) as client:
        created = await _create(client, size_bytes=total)
        response = await _put(
            client,
            created["import_id"],
            total=total,
            start=0,
            end=UPLOAD_CHUNK_SIZE,
            piece=b"x" * UPLOAD_CHUNK_SIZE,
        )

    assert response.status_code == _HTTP_TOO_LARGE, response.text
    assert response.json()["error"]["code"] == "package_too_large"


async def test_upload_after_ready_is_conflict(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Kolejna porcja po ``ready`` → 409 ``import_not_ready`` z ``details.state`` (trasa 7)."""
    alice = await seed_user(sm)
    data = _valid_package(tmp_path)

    async with _client(_app(container, principal_for(alice))) as client:
        created = await _create(client, size_bytes=len(data))
        await _upload_all(client, created["import_id"], data)
        response = await _put(
            client,
            created["import_id"],
            total=len(data),
            start=0,
            end=0,
            piece=b"x",
        )

    assert response.status_code == _HTTP_CONFLICT, response.text
    error = response.json()["error"]
    assert error["code"] == "import_not_ready"
    assert error["details"]["state"] == "ready"


async def test_last_chunk_mismatch_is_rejected_and_file_truncated(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Ciało krótsze niż zakres → 400, a plik wraca do ``received_bytes`` (CONTRACT §4)."""
    alice = await seed_user(sm)
    data = _valid_package(tmp_path)
    ranges = _ranges(data)

    async with _client(_app(container, principal_for(alice))) as client:
        created = await _create(client, size_bytes=len(data))
        start, end, piece = ranges[0]
        response = await _put(
            client,
            created["import_id"],
            total=len(data),
            start=start,
            end=end,
            piece=piece[:-1],
        )
        detail = (await client.get(f"/api/wd/v1/dataset-imports/{created['import_id']}")).json()[
            "data"
        ]

    assert response.status_code == _HTTP_BAD_REQUEST, response.text
    assert detail["received_bytes"] == 0
    assert not _import_file(tmp_path, created["import_id"]).exists() or (
        _import_file(tmp_path, created["import_id"]).stat().st_size == 0
    )


async def test_malicious_package_marks_invalid_and_removes_file(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Paczka ``../x`` albo zła suma → 200 ``invalid`` z kodem błędu, plik usunięty (K19 §5)."""
    alice = await seed_user(sm)

    async with _client(_app(container, principal_for(alice))) as client:
        unsafe = _unsafe_path_package()
        created = await _create(client, size_bytes=len(unsafe))
        response = await _upload_all(client, created["import_id"], unsafe)
        assert response.json()["data"]["errors"][0]["code"] == "unsafe_path"
        assert not _import_file(tmp_path, created["import_id"]).exists()

        corrupt = _checksum_mismatch_package()
        created = await _create(client, size_bytes=len(corrupt))
        response = await _upload_all(client, created["import_id"], corrupt)
        assert response.json()["data"]["errors"][0]["code"] == "checksum_mismatch"
        assert not _import_file(tmp_path, created["import_id"]).exists()

    data = response.json()["data"]
    assert data["state"] == "invalid"
    assert data["summary"] is None


# --- uprawnienia 6-10 ----------------------------------------------------------------------


async def test_foreign_user_gets_not_found_and_superuser_accesses(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Obcy zwykły użytkownik: GET/PUT/DELETE → 404; superuser: 200 (K19 §Uprawnienia 6-10)."""
    owner = await seed_user(sm)
    stranger = await seed_user(sm)
    admin = await seed_user(sm)

    async with _client(_app(container, principal_for(owner))) as client:
        created = await _create(client, size_bytes=2048)
        import_id = created["import_id"]

    async with _client(_app(container, principal_for(stranger))) as client:
        get = await client.get(f"/api/wd/v1/dataset-imports/{import_id}")
        put = await _put(client, import_id, total=2048, start=0, end=0, piece=b"x")
        delete = await client.delete(f"/api/wd/v1/dataset-imports/{import_id}")

    for response in (get, put, delete):
        assert response.status_code == _HTTP_NOT_FOUND, response.text
        assert response.json()["error"]["code"] == "not_found"

    async with _client(_app(container, principal_for(admin, superuser=True))) as client:
        seen = await client.get(f"/api/wd/v1/dataset-imports/{import_id}")
        uploaded = await _put(client, import_id, total=2048, start=0, end=0, piece=b"x")
        removed = await client.delete(f"/api/wd/v1/dataset-imports/{import_id}")

    assert seen.status_code == _HTTP_OK, seen.text
    assert uploaded.status_code == _HTTP_OK, uploaded.text  # też trasa 7 należy do 6-10
    assert uploaded.json()["data"]["received_bytes"] == 1
    assert removed.status_code == _HTTP_OK, removed.text


async def test_unknown_session_is_not_found(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Nieznane ``import_id`` → 404 (bez odróżnienia od cudzej sesji)."""
    alice = await seed_user(sm)

    async with _client(_app(container, principal_for(alice))) as client:
        response = await client.get(f"/api/wd/v1/dataset-imports/{uuid.uuid4().hex}")

    assert response.status_code == _HTTP_NOT_FOUND, response.text


async def test_without_session_returns_401(container: Container) -> None:
    """Brak aktora → 401 kopertą WD (K3)."""
    async with _client(_app(container, None)) as client:
        response = await client.get(f"/api/wd/v1/dataset-imports/{uuid.uuid4().hex}")

    assert response.status_code == _HTTP_UNAUTHORIZED, response.text
    assert response.json()["error"]["code"] == "unauthorized"


# --- trasa 10: usunięcie -------------------------------------------------------------------


async def test_delete_removes_session_and_file(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """DELETE → 200 ``{"deleted": true}``, GET → 404, plik paczki zniknął (trasa 10)."""
    alice = await seed_user(sm)
    data = _valid_package(tmp_path)

    async with _client(_app(container, principal_for(alice))) as client:
        created = await _create(client, size_bytes=len(data))
        await _upload_all(client, created["import_id"], data)
        assert _import_file(tmp_path, created["import_id"]).exists()
        removed = await client.delete(f"/api/wd/v1/dataset-imports/{created['import_id']}")
        after = await client.get(f"/api/wd/v1/dataset-imports/{created['import_id']}")

    assert removed.status_code == _HTTP_OK, removed.text
    assert removed.json()["data"] == {"deleted": True}
    assert after.status_code == _HTTP_NOT_FOUND, after.text
    assert not _import_file(tmp_path, created["import_id"]).exists()


async def test_delete_started_session_with_running_task_is_conflict(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """Sesja ``started`` z działającym zadaniem → 409; po zakończeniu zadania → 200 (trasa 10)."""
    alice = await seed_user(sm)
    task_id = await _queue(container).enqueue(
        NewTask(cast("Any", "import_dataset"), {"actor_id": alice, "import_id": "i"})
    )

    async with _client(_app(container, principal_for(alice))) as client:
        created = await _create(client, size_bytes=2048)
        await _set_state(container, created["import_id"], state="started", task_id=task_id)
        blocked = await client.delete(f"/api/wd/v1/dataset-imports/{created['import_id']}")

    assert blocked.status_code == _HTTP_CONFLICT, blocked.text
    error = blocked.json()["error"]
    assert error["code"] == "import_not_ready"
    assert error["details"]["state"] == "started"

    queue = _queue(container)
    claimed = await queue.claim(_WORKER_ID, ["import_dataset"])
    assert claimed is not None
    await queue.complete(task_id, _WORKER_ID)

    async with _client(_app(container, principal_for(alice))) as client:
        removed = await client.delete(f"/api/wd/v1/dataset-imports/{created['import_id']}")

    assert removed.status_code == _HTTP_OK, removed.text


async def test_delete_waits_for_start_row_lock(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """DELETE czyta wiersz ``FOR UPDATE``: czeka na blokadę ``start`` i widzi ``started`` → 409.

    Transakcja naśladująca ``start`` (``SELECT … FOR UPDATE`` + ``UPDATE`` do ``started``) trzyma
    blokadę wiersza; ``DELETE`` wysłany w tym czasie czeka i po commicie widzi ``started`` z
    działającym zadaniem, więc odpowiada 409 zamiast kasować sesję (MINOR T6, wyścig
    delete-vs-start).
    """
    alice = await seed_user(sm)
    task_id = await _queue(container).enqueue(
        NewTask(cast("Any", "import_dataset"), {"actor_id": alice, "import_id": "i"})
    )
    sessionmaker = cast("async_sessionmaker[AsyncSession]", container.sessionmaker)
    lock_held = asyncio.Event()
    release = asyncio.Event()

    async with _client(_app(container, principal_for(alice))) as client:
        created = await _create(client, size_bytes=2048)
        import_id = created["import_id"]

        async def hold_start_lock() -> None:
            async with transaction(sessionmaker) as session:
                await kb_import_upload.locked_row(session, import_id)
                await session.execute(
                    text(
                        "UPDATE dataset_imports SET state = 'started', task_id = :task_id"
                        " WHERE id = CAST(:id AS BINARY)"
                    ),
                    {"task_id": task_id, "id": import_id},
                )
                lock_held.set()
                await release.wait()

        holder = asyncio.create_task(hold_start_lock())
        await lock_held.wait()
        deleter = asyncio.create_task(client.delete(f"/api/wd/v1/dataset-imports/{import_id}"))
        await asyncio.sleep(0.3)  # DELETE dobiegł do ``SELECT … FOR UPDATE`` i czeka na blokadę
        release.set()
        response = await deleter
        await holder

    assert response.status_code == _HTTP_CONFLICT, response.text
    assert response.json()["error"]["code"] == "import_not_ready"


# --- serializacja porcji (CONTRACT §4, DEC-327) --------------------------------------------


async def test_parallel_chunks_on_same_start_leave_one_winner(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Dwie równoległe porcje o tym samym ``start``: jedna 200, druga 409 (CONTRACT §4)."""
    alice = await seed_user(sm)
    data = _valid_package(tmp_path)
    start, end, piece = _ranges(data)[0]

    async with _client(_app(container, principal_for(alice))) as client:
        created = await _create(client, size_bytes=len(data))
        first, second = await asyncio.gather(
            _put(client, created["import_id"], total=len(data), start=start, end=end, piece=piece),
            _put(client, created["import_id"], total=len(data), start=start, end=end, piece=piece),
        )

    assert sorted((first.status_code, second.status_code)) == [_HTTP_OK, _HTTP_CONFLICT]
    loser = second if second.status_code == _HTTP_CONFLICT else first
    assert loser.json()["error"]["code"] == "offset_mismatch"
    assert _import_file(tmp_path, created["import_id"]).read_bytes() == piece


async def test_parallel_last_chunk_leave_one_winner_no_500(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Dwie równoległe porcje kończące: jedno 200 ``ready``, drugie 409, żadne 500
    (CONTRACT E7-1z §6)."""
    alice = await seed_user(sm)
    data = _valid_package(tmp_path)
    ranges = _ranges(data)

    async with _client(_app(container, principal_for(alice))) as client:
        created = await _create(client, size_bytes=len(data))
        import_id = created["import_id"]
        for start, end, piece in ranges[:-1]:
            assert (
                await _put(client, import_id, total=len(data), start=start, end=end, piece=piece)
            ).status_code == _HTTP_OK
        last_start, last_end, last_piece = ranges[-1]
        first, second = await asyncio.gather(
            _put(
                client,
                import_id,
                total=len(data),
                start=last_start,
                end=last_end,
                piece=last_piece,
            ),
            _put(
                client,
                import_id,
                total=len(data),
                start=last_start,
                end=last_end,
                piece=last_piece,
            ),
        )
        detail = (await client.get(f"/api/wd/v1/dataset-imports/{import_id}")).json()["data"]

    assert sorted((first.status_code, second.status_code)) == [_HTTP_OK, _HTTP_CONFLICT]
    loser = second if second.status_code == _HTTP_CONFLICT else first
    assert loser.json()["error"]["code"] in {"offset_mismatch", "import_not_ready"}
    assert detail["state"] == "ready"
    assert detail["received_bytes"] == len(data)
    assert _import_file(tmp_path, import_id).read_bytes() == data


async def _wait_flag(flag: threading.Event, *, budget_s: float = 10.0) -> None:
    """Czeka, aż wątek roboczy ustawi ``flag`` (walidacja wystartowała) — bez blokowania pętli."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + budget_s
    while not flag.is_set():
        if loop.time() > deadline:
            raise AssertionError("walidacja nie wystartowała w budżecie czasu")
        await asyncio.sleep(0.01)


async def test_row_lock_released_before_validation(
    container: Container,
    sm: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Walidacja biegnie poza ``FOR UPDATE``: w jej trakcie inna sesja bierze wiersz
    ``FOR UPDATE NOWAIT`` bez czekania (CONTRACT E7-1z §6)."""
    alice = await seed_user(sm)
    data = _valid_package(tmp_path)
    ranges = _ranges(data)
    started = threading.Event()
    release = threading.Event()
    real_validate = kb_import_upload.validate_package

    def _blocking(path: Path, *, max_bytes: int, max_ratio: int) -> Any:
        started.set()
        assert release.wait(10.0), "walidacja nie doczekała się zwolnienia"
        return real_validate(path, max_bytes=max_bytes, max_ratio=max_ratio)

    monkeypatch.setattr(kb_import_upload, "validate_package", _blocking)

    async with _client(_app(container, principal_for(alice))) as client:
        created = await _create(client, size_bytes=len(data))
        import_id = created["import_id"]
        for start, end, piece in ranges[:-1]:
            assert (
                await _put(client, import_id, total=len(data), start=start, end=end, piece=piece)
            ).status_code == _HTTP_OK
        last_start, last_end, last_piece = ranges[-1]
        task = asyncio.create_task(
            _put(
                client,
                import_id,
                total=len(data),
                start=last_start,
                end=last_end,
                piece=last_piece,
            )
        )
        try:
            await _wait_flag(started)  # walidacja kończącej porcji trwa, wiersz już po transakcji 1
            # Wiersz NIE jest zablokowany: ``FOR UPDATE NOWAIT`` przechodzi od razu.
            async with transaction(sm) as session:
                locked = (
                    await session.execute(
                        text(
                            "SELECT id FROM dataset_imports"
                            " WHERE id = CAST(:i AS BINARY) FOR UPDATE NOWAIT"
                        ),
                        {"i": import_id},
                    )
                ).first()
            assert locked is not None
        finally:
            release.set()
        response = await task

    assert response.status_code == _HTTP_OK, response.text
    assert response.json()["data"]["state"] == "ready"


async def test_content_range_reaching_past_size_is_rejected_with_full_body(
    container: Container, sm: async_sessionmaker[AsyncSession]
) -> None:
    """``bytes 0-20/20`` z ciałem 21 B → 400: ``end >= size_bytes`` odrzucone (RFC 7233)."""
    alice = await seed_user(sm)

    async with _client(_app(container, principal_for(alice))) as client:
        created = await _create(client, size_bytes=20)
        response = await client.put(
            f"/api/wd/v1/dataset-imports/{created['import_id']}/content",
            content=b"x" * 21,  # pełne ciało zakresu 0-20 (21 B) — nie polega na skróceniu ciała
            headers={
                "Content-Range": "bytes 0-20/20",
                "Content-Type": "application/octet-stream",
            },
        )
        detail = (await client.get(f"/api/wd/v1/dataset-imports/{created['import_id']}")).json()[
            "data"
        ]

    assert response.status_code == _HTTP_BAD_REQUEST, response.text
    assert response.json()["error"]["code"] == "validation_failed"
    assert detail["received_bytes"] == 0  # porcja poza plikiem nie została doliczona
