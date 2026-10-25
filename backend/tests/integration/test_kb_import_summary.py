"""Testy ``build_summary`` na prawdziwej MariaDB (brief E7-1b-T1, K19 §3).

Każdy przykład z briefu ma osobny test. Kształt wyniku sprawdza ``ImportSummary`` z
``app.api.wd.kb_schemas`` (import wyłącznie w testach — warstwy). Paczki buduje ``PackageWriter``
i waliduje ``validate_package`` (pełny round-trip, wzór: testy E7-1f w ``tests/**/kb_package``).
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alembic import command
from app.api.wd.kb_schemas import ImportSummary
from app.core.config import Settings
from app.core.container import Container
from app.core.ids import UuidV7Generator
from app.db.engine import make_engine, make_sessionmaker
from app.db.repositories import datasets as datasets_repo
from app.db.uow import transaction
from app.llm.gateway import LLMGateway
from app.llm.types import ModelRef
from app.services.kb_import_summary import build_summary
from app.services.kb_package import format as fmt
from app.services.kb_package.validate import ValidatedPackage, validate_package
from app.services.kb_package.writer import PackageWriter
from tests.fakes.clock import FrozenClock
from tests.integration.datasets.conftest import count_sql, exec_sql, seed_model, seed_user
from tests.integration.db.helpers import alembic_cfg

pytestmark = pytest.mark.db

MAX_BYTES = 100 * 1024 * 1024
MAX_RATIO = 100
# Zegar zamrożony na 2026-10-12 12:00 UTC — fixture conftest datasetów zamraża inną datę.
SUMMARY_TIME_MS = 1791806400000
SUGGESTED_DATE = "2026-10-12"
PACKAGE_NAME = "Baza paczki"
MODEL_NAME = "fake-embed"
DIMENSION = 8
TOKEN_COUNTS = (5, 7, 11)
TOTAL_TOKENS = sum(TOKEN_COUNTS)
LOGGER_NAME = "app.services.kb_import_summary"


@pytest.fixture
def migrated_db(fresh_db: Settings) -> Settings:
    """Świeża baza po migracji do head (sync — env.py Alembic robi asyncio.run)."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    return fresh_db


@pytest.fixture
async def sm(migrated_db: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Sessionmaker na engine per test; po teście dispose."""
    engine = make_engine(migrated_db)
    yield make_sessionmaker(engine)
    await engine.dispose()


@pytest.fixture
async def container(migrated_db: Settings, tmp_path: Path) -> AsyncIterator[Container]:
    """Kontener na zmigrowanej bazie z zegarem zamrożonym na dzień podsumowania."""
    instance = Container(
        migrated_db.model_copy(update={"storage_root": str(tmp_path)}),
        clock=FrozenClock(SUMMARY_TIME_MS),
        id_gen=UuidV7Generator(),
    )
    await instance.start()
    yield instance
    await instance.aclose()


def _document(ref: str) -> dict[str, Any]:
    """Linia documents.jsonl wg K19 §2."""
    return {
        "ref": ref,
        "name": f"{ref}.txt",
        "type": "txt",
        "suffix": "txt",
        "size": 12,
        "file_sha256": None,
        "chunk_method": "naive",
        "parser_config": {},
        "meta_fields": {},
        "run": "3",  # DONE — run surowe (K19 §2)
        "progress_msg": "",
        "token_num": 10,
        "chunk_num": len(TOKEN_COUNTS),
    }


def _chunk(ref: str, document_ref: str, ordinal: int, token_count: int) -> dict[str, Any]:
    """Linia chunks.jsonl wg K19 §2."""
    return {
        "ref": ref,
        "document_ref": document_ref,
        "ordinal": ordinal,
        "chunk_type": "text",
        "content": f"treść {ref}",
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
        "token_count": token_count,
    }


def _jsonl(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(json.dumps(row, ensure_ascii=False).encode("utf-8") + b"\n" for row in rows)


def _npy(rows: list[list[float]], dimension: int = DIMENSION) -> bytes:
    buf = io.BytesIO()
    fmt.write_npy(buf, rows, dimension)
    return buf.getvalue()


def _write_package(  # noqa: PLR0913 — jeden builder paczki z opcjonalnymi polami manifestu
    path: Path,
    *,
    name: str = PACKAGE_NAME,
    description: str | None = None,
    model_name: str = MODEL_NAME,
    dimension: int = DIMENSION,
    included: bool = True,
) -> ValidatedPackage:
    """Buduje i waliduje paczkę: 1 dokument, 3 chunki, wektory o wymiarze ``dimension``."""
    documents = [_document("d1")]
    chunks = [
        _chunk(f"c{index + 1}", "d1", index, token_count)
        for index, token_count in enumerate(TOKEN_COUNTS)
    ]
    blobs: dict[str, bytes] = {
        fmt.DOCUMENTS_PATH: _jsonl(documents),
        fmt.CHUNKS_PATH: _jsonl(chunks),
    }
    if included:
        blobs[fmt.vector_part_path(0)] = _npy([[0.0] * dimension for _ in chunks], dimension)
    writer = PackageWriter(path, max_bytes=MAX_BYTES)
    for entry_path, data in blobs.items():
        writer.add_bytes(entry_path, data)
    manifest = fmt.Manifest.model_validate(
        {
            "format": fmt.FORMAT_NAME,
            "schema_version": fmt.SCHEMA_VERSION,
            "wd_version": "0.9.0",
            "created_at": "2026-10-12T21:00:00Z",
            "source_instance_id": "0123456789abcdef0123456789abcdef",
            "dataset": {
                "name": name,
                "description": description,
                "language": "Polish",
                "chunk_method": "naive",
                "parser_config": {},
                "similarity_threshold": 0.2,
                "vector_similarity_weight": 0.3,
                "pagerank": 0,
            },
            "embedding": {"model_name": model_name, "dimension": dimension, "included": included},
            "counts": {
                "documents": len(documents),
                "chunks": len(chunks),
                "vectors": len(chunks) if included else 0,
            },
            "entries": [],
        }
    )
    writer.finish(manifest)
    validated = validate_package(path, max_bytes=MAX_BYTES, max_ratio=MAX_RATIO)
    assert isinstance(validated, ValidatedPackage), validated
    return validated


async def _seed_dataset(sm: async_sessionmaker[AsyncSession], *, tenant_id: str, name: str) -> None:
    """Wstawia dataset o danej nazwie (ustawienie nazwy „zajętej” u aktora)."""
    async with transaction(sm) as session:
        await datasets_repo.insert(
            session,
            id=UuidV7Generator().new_id(),
            tenant_id=tenant_id,
            created_by=tenant_id,
            name=name,
            description=None,
            avatar=None,
            language="Polish",
            embedding_model=MODEL_NAME,
            embedding_dim=DIMENSION,
            permission="me",
            chunk_method="naive",
            parser_config={},
            now_ms=SUMMARY_TIME_MS,
        )


async def _summary(
    container: Container, package: ValidatedPackage, actor_id: str
) -> dict[str, Any]:
    """``build_summary`` i walidacja kształtu przez ``ImportSummary`` (K19 §3)."""
    result = await build_summary(container, actor_id=actor_id, pkg=package)
    assert ImportSummary.model_validate(result) is not None
    return result


async def test_summary_shape_and_compatible_model(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Paczka z modelem dostępnym aktorowi: compatible=true, default_model=model paczki.

    Pola z manifestu przechodzą dosłownie, a ``target.models`` zawiera tylko aktywne modele
    embeddingów ze znanym wymiarem (chat/nieaktywny/bez wymiaru odpadają).
    """
    user_id, _email = await seed_user(sm)
    await seed_model(sm, MODEL_NAME, "embedding", dimension=DIMENSION)
    # Modele odfiltrowane z target.models: chat, embedding nieaktywny, embedding bez wymiaru.
    await seed_model(sm, "fake-chat", "chat", is_default=False)
    inactive_id = await seed_model(sm, "retired-embed", "embedding", is_default=False, dimension=4)
    await exec_sql(sm, "UPDATE models SET is_active = 0 WHERE id = :id", id=inactive_id)
    await seed_model(sm, "dimensionless-embed", "embedding", is_default=False)
    package = _write_package(tmp_path / "pkg.wdkb.zip", description="Opis paczki")

    result = await _summary(container, package, user_id)

    assert result["name"] == PACKAGE_NAME
    assert result["description"] == "Opis paczki"
    assert result["documents"] == 1
    assert result["chunks"] == len(TOKEN_COUNTS)
    assert result["schema_version"] == fmt.SCHEMA_VERSION
    assert result["wd_version"] == "0.9.0"
    assert result["created_at"] == "2026-10-12T21:00:00Z"
    assert result["embedding"] == {
        "model_name": MODEL_NAME,
        "dimension": DIMENSION,
        "included": True,
    }
    assert result["target"] == {
        "compatible": True,
        "default_model": MODEL_NAME,
        "models": [{"name": MODEL_NAME, "dimension": DIMENSION}],
    }
    assert result["name_taken"] is False
    assert result["suggested_name"] == PACKAGE_NAME
    assert result["estimated_reembed_tokens"] == TOTAL_TOKENS


async def test_incompatible_dimension_falls_back_to_default_model(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Model paczki nieobecny u aktora: compatible=false, default_model=domyślny embedding."""
    user_id, _email = await seed_user(sm)
    await seed_model(sm, "fake-embed-1024", "embedding", dimension=1024)
    package = _write_package(tmp_path / "pkg.wdkb.zip")

    result = await _summary(container, package, user_id)

    assert result["target"]["compatible"] is False
    assert result["target"]["default_model"] == "fake-embed-1024"
    assert result["target"]["models"] == [{"name": "fake-embed-1024", "dimension": 1024}]


async def test_incompatible_without_default_model(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Brak domyślnego modelu embeddingów (tylko niedomyślny): default_model=null."""
    user_id, _email = await seed_user(sm)
    await seed_model(sm, "other-embed", "embedding", dimension=4, is_default=False)
    package = _write_package(tmp_path / "pkg.wdkb.zip")

    result = await _summary(container, package, user_id)

    assert result["target"]["compatible"] is False
    assert result["target"]["default_model"] is None
    assert result["target"]["models"] == [{"name": "other-embed", "dimension": 4}]


async def test_included_false_is_not_compatible(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Paczka bez wektorów: compatible=false, mimo modelu o zgodnej nazwie i wymiarze."""
    user_id, _email = await seed_user(sm)
    await seed_model(sm, MODEL_NAME, "embedding", dimension=DIMENSION)
    package = _write_package(tmp_path / "pkg.wdkb.zip", included=False)

    result = await _summary(container, package, user_id)

    assert result["embedding"]["included"] is False
    assert result["target"]["compatible"] is False
    assert result["target"]["models"] == [{"name": MODEL_NAME, "dimension": DIMENSION}]


async def test_suggested_name_and_counter_when_taken(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Nazwa z paczki zajęta u aktora: najpierw z datą, potem z licznikiem."""
    user_id, _email = await seed_user(sm)
    await _seed_dataset(sm, tenant_id=user_id, name=PACKAGE_NAME)
    package = _write_package(tmp_path / "pkg.wdkb.zip")

    first = await _summary(container, package, user_id)
    assert first["name_taken"] is True
    assert first["suggested_name"] == f"{PACKAGE_NAME} (import {SUGGESTED_DATE})"

    await _seed_dataset(sm, tenant_id=user_id, name=first["suggested_name"])
    second = await _summary(container, package, user_id)
    assert second["suggested_name"] == f"{PACKAGE_NAME} (import {SUGGESTED_DATE}) 2"


async def test_suggested_name_case_insensitive_and_truncated(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Kolacja case-insensitive (uq_datasets_tenant_name_ci); wynik ≤ 128 znaków."""
    user_id, _email = await seed_user(sm)
    # Literał z briefu §2 p. 2 („Długość ≤ 128") i DDL datasets.name VARCHAR(128) — celowo NIE
    # stała z modułu pod testem, żeby zmiana MAX_NAME_LEN w kodzie czerwieniła ten test.
    name_limit = 128
    long_name = "N" * name_limit
    await _seed_dataset(sm, tenant_id=user_id, name=PACKAGE_NAME.lower())
    await _seed_dataset(sm, tenant_id=user_id, name=long_name)
    package = _write_package(tmp_path / "pkg.wdkb.zip")
    long_package = _write_package(tmp_path / "long.wdkb.zip", name=long_name)

    taken = await _summary(container, package, user_id)
    assert taken["name_taken"] is True  # ta sama nazwa inną wielkością liter
    assert taken["suggested_name"] == f"{PACKAGE_NAME} (import {SUGGESTED_DATE})"

    truncated = await _summary(container, long_package, user_id)
    suffix = f" (import {SUGGESTED_DATE})"
    assert truncated["suggested_name"] == "N" * (name_limit - len(suffix)) + suffix
    assert len(truncated["suggested_name"]) == name_limit


async def test_other_user_dataset_does_not_count(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Nazwa zajęta u innego użytkownika nie liczy się aktorowi."""
    user_id, _email = await seed_user(sm)
    other_id, _other_email = await seed_user(sm, nickname="Bob")
    await _seed_dataset(sm, tenant_id=other_id, name=PACKAGE_NAME)
    package = _write_package(tmp_path / "pkg.wdkb.zip")

    result = await _summary(container, package, user_id)

    assert result["name_taken"] is False
    assert result["suggested_name"] == PACKAGE_NAME


# --- DEC-342: sonda wymiaru modelu z dimension IS NULL (świeża instalacja) -----------------


class _CountingGateway:
    """Bramka-dekorator: liczy wywołania ``embed``, resztę metod deleguje do prawdziwej bramki."""

    def __init__(self, inner: LLMGateway) -> None:
        self._inner = inner
        self.embed_calls = 0

    async def embed(self, model: ModelRef, texts: Sequence[str]) -> list[list[float]]:
        self.embed_calls += 1
        return await self._inner.embed(model, texts)

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)


async def _stored_dimension(sm: async_sessionmaker[AsyncSession], name: str, dim: int) -> bool:
    """Czy w ``models`` wiersz o nazwie ma zapisany wymiar ``dim`` (None = bez sondy)."""
    return (
        await count_sql(
            sm,
            "SELECT id FROM models WHERE name = :name AND dimension = :dim",
            name=name,
            dim=dim,
        )
        == 1
    )


async def test_probe_fills_default_dimension_on_fresh_install(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """DEC-342 p. 1: model domyślny z ``dimension NULL`` + paczka zgodna (1024) → compatible.

    Sonda mierzy wymiar (fake-embed-1024 → 1024), zapisuje go w ``models.dimension`` i wiersz
    trafia do ``target.models``/``default_model`` — bez ręcznego użycia modelu (SC-E7-2-06).
    """
    user_id, _email = await seed_user(sm)
    await seed_model(sm, "fake-embed-1024", "embedding")  # dimension NULL (świeża instalacja)
    package = _write_package(
        tmp_path / "pkg.wdkb.zip", model_name="fake-embed-1024", dimension=1024
    )

    result = await _summary(container, package, user_id)

    assert result["target"] == {
        "compatible": True,
        "default_model": "fake-embed-1024",
        "models": [{"name": "fake-embed-1024", "dimension": 1024}],
    }
    assert await _stored_dimension(sm, "fake-embed-1024", 1024) is True


async def test_probe_measured_dimension_differs_from_package(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """DEC-342 p. 2: ten sam model NULL, paczka o innym wymiarze (768) → compatible=false.

    Zmierzony wymiar (1024) trafia na listę modeli, a ``default_model`` zostaje domyślnym.
    """
    user_id, _email = await seed_user(sm)
    await seed_model(sm, "fake-embed-1024", "embedding")  # dimension NULL
    package = _write_package(tmp_path / "pkg.wdkb.zip", model_name="fake-embed-1024", dimension=768)

    result = await _summary(container, package, user_id)

    assert result["target"] == {
        "compatible": False,
        "default_model": "fake-embed-1024",
        "models": [{"name": "fake-embed-1024", "dimension": 1024}],
    }


async def test_probe_fills_package_model_distinct_from_default(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """DEC-342 p. 1 (kandydat a): model paczki (NULL) różny od domyślnego (wymiar znany) → sonda.

    Model domyślny ma już wymiar (nie jest sondowany), więc zgodność dowodzi sondy modelu
    paczki: bez niej ``fake-embed-3072`` nie trafiłby do ``target.models`` i ``compatible=false``.
    """
    user_id, _email = await seed_user(sm)
    await seed_model(sm, "fake-embed-1024", "embedding", dimension=1024)  # domyślny, wymiar znany
    await seed_model(sm, "fake-embed-3072", "embedding", is_default=False)  # model paczki, NULL
    package = _write_package(
        tmp_path / "pkg.wdkb.zip", model_name="fake-embed-3072", dimension=3072
    )

    result = await _summary(container, package, user_id)

    assert result["target"]["compatible"] is True
    assert result["target"]["default_model"] == "fake-embed-3072"
    assert {"name": "fake-embed-3072", "dimension": 3072} in result["target"]["models"]
    assert await _stored_dimension(sm, "fake-embed-3072", 3072) is True


async def test_probe_failure_leaves_model_without_dimension(
    container: Container,
    sm: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """DEC-342 p. 3: błąd sondy nie wywraca podsumowania — model bez wymiaru, default_model=null.

    Bramka nieosiągalna (URL z kluczem) → ``build_summary`` kończy się normalnie: brak modelu na
    liście, ``default_model=null``; log zawiera tylko nazwę klasy wyjątku, klucz z URL nie wycieka.
    """
    user_id, _email = await seed_user(sm)
    await seed_model(sm, "fake-embed-1024", "embedding")  # dimension NULL
    await exec_sql(
        sm,
        "UPDATE models SET base_url = :url WHERE name = :name",
        url="http://sekret-probe-key@127.0.0.1:1/v1",
        name="fake-embed-1024",
    )
    package = _write_package(
        tmp_path / "pkg.wdkb.zip", model_name="fake-embed-1024", dimension=1024
    )

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        result = await _summary(container, package, user_id)  # nie rzuca (brak 500 na trasie)

    assert result["target"] == {"compatible": False, "default_model": None, "models": []}
    failures = [
        rec for rec in caplog.records if getattr(rec, "event", None) == "embedding_probe_failed"
    ]
    assert len(failures) == 1
    assert getattr(failures[0], "model_name", None) == "fake-embed-1024"
    assert getattr(failures[0], "exception", None)  # klasa wyjątku, bez treści
    assert "sekret-probe-key" not in caplog.text  # URL z kluczem nie wycieka do logu


async def test_no_probe_when_dimension_known(
    container: Container, sm: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """DEC-342 p. 1: model ze znanym wymiarem nie jest sondowany — licznik ``embed`` równy 0."""
    user_id, _email = await seed_user(sm)
    await seed_model(sm, "fake-embed-1024", "embedding", dimension=1024)  # wymiar znany
    spy = _CountingGateway(container.llm)
    container.llm = spy
    package = _write_package(
        tmp_path / "pkg.wdkb.zip", model_name="fake-embed-1024", dimension=1024
    )

    result = await _summary(container, package, user_id)

    assert result["target"]["compatible"] is True
    assert spy.embed_calls == 0
