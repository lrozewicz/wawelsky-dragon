"""Testy T5 importu bazy wiedzy: ponowny embedding chunków (K19 §5, CONTRACT E7-1b §2).

Paczki buduje ``PackageWriter`` i przechodzą ``validate_package`` (round-trip jak w testach
T3), więc testy ćwiczą realny czytnik paczki i realne chunki w bazie. Wektory liczy
fake-llm (deterministyczny per ``(model, tekst)``), a testy porównują zapis z tym samym
przepisem, którego używa ingestia: ``recipe_text`` → ``embed_texts`` → ``combine`` z wektorem
tytułu i wagą ``filename_embd_weight`` (``ingest_pipeline._embed_all``). Rozstrzygnięcie
przepisu i kolejności: DEC w raporcie T5 (TL zapisuje DEC).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import text

from alembic import command
from app.core.config import Settings
from app.core.container import Container
from app.core.ids import UuidV7Generator
from app.db.repositories import chunk_vectors
from app.db.repositories import models as models_repo
from app.db.repositories import users as users_repo
from app.db.uow import transaction
from app.llm.gateway import LLMGateway
from app.llm.types import ModelRef
from app.services import kb_import_embed
from app.services.embed import combine, filename_weight, recipe_text
from app.services.kb_import_chunks import write_chunks
from app.services.kb_import_embed import embed_chunks
from app.services.kb_import_write import ImportPlan, create_dataset_with_documents
from app.services.kb_package import format as fmt
from app.services.kb_package.validate import ValidatedPackage, validate_package
from app.services.kb_package.writer import PackageWriter
from app.worker.errors import PermanentError, TaskCancelled
from tests.fakes.clock import FrozenClock
from tests.integration.db.helpers import alembic_cfg

pytestmark = pytest.mark.db

MAX_BYTES = 100 * 1024 * 1024
MAX_RATIO = 100
DIM = 1024  # fake-embed-1024 — jedyny model embeddingu w atrapie (typowany z paczki)
EMBED_MODEL = "fake-embed-1024"
TIME_MS = 1790157600000
PARSER_CONFIG: dict[str, Any] = {"chunk_token_num": 128, "delimiter": "\n"}
# Drugi dokument miesza wektor tytułu inną wagą — waga MUSI iść z parser_config dokumentu.
WEIGHTED_PARSER_CONFIG: dict[str, Any] = {**PARSER_CONFIG, "filename_embd_weight": 0.5}


@pytest.fixture
def migrated_db(fresh_db: Settings) -> Settings:
    """Świeża baza po migracji do head; sync, bo env.py Alembic robi asyncio.run (C12)."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    return fresh_db


async def _make_container(migrated_db: Settings, tmp_path: Path) -> Container:
    """Kontener na zmigrowanej bazie + rejestr modeli (fake-embed-1024 embeddingiem domyślnym)."""
    instance = Container(
        migrated_db.model_copy(update={"storage_root": str(tmp_path)}),
        clock=FrozenClock(),
        id_gen=UuidV7Generator(),
    )
    await instance.start()
    assert instance.sessionmaker is not None
    async with transaction(instance.sessionmaker) as session:
        await models_repo.insert(
            session,
            id="e" * 32,
            name=EMBED_MODEL,
            model_type="embedding",
            is_default=True,
            now_ms=TIME_MS,
        )
    return instance


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener z atrapą LLM (WD_LLM_BASE_URL) i zarejestrowanym modelem embeddingu."""
    instance = await _make_container(migrated_db, tmp_path)
    yield instance
    await instance.aclose()


class FakeProgress:
    """Fake ``ImportProgress``: zapisuje etapy; ``check_cancel`` rzuca PO wskazanej partii.

    ``cancel_after_stage`` (etap, ``done``) uzbraja anulowanie dopiero, gdy postęp tej partii
    został zaraportowany — czyli po zapisaniu pierwszej partii (przykład 3), niezależnie od
    tego, ile wewnętrznych żądań embeddingu zrobiła atrapa LLM.
    """

    def __init__(self, *, cancel_after_stage: tuple[str, int] | None = None) -> None:
        self.stages: list[tuple[str, int, int]] = []
        self.checks = 0
        self._cancel_after = cancel_after_stage
        self._armed = False

    async def stage(self, stage: str, done: int, total: int) -> None:
        """Zapisuje wywołanie etapu; uzbraja anulowanie po wskazanej partii."""
        self.stages.append((stage, done, total))
        if self._cancel_after is not None and (stage, done) == self._cancel_after:
            self._armed = True

    async def check_cancel(self) -> None:
        """Liczy wywołania; po uzbrojeniu rzuca ``TaskCancelled`` (jak handler T7)."""
        self.checks += 1
        if self._armed:
            raise TaskCancelled("task-test")


def _manifest(*, documents: int, chunks: int) -> fmt.Manifest:
    """Manifest paczki bez wektorów (``included=false``) — scenariusz ponownego embeddingu."""
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
            "embedding": {"model_name": EMBED_MODEL, "dimension": DIM, "included": False},
            "counts": {"documents": documents, "chunks": chunks, "vectors": 0},
            "entries": [],
        }
    )


def _document(ref: str, parser_config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Linia ``documents.jsonl`` wg K19 §2 (bez pliku — import z reembedem go nie potrzebuje)."""
    return {
        "ref": ref,
        "name": f"umowa  {ref}.pdf",
        "type": "pdf",
        "suffix": "pdf",
        "size": 0,
        "file_sha256": None,
        "chunk_method": "naive",
        "parser_config": parser_config if parser_config is not None else PARSER_CONFIG,
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


def _jsonl(rows: Sequence[dict[str, Any]]) -> bytes:
    """Wpis JSONL z linii modelu."""
    return b"".join(json.dumps(row, ensure_ascii=False).encode("utf-8") + b"\n" for row in rows)


def _package(
    path: Path,
    *,
    documents: Sequence[dict[str, Any]],
    chunks: Sequence[dict[str, Any]],
) -> ValidatedPackage:
    """Buduje paczkę bez wektorów i waliduje ją (round-trip jak w testach T3)."""
    writer = PackageWriter(path, max_bytes=MAX_BYTES)
    writer.add_bytes(fmt.DOCUMENTS_PATH, _jsonl(documents))
    writer.add_bytes(fmt.CHUNKS_PATH, _jsonl(chunks))
    writer.finish(_manifest(documents=len(documents), chunks=len(chunks)))
    validated = validate_package(path, max_bytes=MAX_BYTES, max_ratio=MAX_RATIO)
    assert isinstance(validated, ValidatedPackage), validated  # paczka testowa musi być poprawna
    return validated


def _plan(dataset_id: str, actor_id: str, *, dim: int = DIM) -> ImportPlan:
    """Plan importu: id ustala wołający (handler T7), model/wymiar docelowy z reembedu."""
    return ImportPlan(
        dataset_id=dataset_id,
        actor_id=actor_id,
        name="Import 1",
        embedding_model=EMBED_MODEL,
        embedding_dim=dim,
        reembed=True,
        task_public_id="a" * 32,
    )


async def _actor(container: Container) -> str:
    """Wstawia użytkownika-aktora (FK ``datasets.tenant_id`` → ``users``)."""
    user_id = uuid.uuid4().hex
    assert container.sessionmaker is not None
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


async def _vectors_in_db(container: Container, dim: int = DIM) -> dict[str, list[float]]:
    """Wektory z ``chunk_vec_d<dim>`` jako JSON listy liczb (``VEC_ToText``)."""
    assert container.sessionmaker is not None
    async with transaction(container.sessionmaker) as session:
        table = chunk_vectors.table_name(dim)
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


async def _imported_chunks(
    container: Container, pkg: ValidatedPackage, plan: ImportPlan
) -> dict[str, str]:
    """Tworzy dataset importu i zapisuje chunki bez wektorów; zwraca mapę ``ref → chunk_id``."""
    doc_ids = await create_dataset_with_documents(
        container, pkg=pkg, plan=plan, progress=FakeProgress()
    )
    return await write_chunks(
        container,
        pkg=pkg,
        plan=plan,
        doc_ids=doc_ids,
        progress=FakeProgress(),
        with_vectors=False,
    )


async def _set_model_concurrency(container: Container, value: int) -> None:
    """Wpisuje ``models.extra.max_concurrency`` modelu embeddingu (panel/API robi to samo)."""
    assert container.sessionmaker is not None
    async with transaction(container.sessionmaker) as session:
        row = await models_repo.get_by_name(session, EMBED_MODEL, "embedding")
        assert row is not None, f"model {EMBED_MODEL} musi być w rejestrze"
        await models_repo.update_fields(
            session,
            model_id=row.id,
            is_active=None,
            max_tokens=None,
            extra={"max_concurrency": value},
            now_ms=TIME_MS,
        )


async def _fake_vectors(
    container: Container, *, name: str, text: str
) -> tuple[list[float], list[float]]:
    """Wektory atrapy LLM: tytuł dokumentu (``Path(name).stem``) i tekst (deterministyczne)."""
    assert container.models is not None
    model: ModelRef = await container.models.resolve(EMBED_MODEL, "embedding")
    llm = cast(LLMGateway, container.llm)
    title_vec = (await llm.embed(model, [Path(name).stem]))[0]
    text_vec = (await llm.embed(model, [text]))[0]
    return title_vec, text_vec


async def _expected_vector(
    container: Container,
    *,
    name: str,
    content: str,
    questions: list[str],
    parser_config: dict[str, Any],
) -> list[float]:
    """Wektor wg przepisu ingestii: ``combine(tytuł, recipe_text, waga)`` — przez atrapę LLM."""
    title_vec, content_vec = await _fake_vectors(
        container, name=name, text=recipe_text(content, questions)
    )
    return combine(title_vec, content_vec, filename_weight(parser_config))


async def test_embed_chunks_stores_vectors_like_ingest(
    container: Container, tmp_path: Path
) -> None:
    """5 chunków bez wektorów → 5 wierszy; wektory jak po ingestii (przykład 1)."""
    actor = await _actor(container)
    documents = [_document("d1"), _document("d2", WEIGHTED_PARSER_CONFIG)]
    chunks = [
        _chunk("c1", "d1", 0, questions=["Co  to\r\njest?", "Ile?"]),
        _chunk("c2", "d1", 1),
        _chunk("c3", "d1", 2, available=False),
        _chunk("c4", "d2", 0, questions=["Kiedy?"]),
        _chunk("c5", "d2", 1),
    ]
    pkg = _package(tmp_path / "p.wdkb.zip", documents=documents, chunks=chunks)
    plan = _plan(uuid.uuid4().hex, actor)
    mapping = await _imported_chunks(container, pkg, plan)
    assert await _vectors_in_db(container) == {}  # reembed: tabela wektorów pusta przed T5

    progress = FakeProgress()
    await embed_chunks(container, plan=plan, chunk_ids=list(mapping.values()), progress=progress)

    db_vectors = await _vectors_in_db(container)
    assert set(db_vectors) == set(mapping.values())
    by_ref = {ref: chunks[index] for index, ref in enumerate(["c1", "c2", "c3", "c4", "c5"])}
    names = {"d1": "umowa  d1.pdf", "d2": "umowa  d2.pdf"}
    configs = {"d1": PARSER_CONFIG, "d2": WEIGHTED_PARSER_CONFIG}
    for ref, chunk_id in mapping.items():
        chunk = by_ref[ref]
        doc_ref = str(chunk["document_ref"])
        doc_name = names[doc_ref]
        expected = await _expected_vector(
            container,
            name=doc_name,
            content=str(chunk["content"]),
            questions=list(chunk["questions"]),
            parser_config=configs[doc_ref],
        )
        assert db_vectors[chunk_id] == pytest.approx(expected, abs=1e-6)
    # chunk z pytaniami embeduje PYTANIA (recipe_text), nie treść
    c1 = by_ref["c1"]
    assert recipe_text(str(c1["content"]), list(c1["questions"])) == "\n".join(c1["questions"])
    content_only = await _expected_vector(
        container,
        name=names["d1"],
        content=str(c1["content"]),
        questions=[],
        parser_config=PARSER_CONFIG,
    )
    assert db_vectors[mapping["c1"]] != pytest.approx(content_only, abs=1e-6)
    # zapis to wektor ZMIESZANY — ani sam tekst, ani sam tytuł (bez ``combine`` test pada)
    title_vec, content_vec = await _fake_vectors(
        container, name=names["d1"], text=str(by_ref["c2"]["content"])
    )
    assert db_vectors[mapping["c2"]] != pytest.approx(content_vec, abs=1e-6)
    assert db_vectors[mapping["c2"]] != pytest.approx(title_vec, abs=1e-6)
    # waga tytułu idzie z parser_config DOKUMENTU (d2 ma 0.5), nie z datasetu
    assert filename_weight(configs["d2"]) == 0.5  # noqa: PLR2004 — waga z paczki
    assert db_vectors[mapping["c4"]] == pytest.approx(
        await _expected_vector(
            container,
            name=names["d2"],
            content=str(by_ref["c4"]["content"]),
            questions=list(by_ref["c4"]["questions"]),
            parser_config=WEIGHTED_PARSER_CONFIG,
        ),
        abs=1e-6,
    )
    # postęp: jedna partia, done == total
    assert ("embedding", 5, 5) in progress.stages


async def test_embed_chunks_cancel_after_first_batch_keeps_partial(
    container: Container, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``TaskCancelled`` po 1. partii → wyjątek propaguje, wektory częściowe zostają (prz. 3)."""
    actor = await _actor(container)
    documents = [_document("d1")]
    chunks = [_chunk(f"c{i}", "d1", i) for i in range(3)]
    pkg = _package(tmp_path / "p.wdkb.zip", documents=documents, chunks=chunks)
    plan = _plan(uuid.uuid4().hex, actor)
    mapping = await _imported_chunks(container, pkg, plan)

    monkeypatch.setattr("app.services.kb_import_embed.CHUNK_BATCH", 2)  # partie: 2 + 1
    progress = FakeProgress(cancel_after_stage=("embedding", 2))

    with pytest.raises(TaskCancelled):
        await embed_chunks(
            container, plan=plan, chunk_ids=list(mapping.values()), progress=progress
        )

    # pierwsza partia zapisana, druga nie — sprzątanie robi wołający (handler T7)
    db_vectors = await _vectors_in_db(container)
    assert set(db_vectors) == {mapping["c0"], mapping["c1"]}


async def test_embed_chunks_batches_2500_into_three_parts(
    container: Container, tmp_path: Path
) -> None:
    """2500 chunków → 3 partie (1000/1000/500), postęp dochodzi do ``(2500, 2500)`` (prz. 2)."""
    actor = await _actor(container)
    count = 2500
    documents = [_document("d1")]
    chunks = [_chunk(f"c{i}", "d1", i, content=f"treść chunka {i}") for i in range(count)]
    pkg = _package(tmp_path / "p.wdkb.zip", documents=documents, chunks=chunks)
    plan = _plan(uuid.uuid4().hex, actor)
    mapping = await _imported_chunks(container, pkg, plan)

    progress = FakeProgress()
    await embed_chunks(container, plan=plan, chunk_ids=list(mapping.values()), progress=progress)

    stages = [(stage, done, total) for stage, done, total in progress.stages]
    embedding = [(done, total) for stage, done, total in stages if stage == "embedding"]
    assert embedding[-1] == (count, count)
    assert all(total == count for _done, total in embedding)
    assert [done for done, _total in embedding] == sorted({done for done, _total in embedding})
    # granice partii pisania (1000, 2000) są zaraportowane — jak w briefie
    assert (1000, count) in embedding
    assert (2000, count) in embedding
    assert len(await _vectors_in_db(container)) == count


async def test_embed_chunks_wrong_dimension_is_permanent(
    container: Container, tmp_path: Path
) -> None:
    """Wektor o wymiarze ≠ ``plan.embedding_dim`` → ``PermanentError`` (przykład 4)."""
    actor = await _actor(container)
    documents = [_document("d1")]
    chunks = [_chunk("c1", "d1", 0)]
    pkg = _package(tmp_path / "p.wdkb.zip", documents=documents, chunks=chunks)
    plan = _plan(uuid.uuid4().hex, actor, dim=7)  # atrapa zwraca 1024 wymiary (fake-embed-1024)
    mapping = await _imported_chunks(container, pkg, plan)

    with pytest.raises(PermanentError):
        await embed_chunks(
            container, plan=plan, chunk_ids=list(mapping.values()), progress=FakeProgress()
        )

    assert await _vectors_in_db(container, 7) == {}


async def test_embed_chunks_passes_ingest_batch_and_model_concurrency(
    container: Container, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``batch_size`` i współbieżność wg modelu (E5-H8b) trafiają do ``embed_texts``.

    Regresja: stała ``concurrency=1`` zamiast ``resolve_concurrency(model, …)`` ma zapalić ten
    test (kolejne żądania ``embed_texts`` są obserwowane bezpośrednio — atrapa LLM nie liczy
    zbieżnych żądań, kontrakt E7-1b §2 p. 2 wymaga współbieżności „jak ingestia").
    """
    actor = await _actor(container)
    documents = [_document("d1")]
    chunks = [_chunk("c1", "d1", 0)]
    pkg = _package(tmp_path / "p.wdkb.zip", documents=documents, chunks=chunks)
    plan = _plan(uuid.uuid4().hex, actor)
    mapping = await _imported_chunks(container, pkg, plan)
    await _set_model_concurrency(container, 8)  # extra.max_concurrency modelu (nie ustawienie)

    calls: list[dict[str, Any]] = []
    original = kb_import_embed.embed_texts

    async def _spy(
        llm: LLMGateway, model: ModelRef, texts: Sequence[str], **kwargs: Any
    ) -> list[list[float]]:
        calls.append({"texts": list(texts), **kwargs})
        return await original(llm, model, texts, **kwargs)

    monkeypatch.setattr(kb_import_embed, "embed_texts", _spy)
    progress = FakeProgress()
    await embed_chunks(container, plan=plan, chunk_ids=list(mapping.values()), progress=progress)

    content = [call for call in calls if "concurrency" in call]
    assert len(content) == 1  # jedna partia chunków (1 chunk)
    assert content[0]["concurrency"] == 8  # noqa: PLR2004 — extra.max_concurrency modelu
    assert content[0]["batch_size"] == container.settings.embed_batch_size
    assert content[0]["expected_dim"] == plan.embedding_dim
    assert content[0]["check_cancel"] == progress.check_cancel
    assert content[0]["on_batch"] is not None
    # wektor tytułu liczony osobno, po jednym tekście na raz — jak krok 10 ingestii
    titles = [call for call in calls if "concurrency" not in call]
    assert titles == [{"texts": ["umowa  d1"], "batch_size": 1, "expected_dim": plan.embedding_dim}]
    assert len(await _vectors_in_db(container)) == 1
