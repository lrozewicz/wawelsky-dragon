"""Testy T2 eksportu bazy wiedzy: handler ``export_dataset`` (K19 §3, CONTRACT E7-1a §3).

Handler uruchamiamy przez ``TaskContext`` z ``DbTaskQueue`` (bez pętli workera): claim zadania,
wywołanie handlera i zapis wyniku tą samą klasyfikacją, co ``app.worker.loop`` (``classify``).
Paczkę buduje ``kb_export_build`` z realnych wierszy DB i storage, a odczytuje ``PackageReader``
po ``validate_package`` — testy ćwiczą więc pełny round-trip (documents/chunks/wektory/obrazy).
Przykłady z briefu T2 pokryte dosłownie; seed: dataset + 2 dokumenty (ten sam blob → dedup),
5 chunków (1 edytowany, 1 ``available=0``, 1 z obrazem), wektory o wymiarze datasetu.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
import zipfile
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from alembic import command
from app.api.wd.kb_schemas import ExportResult
from app.core.config import Settings
from app.core.container import Container
from app.core.ids import UuidV7Generator
from app.core.timeutil import from_ms
from app.db.repositories import chunk_vectors as vectors_repo
from app.db.repositories import datasets as datasets_repo
from app.db.repositories import users as users_repo
from app.db.uow import transaction
from app.services import kb_export_build as build_module
from app.services.kb_export_link import EXPORT_LINK_TTL_S, export_package_path
from app.services.kb_package import format as fmt
from app.services.kb_package.reader import PackageReader
from app.services.kb_package.validate import ValidatedPackage, validate_package
from app.storage.keys import StorageKey, document_key, image_key
from app.worker.context import TaskContext
from app.worker.errors import TaskCancelled
from app.worker.handlers import export_dataset as handler_module
from app.worker.handlers.export_dataset import export_dataset
from app.worker.loop import classify
from app.worker.queue import DbTaskQueue, NewTask, TaskRow
from tests.fakes.clock import FrozenClock
from tests.integration.db.helpers import alembic_cfg

pytestmark = pytest.mark.db

DIM = 8
MAX_BYTES = 100 * 1024 * 1024
MAX_RATIO = 100
TIME_MS = 1790157600000
WORKER_ID = "test-host:1:0"
PARSER_CONFIG: dict[str, Any] = {"chunk_token_num": 128, "delimiter": "\n"}
DOC_BLOB = b"umowa najmu " * 8
IMAGE_DATA = b"\x89PNG\r\n\x1a\n obraz chunka "
PREFIX = "exports"
# Wektory per treść chunka — porządek wektorów w paczce porównujemy z porządkiem linii chunks.jsonl.
VEC_BY_CONTENT: dict[str, list[float]] = {
    "chunk-1": [1.0] * DIM,
    "chunk-2-edited": [2.0] * DIM,
    "chunk-3": [3.0] * DIM,
    "chunk-4": [4.0] * DIM,
    "chunk-5": [5.0] * DIM,
}
# Markery sekretów, które NIE mogą trafić do paczki (wymaganie f).
PROVIDER_KEY = "provider-secret-key-PROVIDER-123"
API_TOKEN = "ragflow-api-token-APIKEY-456"  # noqa: S105 — marker sekretu w teście, nie hasło


@pytest.fixture
def migrated_db(fresh_db: Settings) -> Settings:
    """Świeża baza po migracji do head; sync, bo env.py Alembic robi asyncio.run (C12)."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    return fresh_db


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener (storage w ``tmp_path``) z zamrożonym zegarem i układem storage."""
    instance = Container(
        migrated_db.model_copy(update={"storage_root": str(tmp_path)}),
        clock=FrozenClock(),
        id_gen=UuidV7Generator(),
    )
    await instance.start()
    await instance.storage.ensure_layout()
    yield instance
    await instance.aclose()


def _sm(container: Container) -> async_sessionmaker[Any]:
    """Fabryka sesji z kontenera (istnieje po ``start()``); brak → asercja."""
    sessionmaker = container.sessionmaker
    assert sessionmaker is not None, "container nie wystartował"
    return sessionmaker


# --- seed ------------------------------------------------------------------------------------


async def _actor(container: Container) -> str:
    """Wstawia użytkownika-aktora (FK ``datasets.tenant_id`` → ``users``)."""
    user_id = uuid.uuid4().hex
    async with transaction(_sm(container)) as session:
        await users_repo.insert(
            session,
            user_id=user_id,
            email=f"{user_id[:12]}@example.com",
            nickname="Eksporter",
            password_hash=None,
            auth_source="local",
            oidc_sub=None,
            is_superuser=False,
            is_service=False,
            now_ms=TIME_MS,
        )
    return user_id


async def _dataset(container: Container, actor: str, *, name: str = "Baza źródłowa") -> str:
    """Wstawia dataset o wymiarze ``DIM`` i zwraca jego id."""
    dataset_id = container.id_gen.new_id()
    async with transaction(_sm(container)) as session:
        await datasets_repo.insert(
            session,
            id=dataset_id,
            tenant_id=actor,
            created_by=actor,
            name=name,
            description="opis źródła",
            avatar=None,
            language="Polish",
            embedding_model="fake-embed-8",
            embedding_dim=DIM,
            permission="me",
            chunk_method="naive",
            parser_config=PARSER_CONFIG,
            now_ms=TIME_MS,
        )
    return dataset_id


async def _document(  # noqa: PLR0913 — pełny wiersz dokumentu w seedzie
    container: Container,
    *,
    dataset_id: str,
    actor: str,
    document_id: str,
    name: str,
    blob: bytes,
    run: str = "3",
) -> None:
    """Wgrywa blob dokumentu do storage i wstawia wiersz ``documents`` (``location`` z klucza)."""
    suffix = "pdf"
    location = document_key(dataset_id, document_id, suffix)
    await container.storage.put(StorageKey(location), blob)
    now = container.clock.now_ms()
    async with transaction(_sm(container)) as session:
        await session.execute(
            text(
                "INSERT INTO documents (id, dataset_id, created_by, name, suffix, type, size,"
                " location, content_hash, chunk_method, parser_config, run, progress_msg,"
                " chunk_count, token_count, meta_fields, create_time, create_date,"
                " update_time, update_date)"
                " VALUES (:id, :ds, :by, :name, :suffix, :type, :size, :location, :hash,"
                " 'naive', :pc, :run, :msg, :chunks, :tokens, :meta, :now, :now_date,"
                " :now, :now_date)"
            ),
            {
                "id": document_id,
                "ds": dataset_id,
                "by": actor,
                "name": name,
                "suffix": suffix,
                "type": "pdf",
                "size": len(blob),
                "location": location,
                "hash": "0" * 32,
                "pc": json.dumps(PARSER_CONFIG),
                "run": run,
                "msg": "gotowe",
                "chunks": 0,
                "tokens": 4,
                "meta": json.dumps({"tag": document_id[:4]}),
                "now": now,
                "now_date": from_ms(now).replace(tzinfo=None),
            },
        )


async def _chunk(  # noqa: PLR0913 — pełny wiersz chunka w seedzie
    container: Container,
    *,
    dataset_id: str,
    document_id: str,
    chunk_id: str,
    ordinal: int,
    content: str,
    available: bool = True,
    image_id: str | None = None,
) -> None:
    """Wstawia ``committed=1`` chunk z treścią, dostępnością i opcjonalnym obrazem."""
    now = container.clock.now_ms()
    async with transaction(_sm(container)) as session:
        await session.execute(
            text(
                "INSERT INTO chunks (id, document_id, dataset_id, ordinal, chunk_type, content,"
                " content_ft, content_stem, title_ft, keywords, questions, important_ft,"
                " question_ft, tags, positions, image_id, available, committed, token_count,"
                " embed_source, create_time, create_date, update_time, update_date)"
                " VALUES (:id, :doc, :ds, :ordinal, 'text', :content, :content, '', '', '[]',"
                " '[]', '', '', '{}', NULL, :image_id, :available, 1, 3, 'content',"
                " :now, :now_date, :now, :now_date)"
            ),
            {
                "id": chunk_id,
                "doc": document_id,
                "ds": dataset_id,
                "ordinal": ordinal,
                "content": content,
                "image_id": image_id,
                "available": int(available),
                "now": now,
                "now_date": from_ms(now).replace(tzinfo=None),
            },
        )


async def _vectors(
    container: Container, *, dataset_id: str, rows: Sequence[tuple[str, list[float]]]
) -> None:
    """Tworzy tabelę wektorów wymiaru ``DIM`` (DDL osobno) i wstawia wektory chunków."""
    async with transaction(_sm(container)) as session:
        await vectors_repo.ensure_table(session, DIM)
    async with transaction(_sm(container)) as session:
        await vectors_repo.insert_many(
            session, DIM, [(chunk_id, dataset_id, values) for chunk_id, values in rows]
        )


async def _seed(container: Container) -> dict[str, str]:
    """Seed briefu: dataset, 2 dokumenty (ten sam blob), 5 chunków, wektory, obraz."""
    actor = await _actor(container)
    dataset_id = await _dataset(container, actor)
    doc1, doc2 = container.id_gen.new_id(), container.id_gen.new_id()
    await _document(
        container, dataset_id=dataset_id, actor=actor, document_id=doc1, name="a.pdf", blob=DOC_BLOB
    )
    await _document(
        container, dataset_id=dataset_id, actor=actor, document_id=doc2, name="b.pdf", blob=DOC_BLOB
    )
    image_sha = hashlib.sha256(IMAGE_DATA).hexdigest()
    await container.storage.put(image_key(dataset_id, image_sha), IMAGE_DATA)
    # chunk.id to CHAR(16) — krótki identyfikator jak z ``chunks_repo.chunk_id`` (xxh64).
    chunks = [
        (uuid.uuid4().hex[:16], doc1, 0, "chunk-1", True, None),
        (uuid.uuid4().hex[:16], doc1, 1, "chunk-2-edited", True, None),
        (uuid.uuid4().hex[:16], doc1, 2, "chunk-3", False, None),
        (uuid.uuid4().hex[:16], doc2, 0, "chunk-4", True, f"{dataset_id}-{image_sha}"),
        (uuid.uuid4().hex[:16], doc2, 1, "chunk-5", True, None),
    ]
    for chunk_id, doc, ordinal, content, available, image_id in chunks:
        await _chunk(
            container,
            dataset_id=dataset_id,
            document_id=doc,
            chunk_id=chunk_id,
            ordinal=ordinal,
            content=content,
            available=available,
            image_id=image_id,
        )
    await _vectors(
        container,
        dataset_id=dataset_id,
        rows=[(chunk_id, VEC_BY_CONTENT[content]) for chunk_id, _, _, content, _, _ in chunks],
    )
    return {"actor": actor, "dataset_id": dataset_id, "image_sha": image_sha}


# --- osprzęt zadania -------------------------------------------------------------------------


async def _enqueue(
    container: Container, *, actor: str, dataset_id: str, include_vectors: bool
) -> str:
    """Zleca zadanie ``export_dataset`` (CONTRACT §3) i zwraca jego public_id."""
    queue = DbTaskQueue(_sm(container), container.clock, container.id_gen)
    payload = {"actor_id": actor, "include_vectors": include_vectors}
    return await queue.enqueue(
        NewTask("export_dataset", payload, dataset_id=dataset_id, max_attempts=3)
    )


async def _claim(container: Container, task_id: str) -> TaskRow:
    """Claim zadania przez ``DbTaskQueue`` (jak slot workera)."""
    queue = DbTaskQueue(_sm(container), container.clock, container.id_gen)
    task = await queue.claim(WORKER_ID, ["export_dataset"])
    assert task is not None and task.id == task_id
    return task


def _ctx(container: Container, task: TaskRow) -> TaskContext:
    """Kontekst zadania dla handlera (logger bez handlera, kolejka z kontenera)."""
    queue = DbTaskQueue(_sm(container), container.clock, container.id_gen)
    logger: logging.LoggerAdapter[logging.Logger] = logging.LoggerAdapter(
        logging.getLogger("test.export_dataset"), {"task_id": task.id}
    )
    return TaskContext(
        task=task, worker_id=WORKER_ID, container=container, logger=logger, queue=queue
    )


async def _execute(container: Container, task: TaskRow) -> str:
    """Wykonuje handler i zapisuje wynik jak ``app.worker.loop`` (classify + queue)."""
    queue = DbTaskQueue(_sm(container), container.clock, container.id_gen)
    ctx = _ctx(container, task)
    try:
        await export_dataset(task, ctx)
    except TaskCancelled:
        await queue.mark_cancelled(task.id, WORKER_ID)
        return "cancelled"
    except Exception as exc:  # noqa: BLE001 — klasyfikacja jak w loop.classify
        transient = classify(exc) == "fail_transient"
        await queue.fail(task.id, WORKER_ID, exc, transient=transient)
        return "queued" if transient else "failed"
    await queue.complete(task.id, WORKER_ID)
    return "done"


async def _snapshot(container: Container, task_id: str) -> Any:
    """Wiersz zadania dla tras WD (``payload`` zdekodowany)."""
    return await DbTaskQueue(_sm(container), container.clock, container.id_gen).snapshot(task_id)


async def _audit_rows(container: Container) -> list[dict[str, Any]]:
    """Wpisy audytu ``dataset_exported`` z ``details`` (odczyt testowy)."""
    async with transaction(_sm(container)) as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT action, target_id, details FROM audit_log"
                        " WHERE action = 'dataset_exported'"
                    )
                )
            )
            .mappings()
            .all()
        )
    return [
        {"action": r["action"], "target_id": r["target_id"], "details": json.loads(r["details"])}
        for r in rows
    ]


async def _db_chunk_contents(container: Container, dataset_id: str) -> list[str]:
    """Treści chunków ``committed=1`` w kolejności ``(document_id, ordinal)`` — porządek paczki."""
    async with transaction(_sm(container)) as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT content FROM chunks WHERE dataset_id = :ds AND committed = 1"
                        " ORDER BY document_id, ordinal"
                    ),
                    {"ds": dataset_id},
                )
            )
            .scalars()
            .all()
        )
    return [str(row) for row in rows]


# --- testy -----------------------------------------------------------------------------------


async def test_export_success_round_trip(container: Container) -> None:
    """Sukces: poprawna paczka (walidator + reader), dedup, obraz, audyt, ``result``."""
    seed = await _seed(container)
    task_id = await _enqueue(
        container, actor=seed["actor"], dataset_id=seed["dataset_id"], include_vectors=True
    )
    task = await _claim(container, task_id)

    outcome = await _execute(container, task)

    assert outcome == "done"
    path = export_package_path(container.settings.storage_root, task_id)
    assert path.exists()
    assert not path.with_name(path.name + ".part").exists()
    validated = validate_package(path, max_bytes=MAX_BYTES, max_ratio=MAX_RATIO)
    assert isinstance(validated, ValidatedPackage)
    manifest = validated.manifest
    assert manifest.counts.documents == 2  # noqa: PLR2004
    assert manifest.counts.chunks == 5  # noqa: PLR2004
    assert manifest.counts.vectors == 5  # noqa: PLR2004
    assert manifest.embedding.included is True
    assert manifest.dataset.name == "Baza źródłowa"
    assert manifest.embedding.dimension == DIM
    reader = PackageReader(validated)
    doc_sha = hashlib.sha256(DOC_BLOB).hexdigest()
    documents = list(reader.documents())
    assert len(documents) == 2  # noqa: PLR2004
    assert {line.file_sha256 for line in documents} == {doc_sha}
    # dedup: dwa dokumenty o tej samej treści → jeden wpis files/<sha>
    file_entries = [e for e in manifest.entries if e.path.startswith(fmt.FILES_PREFIX)]
    assert [e.path for e in file_entries] == [f"{fmt.FILES_PREFIX}{doc_sha}"]
    chunks = list(reader.chunks())
    assert [line.content for line in chunks] == await _db_chunk_contents(
        container, seed["dataset_id"]
    )
    assert {"chunk-2-edited"} <= {line.content for line in chunks}  # edycja zachowana
    disabled = [line for line in chunks if not line.available]
    assert [line.content for line in disabled] == ["chunk-3"]
    image_lines = [line for line in chunks if line.image_sha256 is not None]
    assert [line.image_sha256 for line in image_lines] == [seed["image_sha"]]
    # kolejność wektorów = kolejność chunków
    assert list(reader.vectors()) == [VEC_BY_CONTENT[line.content] for line in chunks]
    rows = await _audit_rows(container)
    assert len(rows) == 1
    assert rows[0]["target_id"] == seed["dataset_id"]
    assert rows[0]["details"] == {
        "dataset_id": seed["dataset_id"],
        "task_id": task_id,
        "include_vectors": True,
        "size_bytes": path.stat().st_size,
    }
    result = _wd_result(await _snapshot(container, task_id))
    assert set(result.model_dump()) == {"download_url", "expires_at", "size_bytes", "file_name"}
    assert result.file_name == "baza-zrodlowa.wdkb.zip"
    assert result.expires_at == (TIME_MS // 1000 + EXPORT_LINK_TTL_S) * 1000
    assert result.size_bytes == path.stat().st_size


def _wd_result(snapshot: Any) -> ExportResult:
    """``payload.result`` zadania jako model ``ExportResult`` (K19 §3)."""
    return ExportResult.model_validate(snapshot.payload["result"])


async def test_export_without_vectors(container: Container) -> None:
    """``include_vectors=False``: brak ``vectors/*``, ``counts.vectors=0``, ``included=false``."""
    seed = await _seed(container)
    task_id = await _enqueue(
        container, actor=seed["actor"], dataset_id=seed["dataset_id"], include_vectors=False
    )
    task = await _claim(container, task_id)

    outcome = await _execute(container, task)

    assert outcome == "done"
    path = export_package_path(container.settings.storage_root, task_id)
    validated = validate_package(path, max_bytes=MAX_BYTES, max_ratio=MAX_RATIO)
    assert isinstance(validated, ValidatedPackage)
    assert validated.manifest.embedding.included is False
    assert validated.manifest.counts.vectors == 0
    assert not [e for e in validated.manifest.entries if e.path.startswith(fmt.VECTORS_PREFIX)]
    assert list(PackageReader(validated).vectors()) == []


async def test_export_progress_stages_and_messages(
    container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Postęp: etapy ``files→chunks→vectors→finalize`` i komunikaty „Chunki …/…” po partiach."""
    seed = await _seed(container)
    # Partia odczytu musiała zostać zmniejszona, żeby 5 chunków dało kilka wywołań ``stage``.
    # Etap ``chunks`` woła ``export_data.iter_chunks`` bez ``batch``, więc działa domyślny argument
    # funkcji — wiązanie w czasie definicji (patch ``CHUNKS_BATCH`` na module go NIE zmieni);
    # ``_write_vectors`` czyta ``export_data.CHUNKS_BATCH`` w czasie wywołania. Stąd dwa patche.
    monkeypatch.setattr(build_module.export_data, "CHUNKS_BATCH", 2)
    monkeypatch.setattr(build_module.export_data.iter_chunks, "__kwdefaults__", {"batch": 2})
    stages: list[str] = []
    real_patch = handler_module.patch_payload

    async def _record(
        session: Any, *, public_id: str, patch: Mapping[str, Any], now_ms: int
    ) -> None:
        if "stage" in patch:
            stages.append(str(patch["stage"]))
        await real_patch(session, public_id=public_id, patch=patch, now_ms=now_ms)

    monkeypatch.setattr(handler_module, "patch_payload", _record)
    task_id = await _enqueue(
        container, actor=seed["actor"], dataset_id=seed["dataset_id"], include_vectors=True
    )
    task = await _claim(container, task_id)
    ctx = _ctx(container, task)
    messages: list[str] = []
    real_report = ctx.report

    async def _report(progress: float, msg: str | None = None) -> None:
        if msg is not None:
            messages.append(msg)
        await real_report(progress, msg)

    ctx.report = _report  # type: ignore[method-assign]

    await export_dataset(task, ctx)

    distinct = list(dict.fromkeys(stages))
    assert distinct == ["files", "chunks", "vectors", "finalize"]
    # 5 chunków w partiach po 2 → postęp rośnie w trzech krokach (dowód, że partia jest mała
    # i że komunikat niesie licznik, a nie jednorazowe „Chunki 5/5”).
    assert [msg for msg in messages if msg.startswith("Chunki ")] == [
        "Chunki 2/5",
        "Chunki 4/5",
        "Chunki 5/5",
    ]
    assert [msg for msg in messages if msg.startswith("Wektory ")] == [
        "Wektory 2/5",
        "Wektory 4/5",
        "Wektory 5/5",
    ]


async def test_stop_removes_partial_and_final(
    container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stop (``TaskCancelled`` w 2. sprawdzeniu) → brak ``.part`` i brak pliku końcowego."""
    seed = await _seed(container)
    task_id = await _enqueue(
        container, actor=seed["actor"], dataset_id=seed["dataset_id"], include_vectors=True
    )
    task = await _claim(container, task_id)
    real_cls = handler_module._TaskProgress

    class _StopOnSecond(real_cls):  # type: ignore[misc, valid-type]
        """Postęp, który przy drugim ``check_cancel`` zgłasza Stop (jak cancel_requested)."""

        def __init__(self, ctx: TaskContext) -> None:
            super().__init__(ctx)
            self._calls = 0

        async def check_cancel(self) -> None:
            self._calls += 1
            if self._calls >= 2:  # noqa: PLR2004 — stop w 2. sprawdzeniu (brief T2, wymaganie d)
                raise TaskCancelled("stop w trakcie budowy")
            await super().check_cancel()

    monkeypatch.setattr(handler_module, "_TaskProgress", _StopOnSecond)

    outcome = await _execute(container, task)

    assert outcome == "cancelled"
    path = export_package_path(container.settings.storage_root, task_id)
    assert not path.exists()
    assert not path.with_name(path.name + ".part").exists()


async def test_retry_leaves_single_package(container: Container) -> None:
    """Ponowienie na tym samym zadaniu zostawia dokładnie jedną paczkę ``exports/<id>.wdkb.zip``."""
    seed = await _seed(container)
    task_id = await _enqueue(
        container, actor=seed["actor"], dataset_id=seed["dataset_id"], include_vectors=True
    )
    task = await _claim(container, task_id)
    ctx = _ctx(container, task)

    await export_dataset(task, ctx)
    await export_dataset(task, ctx)

    exports_dir = Path(container.settings.storage_root) / PREFIX
    assert sorted(p.name for p in exports_dir.iterdir()) == [f"{task_id}.wdkb.zip"]


async def test_permanent_failure_package_too_large_sets_error_code(
    container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Porażka trwała ``package_too_large``: ``payload.error_code`` i brak pliku paczki."""
    seed = await _seed(container)
    # Limit paczki poniżej documents.jsonl → pierwszy ``add_file`` rzuca „package too large”.
    monkeypatch.setattr(container.settings, "export_max_bytes", 16)
    task_id = await _enqueue(
        container, actor=seed["actor"], dataset_id=seed["dataset_id"], include_vectors=True
    )
    task = await _claim(container, task_id)

    outcome = await _execute(container, task)

    assert outcome == "failed"
    assert (await _snapshot(container, task_id)).payload["error_code"] == "package_too_large"
    path = export_package_path(container.settings.storage_root, task_id)
    assert not path.exists()
    assert not path.with_name(path.name + ".part").exists()


async def test_permanent_failure_manifest_too_large_sets_error_code(
    container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Porażka trwała ``manifest_too_large``: ``payload.error_code`` i brak pliku paczki."""
    seed = await _seed(container)
    # Manifest zawsze „za duży” → ``ManifestTooLarge`` przed ``writer.finish``.
    monkeypatch.setattr(fmt, "MANIFEST_MAX_BYTES", 0)
    task_id = await _enqueue(
        container, actor=seed["actor"], dataset_id=seed["dataset_id"], include_vectors=True
    )
    task = await _claim(container, task_id)

    outcome = await _execute(container, task)

    assert outcome == "failed"
    assert (await _snapshot(container, task_id)).payload["error_code"] == "manifest_too_large"
    path = export_package_path(container.settings.storage_root, task_id)
    assert not path.exists()
    assert not path.with_name(path.name + ".part").exists()


async def test_package_has_no_secrets(container: Container) -> None:
    """Paczka (wpisy i surowy ZIP) nie zawiera żadnych sekretów konfiguracji ani kluczy."""

    async def _scan(needles: Sequence[bytes], haystack: bytes) -> None:
        for needle in needles:
            assert needle not in haystack

    seed = await _seed(container)
    await _seed_provider_and_key(container, actor=seed["actor"])
    task_id = await _enqueue(
        container, actor=seed["actor"], dataset_id=seed["dataset_id"], include_vectors=True
    )
    task = await _claim(container, task_id)
    await _execute(container, task)

    path = export_package_path(container.settings.storage_root, task_id)
    settings = container.settings
    secrets = [
        settings.secret_key.get_secret_value(),
        settings.crypto_key.get_secret_value(),
        settings.db_password.get_secret_value(),
        PROVIDER_KEY,
        API_TOKEN,
        hashlib.sha256(API_TOKEN.encode()).hexdigest(),
    ]
    needles = [s.encode() for s in secrets if s] + [API_TOKEN.encode()]
    raw = path.read_bytes()
    await _scan(needles, raw)
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            with archive.open(info) as fp:
                await _scan(needles, fp.read())


async def _seed_provider_and_key(container: Container, *, actor: str) -> None:
    """Wstawia instancję dostawcy z kluczem i klucz API (markery wymagania f)."""
    now = container.clock.now_ms()
    async with transaction(_sm(container)) as session:
        await session.execute(
            text(
                "INSERT INTO provider_instances (id, provider, name, base_url, api_key_enc,"
                " created_by, create_time, create_date, update_time, update_date)"
                " VALUES (:id, 'openai', 'prov', 'https://x.example', :key, :by, :now,"
                " :now_date, :now, :now_date)"
            ),
            {
                "id": container.id_gen.new_id(),
                "key": PROVIDER_KEY.encode(),
                "by": actor,
                "now": now,
                "now_date": from_ms(now).replace(tzinfo=None),
            },
        )
        await session.execute(
            text(
                "INSERT INTO api_keys (id, user_id, token_hash, token_enc, prefix, name,"
                " create_time, create_date, update_time, update_date)"
                " VALUES (:id, :by, :hash, :enc, :prefix, 'k', :now, :now_date, :now, :now_date)"
            ),
            {
                "id": container.id_gen.new_id(),
                "by": actor,
                "hash": hashlib.sha256(API_TOKEN.encode()).hexdigest(),
                "enc": API_TOKEN.encode(),
                "prefix": "ragflow-",
                "now": now,
                "now_date": from_ms(now).replace(tzinfo=None),
            },
        )
