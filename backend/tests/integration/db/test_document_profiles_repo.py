"""Testy repozytorium `document_profiles` na MariaDB (K21 §1, CONTRACT V13-1).

Wszystkie testy asynchroniczne — świeża baza migrowana do head przez fixture `migrated_db`
(wzorzec testów repozytorium `dataset_imports`).
"""

import json
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alembic import command
from app.core.config import Settings
from app.db.engine import make_engine, make_sessionmaker
from app.db.repositories import document_profiles as repo
from app.db.uow import transaction
from tests.integration.db.helpers import alembic_cfg
from tests.integration.ingest.conftest import TIME, TIME_MS

pytestmark = pytest.mark.db

LATER = TIME_MS + 5_000

_OUTLINE = [
    {"level": 0, "title": "Rocznik Statystyczny", "page": None},
    {"level": 1, "title": "Dział I", "page": 12},
]
_OUTLINE_SECOND = [{"level": 0, "title": "Nowy układ", "page": 3}]

_READ_SQL = text(
    "SELECT outline, outline_source, outline_count, summary, topics, model, create_time,"
    " update_time FROM document_profiles WHERE document_id = :id"
)


@pytest.fixture
def migrated_db(fresh_db: Settings) -> Settings:
    """Świeża baza po migracji do head (sync — env.py Alembic robi asyncio.run, C12)."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    return fresh_db


@pytest.fixture
async def sm(migrated_db: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Sessionmaker na engine per test; po teście dispose."""
    engine = make_engine(migrated_db)
    yield make_sessionmaker(engine)
    await engine.dispose()


async def _seed_dataset(
    sm: async_sessionmaker[AsyncSession], *, dataset_id: str, user_id: str, name: str
) -> None:
    """Wstawia dataset o podanej nazwie (kolejność katalogu po nazwie datasetu, K21 §3)."""
    async with transaction(sm) as session:
        await session.execute(
            text(
                "INSERT INTO datasets (id, tenant_id, created_by, name, embedding_model,"
                " embedding_dim, create_time, create_date, update_time, update_date)"
                " VALUES (:id, :tenant, :tenant, :name, 'openai/text-embedding-3-large', 3072,"
                " :time_ms, :time, :time_ms, :time)"
            ),
            {"id": dataset_id, "tenant": user_id, "name": name, "time_ms": TIME_MS, "time": TIME},
        )


async def _seed_document(  # noqa: PLR0913 — pomocnik testowy z domyślnymi wartościami
    sm: async_sessionmaker[AsyncSession],
    *,
    document_id: str,
    dataset_id: str,
    user_id: str,
    name: str = "doc.pdf",
    run: str = "3",
    enabled: int = 1,
) -> None:
    """Wstawia dokument z jawnymi `run`/`enabled` (filtry katalogu i porcji, K21 §3/§2)."""
    async with transaction(sm) as session:
        await session.execute(
            text(
                "INSERT INTO documents (id, dataset_id, created_by, name, suffix, type, location,"
                " content_hash, chunk_method, parser_config, run, enabled, create_time,"
                " create_date, update_time, update_date)"
                " VALUES (:id, :dataset, :creator, :name, 'pdf', 'doc', 'files/x.pdf', '0',"
                " 'naive', '{}', :run, :enabled, :time_ms, :time, :time_ms, :time)"
            ),
            {
                "id": document_id,
                "dataset": dataset_id,
                "creator": user_id,
                "name": name,
                "run": run,
                "enabled": enabled,
                "time_ms": TIME_MS,
                "time": TIME,
            },
        )


async def _seed(sm: async_sessionmaker[AsyncSession]) -> tuple[str, str, str]:
    """Seed users → datasets (`Baza`) → documents (`run='3'`, `enabled=1`); zwraca trzy id."""
    user_id = uuid.uuid4().hex
    dataset_id = uuid.uuid4().hex
    document_id = uuid.uuid4().hex
    async with transaction(sm) as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, nickname, create_time, create_date,"
                " update_time, update_date)"
                " VALUES (:id, :email, 'seed', :time_ms, :time, :time_ms, :time)"
            ),
            {"id": user_id, "email": f"{user_id}@example.com", "time_ms": TIME_MS, "time": TIME},
        )
        await session.execute(
            text(
                "INSERT INTO datasets (id, tenant_id, created_by, name, embedding_model,"
                " embedding_dim, create_time, create_date, update_time, update_date)"
                " VALUES (:id, :tenant, :tenant, 'Baza', 'openai/text-embedding-3-large', 3072,"
                " :time_ms, :time, :time_ms, :time)"
            ),
            {"id": dataset_id, "tenant": user_id, "time_ms": TIME_MS, "time": TIME},
        )
        await session.execute(
            text(
                "INSERT INTO documents (id, dataset_id, created_by, name, suffix, type, location,"
                " content_hash, chunk_method, parser_config, run, enabled, create_time,"
                " create_date, update_time, update_date)"
                " VALUES (:id, :dataset, :creator, 'doc.pdf', 'pdf', 'doc', 'files/x.pdf', '0',"
                " 'naive', '{}', '3', 1, :time_ms, :time, :time_ms, :time)"
            ),
            {
                "id": document_id,
                "dataset": dataset_id,
                "creator": user_id,
                "time_ms": TIME_MS,
                "time": TIME,
            },
        )
    return user_id, dataset_id, document_id


async def test_upsert_inserts_profile(sm: async_sessionmaker[AsyncSession]) -> None:
    """`upsert` zapisuje profil: outline (JSON), licznik, źródło; rezerwy NULL (K21 §1)."""
    _, dataset_id, document_id = await _seed(sm)
    async with transaction(sm) as session:
        await repo.upsert(
            session,
            document_id=document_id,
            dataset_id=dataset_id,
            outline=_OUTLINE,
            outline_source="pdf_bookmarks",
            now_ms=TIME_MS,
        )
        row = (await session.execute(_READ_SQL, {"id": document_id})).mappings().one()
    assert json.loads(row["outline"]) == _OUTLINE
    assert row["outline_source"] == "pdf_bookmarks"
    assert row["outline_count"] == len(_OUTLINE)
    assert (row["summary"], row["topics"], row["model"]) == (None, None, None)
    assert (row["create_time"], row["update_time"]) == (TIME_MS, TIME_MS)


async def test_upsert_twice_single_row_with_second_outline(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """Podwójny `upsert` → 1 wiersz, outline z drugiego wywołania; `create_time` zachowany.

    (Przykład z briefu T2; reparsowanie nadpisuje profil — K21 §1.)
    """
    _, dataset_id, document_id = await _seed(sm)
    async with transaction(sm) as session:
        await repo.upsert(
            session,
            document_id=document_id,
            dataset_id=dataset_id,
            outline=_OUTLINE,
            outline_source="pdf_bookmarks",
            now_ms=TIME_MS,
        )
        await repo.upsert(
            session,
            document_id=document_id,
            dataset_id=dataset_id,
            outline=_OUTLINE_SECOND,
            outline_source="headings",
            now_ms=LATER,
        )
        count = (await session.execute(text("SELECT COUNT(*) FROM document_profiles"))).scalar_one()
        row = (await session.execute(_READ_SQL, {"id": document_id})).mappings().one()
    assert count == 1
    assert json.loads(row["outline"]) == _OUTLINE_SECOND
    assert row["outline_source"] == "headings"
    assert row["outline_count"] == len(_OUTLINE_SECOND)
    assert (row["create_time"], row["update_time"]) == (TIME_MS, LATER)


async def test_list_catalog_orders_by_dataset_then_document(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """Kolejność (nazwa datasetu, nazwa dokumentu); dokument bez profilu → `outline=[]` (K21 §3)."""
    user_id, first_ds, first_doc = await _seed(sm)
    # "Zeta" wstawiona przed "Alfa" — kolejność ma wymusić ORDER BY, nie kolejność wstawiania.
    zeta_ds = uuid.uuid4().hex
    await _seed_dataset(sm, dataset_id=zeta_ds, user_id=user_id, name="Zeta")
    alfa_ds = uuid.uuid4().hex
    await _seed_dataset(sm, dataset_id=alfa_ds, user_id=user_id, name="Alfa")
    doc_a, doc_b, doc_z = (uuid.uuid4().hex for _ in range(3))
    await _seed_document(sm, document_id=doc_a, dataset_id=alfa_ds, user_id=user_id, name="a.pdf")
    await _seed_document(sm, document_id=doc_b, dataset_id=alfa_ds, user_id=user_id, name="b.pdf")
    await _seed_document(sm, document_id=doc_z, dataset_id=zeta_ds, user_id=user_id, name="a.pdf")
    async with transaction(sm) as session:
        await repo.upsert(
            session,
            document_id=first_doc,
            dataset_id=first_ds,
            outline=_OUTLINE,
            outline_source="headings",
            now_ms=TIME_MS,
        )
        docs = await repo.list_catalog(session, [first_ds, zeta_ds, alfa_ds])
    # first_doc ma nazwę "doc.pdf" (po "a.pdf"/"b.pdf" w obrębie datasetu "Baza").
    assert [d.document_name for d in docs] == ["a.pdf", "b.pdf", "doc.pdf", "a.pdf"]
    assert [d.dataset_name for d in docs] == ["Alfa", "Alfa", "Baza", "Zeta"]
    assert [d.document_id for d in docs] == [doc_a, doc_b, first_doc, doc_z]
    with_profile = docs[2]
    assert with_profile.dataset_id == first_ds
    assert with_profile.outline == _OUTLINE
    assert with_profile.outline_source == "headings"
    # Dokument `run='3'` bez wiersza profilu → pusty spis i źródło 'none' (K21 §1/§3).
    without_profile = docs[0]
    assert without_profile.outline == []
    assert without_profile.outline_source == "none"


async def test_list_catalog_scope_and_filters(sm: async_sessionmaker[AsyncSession]) -> None:
    """Zakres wyłącznie z `dataset_ids` (puste → `[]`); `enabled=0` i `run!='3'` pominięte."""
    user_id, dataset_id, seeded_doc = await _seed(sm)
    other_ds = uuid.uuid4().hex
    await _seed_dataset(sm, dataset_id=other_ds, user_id=user_id, name="Inna")
    doc_disabled, doc_unparsed, doc_other = (uuid.uuid4().hex for _ in range(3))
    await _seed_document(
        sm,
        document_id=doc_disabled,
        dataset_id=dataset_id,
        user_id=user_id,
        name="off.pdf",
        enabled=0,
    )
    await _seed_document(
        sm,
        document_id=doc_unparsed,
        dataset_id=dataset_id,
        user_id=user_id,
        name="run0.pdf",
        run="0",
    )
    await _seed_document(
        sm, document_id=doc_other, dataset_id=other_ds, user_id=user_id, name="inny.pdf"
    )
    async with transaction(sm) as session:
        assert await repo.list_catalog(session, []) == []
        # Cudzy dataset poza zakresem (przykład z briefu); odfiltrowane `enabled=0`/`run='0'` też.
        docs = await repo.list_catalog(session, [dataset_id])
        both = await repo.list_catalog(session, [dataset_id, other_ds])
    assert [d.document_id for d in docs] == [seeded_doc]
    assert doc_disabled not in [d.document_id for d in both]
    assert doc_unparsed not in [d.document_id for d in both]
    # Kolejność po nazwie datasetu: "Baza" przed "Inna".
    assert [d.document_id for d in both] == [seeded_doc, doc_other]


async def test_ids_without_profile(sm: async_sessionmaker[AsyncSession]) -> None:
    """Dokumenty `run='3'` bez profilu, ≤ limit; z profilem i `run!='3'` poza porcją (K21 §2)."""
    user_id, dataset_id, with_profile = await _seed(sm)
    doc_second, doc_third, doc_unparsed = (uuid.uuid4().hex for _ in range(3))
    await _seed_document(
        sm, document_id=doc_second, dataset_id=dataset_id, user_id=user_id, name="drugi.pdf"
    )
    await _seed_document(
        sm,
        document_id=doc_unparsed,
        dataset_id=dataset_id,
        user_id=user_id,
        name="run0.pdf",
        run="0",
    )
    async with transaction(sm) as session:
        await repo.upsert(
            session,
            document_id=with_profile,
            dataset_id=dataset_id,
            outline=_OUTLINE,
            outline_source="headings",
            now_ms=TIME_MS,
        )
        # Przykład z briefu: 2 dokumenty `run='3'`, jeden z profilem → porcja zawiera tylko drugi.
        ids = await repo.ids_without_profile(session, 50)
    assert ids == [doc_second]
    # Limit porcji (≤ 50, sweep): dwie szanse, limit 1 → dokładnie jeden z nich (K21 §2 p. 4).
    await _seed_document(
        sm, document_id=doc_third, dataset_id=dataset_id, user_id=user_id, name="trzeci.pdf"
    )
    async with transaction(sm) as session:
        limited = await repo.ids_without_profile(session, 1)
    assert len(limited) == 1 and limited[0] in {doc_second, doc_third}


async def test_delete_document_cascades_profile(sm: async_sessionmaker[AsyncSession]) -> None:
    """FK ON DELETE CASCADE: usunięcie dokumentu usuwa jego profil (K21 §1, brief T2 p. 5)."""
    _, dataset_id, document_id = await _seed(sm)
    async with transaction(sm) as session:
        await repo.upsert(
            session,
            document_id=document_id,
            dataset_id=dataset_id,
            outline=_OUTLINE,
            outline_source="headings",
            now_ms=TIME_MS,
        )
        await session.execute(text("DELETE FROM documents WHERE id = :id"), {"id": document_id})
        left = (await session.execute(text("SELECT COUNT(*) FROM document_profiles"))).scalar_one()
    assert left == 0
