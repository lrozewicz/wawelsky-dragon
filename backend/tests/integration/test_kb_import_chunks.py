"""Testy T3 importu bazy wiedzy: chunki, obrazy i wektory 1:1 (K19 §2/§5, CONTRACT E7-1b §2).

Paczki buduje ``PackageWriter`` i przechodzą ``validate_package`` (round-trip), więc testy ćwiczą
realny czytnik paczki. Kolumny pochodne porównujemy z ``ft_text``/``stem_text`` — tym samym
źródłem, którego używa ingestia (brief T3). Rozstrzygnięcia: DEC-328 (pola pochodne), DEC-326
(content_hash jako xxh128 w T2).
"""

from __future__ import annotations

import hashlib
import io
import json
import uuid
from collections import Counter
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from alembic import command
from app.core.config import Settings
from app.core.container import Container
from app.core.ids import UuidV7Generator
from app.db.repositories import chunk_vectors
from app.db.repositories import datasets as datasets_repo
from app.db.repositories import documents as documents_repo
from app.db.repositories import users as users_repo
from app.db.repositories.chunks import chunk_id
from app.db.repositories.documents import DocumentRow
from app.db.uow import transaction
from app.services.kb_import_chunks import write_chunks
from app.services.kb_import_write import ImportPlan, create_dataset_with_documents
from app.services.kb_package import format as fmt
from app.services.kb_package.validate import ValidatedPackage, validate_package
from app.services.kb_package.writer import PackageWriter
from app.storage.keys import StorageKey, image_key
from app.text.fulltext import ft_text, stem_text
from app.worker.errors import PermanentError, TaskCancelled
from tests.fakes.clock import FrozenClock
from tests.integration.db.helpers import alembic_cfg

pytestmark = pytest.mark.db

MAX_BYTES = 100 * 1024 * 1024
MAX_RATIO = 100
DIM = 8  # wymiar wektorów paczki testowej (tabela chunk_vec_d8)
TIME_MS = 1790157600000
DOC_BLOB = b"umowa najmu " * 64
IMAGE_DATA = b"\x89PNG\r\n\x1a\n obraz chunka "
PARSER_CONFIG: dict[str, Any] = {"chunk_token_num": 128, "delimiter": "\n"}


@pytest.fixture
def migrated_db(fresh_db: Settings) -> Settings:
    """Świeża baza po migracji do head; sync, bo env.py Alembic robi asyncio.run (C12)."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    return fresh_db


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener na zmigrowanej bazie, storage w tmp_path (wzór: test_kb_import_write)."""
    instance = Container(
        migrated_db.model_copy(update={"storage_root": str(tmp_path)}),
        clock=FrozenClock(),
        id_gen=UuidV7Generator(),
    )
    await instance.start()
    yield instance
    await instance.aclose()


class FakeProgress:
    """Fake ``ImportProgress``: zapisuje etapy i potrafi przerwać na N-tym ``check_cancel``."""

    def __init__(self, *, cancel_on_check: int | None = None) -> None:
        self.stages: list[tuple[str, int, int]] = []
        self.checks = 0
        self._cancel_on_check = cancel_on_check

    async def stage(self, stage: str, done: int, total: int) -> None:
        """Zapisuje wywołanie etapu postępu."""
        self.stages.append((stage, done, total))

    async def check_cancel(self) -> None:
        """Liczy wywołania; przy ``cancel_on_check`` rzuca ``TaskCancelled`` (jak handler T7)."""
        self.checks += 1
        if self._cancel_on_check is not None and self.checks >= self._cancel_on_check:
            raise TaskCancelled("task-test")


def _manifest(*, documents: int, chunks: int, vectors: int, included: bool = True) -> fmt.Manifest:
    """Manifest paczki testowej; ``included`` mówi, czy paczka niesie wektory (wymiar ``DIM``)."""
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
            "embedding": {"model_name": "fake-embed-8", "dimension": DIM, "included": included},
            "counts": {"documents": documents, "chunks": chunks, "vectors": vectors},
            "entries": [],
        }
    )


def _document(ref: str, *, file_sha256: str | None, size: int) -> dict[str, Any]:
    """Linia ``documents.jsonl`` wg K19 §2."""
    return {
        "ref": ref,
        # Podwójna spacja: ``title_ft`` musi przejść przez ``ft_text`` (nie jest tożsamością)
        "name": f"umowa  {ref}.pdf",
        "type": "pdf",
        "suffix": "pdf",
        "size": size,
        "file_sha256": file_sha256,
        "chunk_method": "naive",
        "parser_config": PARSER_CONFIG,
        "meta_fields": {"tag": ref},
        "run": "3",  # DONE — run surowe (K19 §2)
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
        # CRLF + podwójna spacja: ``content_ft``/``content_stem`` muszą normalizować (nie tożsamość)
        "content": f"Treść  chunka {ref}.\r\nDruga linia.",
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


def _vectors(count: int) -> list[list[float]]:
    """``count`` wektorów o wymiarze ``DIM``; wartość wiersza i rośnie z indeksem."""
    return [[float(i * DIM + j) for j in range(DIM)] for i in range(count)]


def _jsonl(rows: Sequence[dict[str, Any]]) -> bytes:
    """Wpis JSONL z linii modelu."""
    return b"".join(json.dumps(row, ensure_ascii=False).encode("utf-8") + b"\n" for row in rows)


def _npy(rows: list[list[float]]) -> bytes:
    """Wektory jako wpis ``vectors/*.npy`` (NPY 1.0, '<f4')."""
    buf = io.BytesIO()
    fmt.write_npy(buf, rows, DIM)
    return buf.getvalue()


def _package(  # noqa: PLR0913 — builder paczki testowej z opcjami
    path: Path,
    *,
    documents: Sequence[dict[str, Any]],
    chunks: Sequence[dict[str, Any]],
    vectors: list[list[float]],
    blobs: dict[str, bytes],
    validate: bool = True,
    included: bool = True,
) -> ValidatedPackage:
    """Buduje paczkę; ``validate=False`` zwraca ją bez walidacji (test niespójności wektorów)."""
    writer = PackageWriter(path, max_bytes=MAX_BYTES)
    writer.add_bytes(fmt.DOCUMENTS_PATH, _jsonl(documents))
    writer.add_bytes(fmt.CHUNKS_PATH, _jsonl(chunks))
    if vectors:
        writer.add_bytes(fmt.vector_part_path(0), _npy(vectors))
    for entry_path, data in blobs.items():
        writer.add_bytes(entry_path, data)
    manifest = _manifest(
        documents=len(documents), chunks=len(chunks), vectors=len(vectors), included=included
    )
    writer.finish(manifest)  # finish uzupełnia manifest.entries (writer.py)
    if not validate:
        return ValidatedPackage(path=path, manifest=manifest)
    validated = validate_package(path, max_bytes=MAX_BYTES, max_ratio=MAX_RATIO)
    assert isinstance(validated, ValidatedPackage), validated  # paczka testowa musi być poprawna
    return validated


def _plan(dataset_id: str, actor_id: str) -> ImportPlan:
    """Plan importu: id ustala wołający (handler T7), model/wymiar docelowy."""
    return ImportPlan(
        dataset_id=dataset_id,
        actor_id=actor_id,
        name="Import 1",
        embedding_model="fake-embed-8",
        embedding_dim=DIM,
        reembed=False,
        task_public_id="a" * 32,
    )


async def _actor(container: Container) -> str:
    """Wstawia użytkownika-aktora (FK ``datasets.tenant_id`` → ``users``)."""
    user_id = uuid.uuid4().hex
    async with transaction(container.sessionmaker) as session:
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


async def _chunk_rows(container: Container, dataset_id: str) -> dict[str, Any]:
    """Surowe wiersze ``chunks`` datasetu po id (odczyt testowy, bez mapowania na model)."""
    async with transaction(container.sessionmaker) as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT id, document_id, ordinal, chunk_type, content, content_llm,"
                        " content_ft, content_stem, title_ft, keywords, questions, important_ft,"
                        " question_ft, tags, positions, page_from, page_to, image_id, parent_id,"
                        " available, committed, task_id, token_count, embed_source"
                        " FROM chunks WHERE dataset_id = :ds"
                    ),
                    {"ds": dataset_id},
                )
            )
            .mappings()
            .all()
        )
    return {row["id"]: row for row in rows}


async def _vectors_in_db(container: Container) -> dict[str, list[float]]:
    """Wektory z ``chunk_vec_d8`` jako JSON listy liczb (``VEC_ToText``)."""
    async with transaction(container.sessionmaker) as session:
        table = chunk_vectors.table_name(DIM)
        rows = (
            (
                await session.execute(
                    text(f"SELECT chunk_id, VEC_ToText(embedding) AS v FROM {table}")  # noqa: S608
                )
            )
            .mappings()
            .all()
        )
    return {row["chunk_id"]: json.loads(row["v"]) for row in rows}


async def _document_rows(container: Container, dataset_id: str) -> list[DocumentRow]:
    """Wiersze dokumentów datasetu w kolejności ``create_time, id``."""
    async with transaction(container.sessionmaker) as session:
        ids = await datasets_repo.list_document_ids(session, dataset_id)
        return await documents_repo.get_many(session, ids)


async def _dataset(container: Container, dataset_id: str) -> datasets_repo.DatasetRecord | None:
    """Rekord datasetu (odczyt testowy w osobnej transakcji)."""
    async with transaction(container.sessionmaker) as session:
        return await datasets_repo.get_record(session, dataset_id)


async def _read_blob(container: Container, key: StorageKey) -> bytes:
    """Treść bloba ze storage (odczyt testowy)."""
    return b"".join([chunk async for chunk in container.storage.open(key)])


async def test_write_chunks_stores_chunks_images_and_vectors(  # noqa: PLR0915 — jeden scenariusz
    container: Container, tmp_path: Path
) -> None:
    """5 chunków: pola pochodne, available, obrazy, wektory, parent_id i liczniki (przykład 1)."""
    actor = await _actor(container)
    doc_sha = hashlib.sha256(DOC_BLOB).hexdigest()
    image_sha = hashlib.sha256(IMAGE_DATA).hexdigest()
    documents = [
        _document("d1", file_sha256=doc_sha, size=len(DOC_BLOB)),
        _document("d2", file_sha256=None, size=0),
    ]
    chunks = [
        _chunk("c1", "d1", 0, questions=["Co  to\r\njest?"], positions=[[0, 0, 10, 20, 30]]),
        _chunk("c2", "d1", 1, parent_ref="c1"),
        _chunk("c3", "d1", 2, available=False),
        _chunk("c4", "d2", 0, image_sha256=image_sha),
        _chunk(
            "c5", "d2", 1, keywords=["umowa  1"], questions=["Ile  razy?"], content_llm="<p>x</p>"
        ),
    ]
    vectors = _vectors(5)
    pkg = _package(
        tmp_path / "p.wdkb.zip",
        documents=documents,
        chunks=chunks,
        vectors=vectors,
        blobs={
            f"{fmt.FILES_PREFIX}{doc_sha}": DOC_BLOB,
            f"{fmt.IMAGES_PREFIX}{image_sha}": IMAGE_DATA,
        },
    )
    plan = _plan(uuid.uuid4().hex, actor)
    progress = FakeProgress()

    ids = await create_dataset_with_documents(
        container, pkg=pkg, plan=plan, progress=FakeProgress()
    )
    mapping = await write_chunks(
        container, pkg=pkg, plan=plan, doc_ids=ids, progress=progress, with_vectors=True
    )

    assert set(mapping) == {"c1", "c2", "c3", "c4", "c5"}
    # id deterministyczne (chunk_id z pól), mapa ref→id
    assert mapping["c1"] == chunk_id(ids["d1"], plan.task_public_id, 0)
    assert mapping["c4"] == chunk_id(ids["d2"], plan.task_public_id, 0)
    assert len(set(mapping.values())) == len(mapping)

    rows = await _chunk_rows(container, plan.dataset_id)
    assert len(rows) == len(mapping)
    names = {"d1": "umowa  d1.pdf", "d2": "umowa  d2.pdf"}
    by_ref = {ref: rows[cid] for ref, cid in mapping.items()}
    for ref, new_id in mapping.items():
        row = rows[new_id]
        content = by_ref[ref]["content"]
        assert row["content"] == content
        assert row["content_ft"] == ft_text(content)  # kolumny pochodne jak ingestia
        assert row["content_stem"] == stem_text(content)
        assert row["committed"] == 1  # od razu widoczny
        assert row["task_id"] is None  # kolumna NULL-owalna (DDL 0001)
        assert row["available"] == (0 if ref == "c3" else 1)  # available z paczki
    # dane wymagają normalizacji: kolumna pochodna MUSI różnić się od surowej treści (CRLF, spacje)
    assert by_ref["c1"]["content_ft"] != by_ref["c1"]["content"]
    assert by_ref["c1"]["content_stem"] != by_ref["c1"]["content"]
    # available z paczki zachowane (edycje ręczne przetrwają A→B)
    assert by_ref["c3"]["available"] == 0
    # title_ft z nazwy dokumentu (Path(name).stem), znormalizowane (podwójna spacja)
    assert by_ref["c1"]["title_ft"] == ft_text(Path(names["d1"]).stem)
    assert by_ref["c4"]["title_ft"] == ft_text(Path(names["d2"]).stem)
    assert by_ref["c1"]["title_ft"] != Path(names["d1"]).stem
    # important_ft/question_ft też przez ft_text (podwójna spacja/CRLF w danych wejściowych)
    assert by_ref["c5"]["important_ft"] == ft_text("umowa  1")
    assert by_ref["c5"]["important_ft"] != "umowa  1"
    assert by_ref["c1"]["question_ft"] == ft_text("Co  to\r\njest?")
    assert by_ref["c1"]["question_ft"] != "Co  to\r\njest?"
    # questions/keywords/positions 1:1 z paczki (do kolumn JSON bez normalizacji)
    assert json.loads(by_ref["c1"]["questions"]) == ["Co  to\r\njest?"]
    assert json.loads(by_ref["c1"]["positions"]) == [[0, 0, 10, 20, 30]]
    assert json.loads(by_ref["c5"]["keywords"]) == ["umowa  1"]
    assert json.loads(by_ref["c5"]["questions"]) == ["Ile  razy?"]
    assert by_ref["c5"]["content_llm"] == "<p>x</p>"
    # parent_ref → parent_id (rodzic wcześniej w chunks.jsonl)
    assert by_ref["c2"]["parent_id"] == mapping["c1"]
    assert by_ref["c1"]["parent_id"] is None
    # obraz: blob pod image_key(dataset_id, sha) i image_id = "{dataset_id}-{sha}"
    expected_image_id = f"{plan.dataset_id}-{image_sha}"
    assert by_ref["c4"]["image_id"] == expected_image_id
    dataset_id, _, object_key = expected_image_id.partition("-")  # rozwiązanie trasy obrazu
    assert (dataset_id, object_key) == (plan.dataset_id, image_sha)
    assert await _read_blob(container, image_key(plan.dataset_id, object_key)) == IMAGE_DATA
    # wektory 1:1 (kolejność chunków), tabela wymiaru docelowego
    db_vectors = await _vectors_in_db(container)
    assert set(db_vectors) == set(mapping.values())
    assert db_vectors[mapping["c1"]] == pytest.approx(vectors[0], abs=1e-6)
    assert db_vectors[mapping["c5"]] == pytest.approx(vectors[4], abs=1e-6)
    # liczniki: dokumenty i dataset (chunki committed)
    doc_rows = await _document_rows(container, plan.dataset_id)
    by_name = {row.name: row for row in doc_rows}
    per_document = Counter(chunk["document_ref"] for chunk in chunks)
    assert by_name["umowa  d1.pdf"].chunk_count == per_document["d1"]
    assert by_name["umowa  d2.pdf"].chunk_count == per_document["d2"]
    record = await _dataset(container, plan.dataset_id)
    assert record is not None
    assert record.chunk_count == len(mapping)
    assert record.token_num == sum(chunk["token_count"] for chunk in chunks)
    # postęp: chunki i wektory w tej samej partii
    assert ("chunks", 5, 5) in progress.stages
    assert ("vectors", 5, 5) in progress.stages


async def test_write_chunks_without_vectors_skips_vector_table(
    container: Container, tmp_path: Path
) -> None:
    """``with_vectors=False`` (reembed): tylko chunki, bez wierszy w tabeli wektorów."""
    actor = await _actor(container)
    documents = [_document("d1", file_sha256=None, size=0)]
    chunks = [_chunk("c1", "d1", 0), _chunk("c2", "d1", 1)]
    pkg = _package(
        tmp_path / "p.wdkb.zip",
        documents=documents,
        chunks=chunks,
        vectors=_vectors(0),
        blobs={},
        included=False,  # paczka bez wektorów — reembed po stronie T5
    )
    plan = _plan(uuid.uuid4().hex, actor)
    progress = FakeProgress()

    ids = await create_dataset_with_documents(
        container, pkg=pkg, plan=plan, progress=FakeProgress()
    )
    mapping = await write_chunks(
        container, pkg=pkg, plan=plan, doc_ids=ids, progress=progress, with_vectors=False
    )

    assert set(mapping) == {"c1", "c2"}
    assert len(await _chunk_rows(container, plan.dataset_id)) == len(mapping)
    assert await _vectors_in_db(container) == {}
    stages = [stage for stage, _done, _total in progress.stages]
    assert "chunks" in stages and "vectors" not in stages
    record = await _dataset(container, plan.dataset_id)
    assert record is not None and record.chunk_count == len(mapping)


async def test_write_chunks_batches_2500_into_three_parts(
    container: Container, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """2500 chunków → 3 partie po ≤1000; ``insert_many`` wektorów raz na partię (przykład 2)."""
    actor = await _actor(container)
    count = 2500
    documents = [_document("d1", file_sha256=None, size=0)]
    chunks = [_chunk(f"c{i}", "d1", i, content=f"chunk {i}") for i in range(count)]
    vectors = _vectors(count)
    pkg = _package(
        tmp_path / "p.wdkb.zip", documents=documents, chunks=chunks, vectors=vectors, blobs={}
    )
    plan = _plan(uuid.uuid4().hex, actor)

    calls: list[int] = []
    original = chunk_vectors.insert_many

    async def _spy(session: Any, dim: int, rows: Sequence[Any]) -> None:
        calls.append(len(rows))
        await original(session, dim, rows)

    monkeypatch.setattr(chunk_vectors, "insert_many", _spy)

    ids = await create_dataset_with_documents(
        container, pkg=pkg, plan=plan, progress=FakeProgress()
    )
    progress = FakeProgress()
    mapping = await write_chunks(
        container, pkg=pkg, plan=plan, doc_ids=ids, progress=progress, with_vectors=True
    )

    assert len(mapping) == count
    assert calls == [1000, 1000, 500]  # jedna partia wektorów na partię chunków
    assert ("chunks", 1000, count) in progress.stages
    assert ("chunks", 2000, count) in progress.stages
    assert ("chunks", 2500, count) in progress.stages
    assert ("vectors", 1000, count) in progress.stages
    record = await _dataset(container, plan.dataset_id)
    assert record is not None and record.chunk_count == count


async def test_write_chunks_cancel_after_first_batch_propagates(
    container: Container, tmp_path: Path
) -> None:
    """``TaskCancelled`` z ``check_cancel`` po 1. partii → wyjątek propaguje (przykład 3)."""
    actor = await _actor(container)
    count = 1001  # dwie partie: 1000 + 1
    documents = [_document("d1", file_sha256=None, size=0)]
    chunks = [_chunk(f"c{i}", "d1", i, content=f"chunk {i}") for i in range(count)]
    pkg = _package(
        tmp_path / "p.wdkb.zip",
        documents=documents,
        chunks=chunks,
        vectors=_vectors(count),
        blobs={},
    )
    plan = _plan(uuid.uuid4().hex, actor)
    ids = await create_dataset_with_documents(
        container, pkg=pkg, plan=plan, progress=FakeProgress()
    )
    progress = FakeProgress(cancel_on_check=2)

    with pytest.raises(TaskCancelled):
        await write_chunks(
            container, pkg=pkg, plan=plan, doc_ids=ids, progress=progress, with_vectors=True
        )

    # pierwsza partia zapisana (committed=1), druga nie — sprzątanie robi wołający (handler T7)
    assert len(await _chunk_rows(container, plan.dataset_id)) == 1000  # noqa: PLR2004 — partia briefu


@pytest.mark.parametrize("vector_count", [4, 6])  # mniej niż chunków / więcej niż chunków
async def test_write_chunks_vector_count_mismatch_is_permanent(
    container: Container, tmp_path: Path, vector_count: int
) -> None:
    """Liczba wektorów ≠ liczba chunków → ``PermanentError`` w obie strony (przykład 4 + guard)."""
    actor = await _actor(container)
    documents = [_document("d1", file_sha256=None, size=0)]
    chunks = [_chunk(f"c{i}", "d1", i) for i in range(5)]
    pkg = _package(
        tmp_path / "p.wdkb.zip",
        documents=documents,
        chunks=chunks,
        vectors=_vectors(vector_count),
        blobs={},
        validate=False,  # walidator odrzuciłby tę paczkę — guard funkcji ma ją złapać
    )
    plan = _plan(uuid.uuid4().hex, actor)
    ids = await create_dataset_with_documents(
        container, pkg=pkg, plan=plan, progress=FakeProgress()
    )

    with pytest.raises(PermanentError):
        await write_chunks(
            container,
            pkg=pkg,
            plan=plan,
            doc_ids=ids,
            progress=FakeProgress(),
            with_vectors=True,
        )
