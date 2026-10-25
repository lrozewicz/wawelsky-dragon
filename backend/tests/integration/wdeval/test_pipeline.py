"""Integracyjny pipeline wdeval (kontrakt C14): seed mini-korpusu produkcyjną ścieżką WD
i dwa biegi pętli ewaluacji na fake-llm — determinizm między biegami.

Markery db + fakellm; wzorce: ``tests/integration/ingest/test_worker_e2e.py``
(worker w procesie) i ``tests/integration/ingest/conftest.py`` (migracja sync).
"""

import os
import re
from pathlib import Path

import pytest

from alembic import command
from app.core.config import Settings
from tests.integration.db.helpers import alembic_cfg
from wdeval.evaluate import make_ask, make_judge, run_evaluation
from wdeval.fixtures import build_mini_corpus
from wdeval.llm_models import FAKE_MODELS
from wdeval.metrics import ChunkView
from wdeval.report import item_to_json
from wdeval.seed import all_chunks, create_eval_user, register_models, running_worker, seed_arm

_ITEM_COUNT = 3  # pozycje mini-korpusu: mini-pl-01, mini-en-01, mini-un-01

pytestmark = [
    pytest.mark.db,
    pytest.mark.fakellm,
    pytest.mark.skipif(
        not os.environ.get("WD_LLM_BASE_URL"),
        reason="fakellm: brak WD_LLM_BASE_URL (eksportuje verify.sh)",
    ),
]


@pytest.fixture
def migrated_db(fresh_db: Settings) -> Settings:
    """Świeża baza po migracji do head; sync, bo env.py Alembic robi asyncio.run (C12)."""
    command.upgrade(alembic_cfg(fresh_db), "head")
    return fresh_db


async def test_seed_mini_korpusu_i_dwa_biegi_sa_deterministyczne(
    migrated_db: Settings, tmp_path: Path
) -> None:
    settings = migrated_db.model_copy(
        update={
            "storage_root": str(tmp_path / "storage"),
            "ocr_engine": "none",
            "worker_poll_s": 0.05,
        }
    )
    items, docs = build_mini_corpus(tmp_path / "corpus")

    async with running_worker(settings) as container:
        await register_models(container, FAKE_MODELS)
        principal = await create_eval_user(container)

        seed = await seed_arm(
            container, principal, "fast", "Plain Text", docs, FAKE_MODELS, timeout_s=60
        )
        assert seed.failed == []
        assert seed.documents == ["mini-en.txt", "mini.pdf"]
        assert seed.chunk_count > 0

        chunks = await all_chunks(container, seed.spec.dataset_id)
        index: dict[str, dict[str, ChunkView]] = {"fast": {c.chunk_id: c for c in chunks}}

        async def arm_chunks(_arm: str) -> list[ChunkView]:
            return chunks

        common = {
            "ask": make_ask(container, principal, {"fast": seed.spec.chat_id}, index),
            "judge": make_judge(container, FAKE_MODELS),
            "all_chunks": arm_chunks,
            "documents": {"fast": set(seed.documents)},
            "k_list": [1, 3, 6],
        }
        run1 = await run_evaluation(items, ["fast"], **common)
        run2 = await run_evaluation(items, ["fast"], **common)

        assert len(run1.results) == _ITEM_COUNT
        assert [item_to_json(r) for _, r in run1.results] == [
            item_to_json(r) for _, r in run2.results
        ]

        by_id = {r.item_id: r for _, r in run1.results}
        assert "grounded" in by_id["mini-pl-01"].verdicts
        assert "empty_ok" in by_id["mini-un-01"].verdicts
        for _item, result in run1.results:
            for key in result.retrieved_chunks:
                assert re.match(r"^mini(-en\.txt|\.pdf)#\d+$", key)
