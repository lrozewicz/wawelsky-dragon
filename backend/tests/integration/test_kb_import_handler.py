"""Testy T7 importu bazy wiedzy: handler ``import_dataset`` (K19 §3/§5, CONTRACT E7-1b §3).

Handler uruchamiamy przez ``TaskContext`` z ``DbTaskQueue`` (bez pętli workera): claim zadania,
wywołanie handlera i zapis wyniku tą samą klasyfikacją, co ``app.worker.loop`` (``classify``).
Paczki buduje ``PackageWriter`` i przechodzą ``validate_package`` (round-trip), więc testy ćwiczą
realny czytnik i realne chunki w bazie. Przykłady z briefu T7 (sukces 1:1, reembed, Stop,
porażka, ponowienie) pokryte dosłownie; rozstrzygnięcia metodą bez pokrycia w kontrakcie —
w raporcie T7 (DEC nadaje TL).
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from alembic import command
from app.api.wd.tasks import _wd_task
from app.core.config import Settings
from app.core.container import Container
from app.core.ids import UuidV7Generator
from app.db.repositories import dataset_imports as imports_repo
from app.db.repositories import datasets as datasets_repo
from app.db.repositories import models as models_repo
from app.db.repositories import users as users_repo
from app.db.uow import transaction
from app.services.kb_package import format as fmt
from app.services.kb_package.writer import PackageWriter
from app.worker.context import TaskContext
from app.worker.errors import TaskCancelled
from app.worker.handlers import import_dataset as handler_module
from app.worker.handlers.import_dataset import IMPORT_SUFFIX, import_dataset
from app.worker.loop import classify
from app.worker.queue import DbTaskQueue, NewTask, TaskRow
from tests.fakes.clock import FrozenClock
from tests.integration.db.helpers import alembic_cfg

pytestmark = pytest.mark.db

MAX_BYTES = 100 * 1024 * 1024
MAX_RATIO = 100
DIM = 1024  # fake-embed-1024 — model docelowy zarejestrowany w teście
SOURCE_DIM = 3072  # fake-embed-3072 — model paczki (reembed importuje do DIM)
EMBED_MODEL = "fake-embed-1024"
TIME_MS = 1790157600000
# Ten sam worker dla claimu i zapisu wyniku (jak ``make_worker_id`` w loop.py).
WORKER_ID = "test-host:1:0"
PARSER_CONFIG: dict[str, Any] = {"chunk_token_num": 128, "delimiter": "\n"}
DOC_BLOB = b"umowa najmu " * 64
IMAGE_DATA = b"\x89PNG\r\n\x1a\n obraz chunka "
PREFIX = "imports"


@pytest.fixture
def migrated_db(fresh_db: Settings) -> Settings:
    """Świeża baza po migracji do head; sync, bo env.py Alembic robi asyncio.run (C12)."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    return fresh_db


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener (storage w tmp_path) z atrapą LLM i zarejestrowanym modelem ``fake-embed-1024``."""
    instance = Container(
        migrated_db.model_copy(update={"storage_root": str(tmp_path)}),
        clock=FrozenClock(),
        id_gen=UuidV7Generator(),
    )
    await instance.start()
    async with transaction(_sm(instance)) as session:
        await models_repo.insert(
            session,
            id="e" * 32,
            name=EMBED_MODEL,
            model_type="embedding",
            is_default=True,
            now_ms=TIME_MS,
        )
    yield instance
    await instance.aclose()


def _sm(container: Container) -> async_sessionmaker[Any]:
    """Fabryka sesji z kontenera (istnieje po ``start()``); brak → asercja."""
    sessionmaker = container.sessionmaker
    assert sessionmaker is not None, "container nie wystartował"
    return sessionmaker


# --- builder paczek --------------------------------------------------------------------------


def _manifest(
    *, documents: int, chunks: int, vectors: int, dim: int, included: bool
) -> fmt.Manifest:
    """Manifest paczki testowej; ``included`` mówi, czy paczka niesie wektory (wymiar ``dim``)."""
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
            "embedding": {
                "model_name": EMBED_MODEL if dim == DIM else "fake-embed-3072",
                "dimension": dim,
                "included": included,
            },
            "counts": {"documents": documents, "chunks": chunks, "vectors": vectors},
            "entries": [],
        }
    )


def _document(ref: str, *, file_sha256: str | None, run: str = "3") -> dict[str, Any]:
    """Linia ``documents.jsonl`` wg K19 §2 (``run`` surowe, "3" = DONE)."""
    return {
        "ref": ref,
        "name": f"umowa-{ref}.pdf",
        "type": "pdf",
        "suffix": "pdf",
        "size": len(DOC_BLOB) if file_sha256 else 0,
        "file_sha256": file_sha256,
        "chunk_method": "naive",
        "parser_config": PARSER_CONFIG,
        "meta_fields": {"tag": ref},
        "run": run,
        "progress_msg": "gotowe",
        "token_num": 10,
        "chunk_num": 1,
    }


def _chunk(ref: str, document_ref: str, ordinal: int, **overrides: Any) -> dict[str, Any]:
    """Linia ``chunks.jsonl`` wg K19 §2; pola nadpisywane przez ``overrides``."""
    row: dict[str, Any] = {
        "ref": ref,
        "document_ref": document_ref,
        "ordinal": ordinal,
        "chunk_type": "text",
        "content": f"Treść chunka {ref}.",
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
        "token_count": 3,
    }
    row.update(overrides)
    return row


def _vectors(count: int, dim: int) -> list[list[float]]:
    """``count`` wektorów o wymiarze ``dim``; wartość rośnie z indeksem wiersza."""
    return [[float(i * dim + j) for j in range(dim)] for i in range(count)]


def _jsonl(rows: Sequence[Mapping[str, Any]]) -> bytes:
    """Wpis JSONL z linii modelu (puste = pusty wpis)."""
    return b"".join(
        json.dumps(dict(row), ensure_ascii=False).encode("utf-8") + b"\n" for row in rows
    )


def _npy(rows: list[list[float]], dim: int) -> bytes:
    """Wektory jako wpis ``vectors/*.npy`` (NPY 1.0, '<f4')."""
    buf = io.BytesIO()
    fmt.write_npy(buf, rows, dim)
    return buf.getvalue()


def _write_package(  # noqa: PLR0913 — builder paczki testowej z opcjami
    path: Path,
    *,
    documents: Sequence[Mapping[str, Any]],
    chunks: Sequence[Mapping[str, Any]],
    dim: int,
    included: bool,
    vectors: list[list[float]] | None = None,
    blobs: Mapping[str, bytes] | None = None,
) -> int:
    """Buduje paczkę ``.wdkb.zip`` pod ``path``; zwraca rozmiar pliku w bajtach."""
    writer = PackageWriter(path, max_bytes=MAX_BYTES)
    writer.add_bytes(fmt.DOCUMENTS_PATH, _jsonl(documents))
    writer.add_bytes(fmt.CHUNKS_PATH, _jsonl(chunks))
    if vectors:
        writer.add_bytes(fmt.vector_part_path(0), _npy(vectors, dim))
    for entry_path, data in (blobs or {}).items():
        writer.add_bytes(entry_path, data)
    writer.finish(
        _manifest(
            documents=len(documents),
            chunks=len(chunks),
            vectors=len(vectors) if vectors else 0,
            dim=dim,
            included=included,
        )
    )
    return path.stat().st_size


# --- osprzęt zadania -------------------------------------------------------------------------


async def _actor(container: Container) -> str:
    """Wstawia użytkownika-aktora (FK ``datasets.tenant_id`` → ``users``)."""
    user_id = uuid.uuid4().hex
    async with transaction(_sm(container)) as session:
        await users_repo.insert(
            session,
            user_id=user_id,
            email=f"{user_id[:12]}@example.com",
            nickname="Importer",
            password_hash=None,
            auth_source="local",
            oidc_sub=None,
            is_superuser=False,
            is_service=False,
            now_ms=TIME_MS,
        )
    return user_id


def _package_path(container: Container, import_id: str) -> Path:
    """Ścieżka pliku paczki importu (``<storage_root>/imports/<id>.wdkb.zip``)."""
    return Path(container.settings.storage_root) / PREFIX / f"{import_id}{IMPORT_SUFFIX}"


async def _session(container: Container, *, actor: str) -> str:
    """Zakłada sesję ``dataset_imports`` w stanie ``started`` i zwraca jej id."""
    import_id = container.id_gen.new_id()
    now = container.clock.now_ms()
    async with transaction(_sm(container)) as session:
        await imports_repo.insert(
            session,
            id=import_id,
            user_id=actor,
            file_name="p.wdkb.zip",
            size_bytes=1,
            expires_at=now + 86_400_000,
            now_ms=now,
        )
        await imports_repo.set_state(
            session, import_id=import_id, state="started", errors=[], now_ms=now
        )
    return import_id


async def _enqueue(container: Container, payload: Mapping[str, Any]) -> str:
    """Zleca zadanie ``import_dataset`` i zwraca jego public_id."""
    queue = DbTaskQueue(_sm(container), container.clock, container.id_gen)
    return await queue.enqueue(NewTask("import_dataset", payload, max_attempts=3))


async def _claim(container: Container, task_id: str) -> TaskRow:
    """Claim zadania przez ``DbTaskQueue`` (jak slot workera)."""
    queue = DbTaskQueue(_sm(container), container.clock, container.id_gen)
    task = await queue.claim(WORKER_ID, ["import_dataset"])
    assert task is not None and task.id == task_id
    return task


def _ctx(container: Container, task: TaskRow) -> TaskContext:
    """Kontekst zadania dla handlera (logger bez handlera, kolejka z kontenera)."""
    queue = DbTaskQueue(_sm(container), container.clock, container.id_gen)
    logger: logging.LoggerAdapter[logging.Logger] = logging.LoggerAdapter(
        logging.getLogger("test.import_dataset"), {"task_id": task.id}
    )
    return TaskContext(
        task=task, worker_id=WORKER_ID, container=container, logger=logger, queue=queue
    )


async def _execute(container: Container, task: TaskRow) -> str:
    """Wykonuje handler i zapisuje wynik jak ``app.worker.loop`` (classify + queue)."""
    queue = DbTaskQueue(_sm(container), container.clock, container.id_gen)
    ctx = _ctx(container, task)
    try:
        await import_dataset(task, ctx)
    except TaskCancelled:
        await queue.mark_cancelled(task.id, WORKER_ID)
        return "cancelled"
    except Exception as exc:  # noqa: BLE001 — klasyfikacja jak w loop.classify
        transient = classify(exc) == "fail_transient"
        await queue.fail(task.id, WORKER_ID, exc, transient=transient)
        return "queued" if transient else "failed"
    await queue.complete(task.id, WORKER_ID)
    return "done"


def _payload(  # noqa: PLR0913 — pola payloadu z CONTRACT §3
    container: Container,
    *,
    actor: str,
    import_id: str,
    name: str,
    reembed: bool,
    embedding_model: str | None = EMBED_MODEL,
) -> dict[str, Any]:
    """Payload zadania ``import_dataset`` (CONTRACT §3): ``dataset_id`` nadaje wołający."""
    return {
        "actor_id": actor,
        "import_id": import_id,
        "name": name,
        "embedding_model": embedding_model,
        "dataset_id": container.id_gen.new_id(),
        "reembed": reembed,
    }


async def _snapshot(container: Container, task_id: str) -> Any:
    """Wiersz zadania dla tras WD (``payload`` zdekodowany)."""
    return await DbTaskQueue(_sm(container), container.clock, container.id_gen).snapshot(task_id)


async def _session_row(container: Container, import_id: str) -> dict[str, Any] | None:
    """Wiersz sesji importu (odczyt testowy w osobnej transakcji)."""
    async with transaction(_sm(container)) as session:
        return await imports_repo.get(session, import_id)


async def _dataset_count(container: Container, *, actor: str, name: str) -> int:
    """Liczba datasetów aktora o nazwie (bez wielkości liter)."""
    async with transaction(_sm(container)) as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM datasets"
                        " WHERE tenant_id = :tenant AND name_ci = LOWER(:name)"
                    ),
                    {"tenant": actor, "name": name},
                )
            ).scalar_one()
        )


async def _document_runs(container: Container, dataset_id: str) -> list[str]:
    """Kody ``run`` dokumentów datasetu (kolejność nazw) — DONE/„nieuruchomiony"."""
    async with transaction(_sm(container)) as session:
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


async def _vector_count(container: Container, dim: int) -> int:
    """Liczba wierszy w tabeli wektorów wymiaru ``dim``."""
    async with transaction(_sm(container)) as session:
        return int(
            (
                await session.execute(text(f"SELECT COUNT(*) FROM chunk_vec_d{dim}"))  # noqa: S608
            ).scalar_one()
        )


async def _audit_rows(container: Container) -> list[dict[str, Any]]:
    """Wpisy audytu ``dataset_imported`` z ``details`` (odczyt testowy)."""
    async with transaction(_sm(container)) as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT action, target_id, details FROM audit_log"
                        " WHERE action = 'dataset_imported'"
                    )
                )
            )
            .mappings()
            .all()
        )
    return [
        {
            "action": row["action"],
            "target_id": row["target_id"],
            "details": json.loads(row["details"]),
        }
        for row in rows
    ]


def _simple_package(container: Container, import_id: str) -> None:
    """Paczka 1:1: 1 dokument z plikiem i chunk z wektorem (dim ``DIM``)."""
    doc_sha = hashlib.sha256(DOC_BLOB).hexdigest()
    _write_package(
        _package_path(container, import_id),
        documents=[_document("d1", file_sha256=doc_sha)],
        chunks=[_chunk("c1", "d1", 0)],
        dim=DIM,
        included=True,
        vectors=_vectors(1, DIM),
        blobs={f"{fmt.FILES_PREFIX}{doc_sha}": DOC_BLOB},
    )


# --- testy -----------------------------------------------------------------------------------


async def test_import_success_one_to_one(container: Container) -> None:
    """Sukces 1:1: dataset, dokumenty DONE, chunki z wektorami, ``result``, audyt, plik znika."""
    actor = await _actor(container)
    import_id = await _session(container, actor=actor)
    _simple_package(container, import_id)
    payload = _payload(container, actor=actor, import_id=import_id, name="Import 1", reembed=False)
    task_id = await _enqueue(container, payload)
    task = await _claim(container, task_id)

    outcome = await _execute(container, task)

    dataset_id = str(payload["dataset_id"])
    assert outcome == "done"
    assert await _dataset_count(container, actor=actor, name="Import 1") == 1
    assert await _document_runs(container, dataset_id) == ["3"]  # DONE z paczki
    snapshot = await _snapshot(container, task_id)
    assert snapshot.status == "done"
    wd_task = _wd_task(snapshot)
    assert wd_task.kind == "import"
    assert wd_task.result is not None
    assert (wd_task.result.documents, wd_task.result.chunks) == (1, 1)
    assert wd_task.result.dataset_name == "Import 1"
    assert snapshot.payload["result"]["reembedded"] is False
    assert await _vector_count(container, DIM) == 1  # wektor 1:1 z paczki
    rows = await _audit_rows(container)
    assert len(rows) == 1
    assert rows[0]["target_id"] == dataset_id
    assert rows[0]["details"]["task_id"] == task_id
    assert rows[0]["details"]["source_instance_id"] == "0123456789abcdef0123456789abcdef"
    assert rows[0]["details"]["documents"] == 1
    assert rows[0]["details"]["chunks"] == 1
    assert rows[0]["details"]["reembedded"] is False
    assert not _package_path(container, import_id).exists()  # plik usunięty po sukcesie


async def test_import_documents_not_done_are_unstarted(container: Container) -> None:
    """Dokument z paczki o ``run`` innym niż DONE → „nieuruchomiony" (``run='0'``, K19 §2)."""
    actor = await _actor(container)
    import_id = await _session(container, actor=actor)
    doc_sha = hashlib.sha256(DOC_BLOB).hexdigest()
    _write_package(
        _package_path(container, import_id),
        documents=[
            _document("d1", file_sha256=doc_sha, run="3"),  # DONE z paczki
            _document("d2", file_sha256=None, run="1"),  # RUNNING → „nieuruchomiony"
        ],
        chunks=[],
        dim=SOURCE_DIM,
        included=False,
        blobs={f"{fmt.FILES_PREFIX}{doc_sha}": DOC_BLOB},
    )
    payload = _payload(container, actor=actor, import_id=import_id, name="Import 2", reembed=False)
    task_id = await _enqueue(container, payload)
    task = await _claim(container, task_id)

    outcome = await _execute(container, task)

    assert outcome == "done"
    # kolejność nazw: umowa-d1.pdf (DONE) → '3', umowa-d2.pdf → '0'
    assert await _document_runs(container, str(payload["dataset_id"])) == ["3", "0"]


async def test_import_success_with_reembed(container: Container) -> None:
    """Reembed: model docelowy o innym wymiarze → wektory liczone od nowa (``reembedded=true``)."""
    actor = await _actor(container)
    import_id = await _session(container, actor=actor)
    doc_sha = hashlib.sha256(DOC_BLOB).hexdigest()
    _write_package(
        _package_path(container, import_id),
        documents=[_document("d1", file_sha256=doc_sha)],
        chunks=[_chunk("c1", "d1", 0), _chunk("c2", "d1", 1)],
        dim=SOURCE_DIM,
        included=True,
        vectors=_vectors(2, SOURCE_DIM),
        blobs={f"{fmt.FILES_PREFIX}{doc_sha}": DOC_BLOB},
    )
    payload = _payload(container, actor=actor, import_id=import_id, name="Import 3", reembed=True)
    task_id = await _enqueue(container, payload)
    task = await _claim(container, task_id)

    outcome = await _execute(container, task)

    assert outcome == "done"
    snapshot = await _snapshot(container, task_id)
    assert snapshot.payload["result"]["reembedded"] is True
    assert snapshot.payload["result"]["chunks"] == 2  # noqa: PLR2004 — 2 chunki z paczki
    # wektory policzone od nowa modelem docelowym (DIM), paczkowe (SOURCE_DIM) nieużyte
    assert await _vector_count(container, DIM) == 2  # noqa: PLR2004 — 2 chunki z paczki
    assert await _dataset_count(container, actor=actor, name="Import 3") == 1


async def test_stop_during_chunks_cleans_up(container: Container, tmp_path: Path) -> None:
    """Stop (``cancel_requested``) na etapie chunków: cancelled, sprzątanie, sesja invalid."""
    actor = await _actor(container)
    import_id = await _session(container, actor=actor)
    image_sha = hashlib.sha256(IMAGE_DATA).hexdigest()
    # Dokument BEZ pliku (etap „files" nie sprawdza cancel) → pierwszy ``check_cancel`` trafia
    # w ``write_chunks`` (etap chunków), po utworzeniu datasetu i skopiowaniu obrazu.
    _write_package(
        _package_path(container, import_id),
        documents=[_document("d1", file_sha256=None)],
        chunks=[_chunk("c1", "d1", 0, image_sha256=image_sha)],
        dim=SOURCE_DIM,
        included=True,
        vectors=_vectors(1, SOURCE_DIM),
        blobs={f"{fmt.IMAGES_PREFIX}{image_sha}": IMAGE_DATA},
    )
    payload = _payload(container, actor=actor, import_id=import_id, name="Import 4", reembed=False)
    task_id = await _enqueue(container, payload)
    task = await _claim(container, task_id)
    dataset_id = str(payload["dataset_id"])
    queue = DbTaskQueue(_sm(container), container.clock, container.id_gen)
    assert await queue.request_cancel_task(task_id) is True  # Stop na zadaniu running

    outcome = await _execute(container, task)

    assert outcome == "cancelled"
    snapshot = await _snapshot(container, task_id)
    assert snapshot.status == "cancelled"
    assert snapshot.payload["error_code"] == "import_cancelled"
    assert await _dataset_count(container, actor=actor, name="Import 4") == 0
    assert not (tmp_path / "images" / dataset_id).exists()  # bloby obrazów usunięte
    assert not (tmp_path / "files" / dataset_id).exists()
    row = await _session_row(container, import_id)
    assert row is not None and row["state"] == "invalid"
    assert row["errors"][0]["code"] == "import_cancelled"
    assert _package_path(container, import_id).exists()  # plik zostaje do TTL (K19 §5)


async def test_missing_package_blob_is_permanent_invalid_archive(container: Container) -> None:
    """Odwołanie do brakującego ``files/<sha>`` → failed ``invalid_archive``, brak datasetu."""
    actor = await _actor(container)
    import_id = await _session(container, actor=actor)
    # ``file_sha256`` wskazuje wpis, którego NIE ma w paczce — walidator tego nie łapie
    # (nie krzyżuje documents.jsonl z entries), więc ``reader.open_entry`` rzuci ``KeyError``.
    _write_package(
        _package_path(container, import_id),
        documents=[_document("d1", file_sha256=hashlib.sha256(DOC_BLOB).hexdigest())],
        chunks=[],
        dim=SOURCE_DIM,
        included=False,
    )
    payload = _payload(container, actor=actor, import_id=import_id, name="Import 5", reembed=False)
    task_id = await _enqueue(container, payload)
    task = await _claim(container, task_id)

    outcome = await _execute(container, task)

    assert outcome == "failed"
    snapshot = await _snapshot(container, task_id)
    assert snapshot.status == "failed"
    assert snapshot.payload["error_code"] == "invalid_archive"
    error = _wd_task(snapshot).error
    assert error is not None and error.code == "invalid_archive"
    assert await _dataset_count(container, actor=actor, name="Import 5") == 0
    row = await _session_row(container, import_id)
    assert row is not None and row["state"] == "invalid"
    assert row["errors"][0]["code"] == "invalid_archive"


async def test_name_conflict_is_permanent(container: Container) -> None:
    """Nazwa zajęta w międzyczasie → failed ``name_conflict``, tylko istniejący dataset."""
    actor = await _actor(container)
    import_id = await _session(container, actor=actor)
    _simple_package(container, import_id)
    # Dataset o tej samej nazwie w tenancie aktora powstał PO starcie importu.
    existing_id = container.id_gen.new_id()
    async with transaction(_sm(container)) as session:
        await datasets_repo.insert(
            session,
            id=existing_id,
            tenant_id=actor,
            created_by=actor,
            name="Import 6",
            description=None,
            avatar=None,
            language="Polish",
            embedding_model=EMBED_MODEL,
            embedding_dim=DIM,
            permission="me",
            chunk_method="naive",
            parser_config=PARSER_CONFIG,
            now_ms=container.clock.now_ms(),
        )
    payload = _payload(container, actor=actor, import_id=import_id, name="Import 6", reembed=False)
    task_id = await _enqueue(container, payload)
    task = await _claim(container, task_id)

    outcome = await _execute(container, task)

    assert outcome == "failed"
    snapshot = await _snapshot(container, task_id)
    assert snapshot.payload["error_code"] == "name_conflict"
    assert await _dataset_count(container, actor=actor, name="Import 6") == 1  # bez zdublowania
    row = await _session_row(container, import_id)
    assert row is not None and row["errors"][0]["code"] == "name_conflict"


async def test_inconsistent_package_is_permanent_invalid_archive(container: Container) -> None:
    """Niespójna paczka (kolizja klucza w ``chunks``) → failed ``invalid_archive``, nie 500 (§3).

    Walidator nie sprawdza unikalności ``(document_ref, ordinal)``, a ``chunk_id`` jest
    deterministyczny z „dokument:zadanie:porządek” — dwa chunki o tym samym ``ordinal``
    dokumentu przechodzą walidację, a dopiero INSERT w etapie chunków narusza klucz główny.
    ``IntegrityError`` bez nazwy unikatu ``uq_datasets_tenant_name_ci`` mapuje się na
    ``invalid_archive`` (handler), sesja importu → ``invalid``, częściowy dataset sprzątnięty.
    """
    actor = await _actor(container)
    import_id = await _session(container, actor=actor)
    _write_package(
        _package_path(container, import_id),
        documents=[_document("d1", file_sha256=None)],
        # Ten sam ``(document_ref, ordinal)`` → ten sam ``chunk_id`` → kolizja klucza głównego.
        chunks=[_chunk("c1", "d1", 0), _chunk("c2", "d1", 0)],
        dim=SOURCE_DIM,
        included=False,
    )
    payload = _payload(container, actor=actor, import_id=import_id, name="Import 9", reembed=True)
    task_id = await _enqueue(container, payload)
    task = await _claim(container, task_id)

    outcome = await _execute(container, task)

    assert outcome == "failed"
    snapshot = await _snapshot(container, task_id)
    assert snapshot.status == "failed"
    assert snapshot.payload["error_code"] == "invalid_archive"
    error = _wd_task(snapshot).error
    assert error is not None and error.code == "invalid_archive"
    assert error.message == "Paczka jest niespójna (dane niezgodne ze schematem)"
    assert await _dataset_count(container, actor=actor, name="Import 9") == 0
    row = await _session_row(container, import_id)
    assert row is not None and row["state"] == "invalid"
    assert row["errors"][0]["code"] == "invalid_archive"


async def test_broken_package_fails_without_dataset(container: Container) -> None:
    """Uszkodzony ZIP (ponowna walidacja) → failed bez datasetu (K19 §5)."""
    actor = await _actor(container)
    import_id = await _session(container, actor=actor)
    path = _package_path(container, import_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"nie zip\n")
    payload = _payload(container, actor=actor, import_id=import_id, name="Import 7", reembed=False)
    task_id = await _enqueue(container, payload)
    task = await _claim(container, task_id)

    outcome = await _execute(container, task)

    assert outcome == "failed"
    snapshot = await _snapshot(container, task_id)
    assert snapshot.payload["error_code"] == "invalid_archive"
    assert await _dataset_count(container, actor=actor, name="Import 7") == 0


async def test_retry_after_transient_leaves_one_dataset(container: Container) -> None:
    """Ponowienie po restarcie: 1. próba przerwana (transient) bez sprzątania, 2. daje 1 dataset."""
    actor = await _actor(container)
    import_id = await _session(container, actor=actor)
    _simple_package(container, import_id)
    payload = _payload(container, actor=actor, import_id=import_id, name="Import 8", reembed=False)
    task_id = await _enqueue(container, payload)
    dataset_id = str(payload["dataset_id"])
    real_patch = handler_module.patch_payload

    async def _boom(session: Any, *, public_id: str, patch: Mapping[str, Any], now_ms: int) -> None:
        if patch.get("stage") == "chunks":
            raise RuntimeError("worker padł w trakcie (transient)")
        await real_patch(session, public_id=public_id, patch=patch, now_ms=now_ms)

    # 1. próba: awaria na etapie chunków — transient, NIE sprząta (częściowy dataset zostaje).
    handler_module.patch_payload = _boom
    try:
        first = await _claim(container, task_id)
        outcome1 = await _execute(container, first)
    finally:
        handler_module.patch_payload = real_patch
    assert outcome1 == "queued"  # transient → zadanie wraca do kolejki
    assert await _dataset_count(container, actor=actor, name="Import 8") == 1  # ślad po próbie

    # 2. próba: ta sama nazwa/id, sprzątanie na starcie → dokładnie jeden dataset.
    async with transaction(_sm(container)) as session:
        await session.execute(
            text("UPDATE tasks SET next_attempt_at = :now WHERE public_id = :id"),
            {"now": container.clock.now_ms(), "id": task_id},
        )
    second = await _claim(container, task_id)
    outcome2 = await _execute(container, second)

    assert outcome2 == "done"
    assert await _dataset_count(container, actor=actor, name="Import 8") == 1
    assert await _document_runs(container, dataset_id) == ["3"]  # bez resztek 1. próby
