"""Sklejenie biegu oceny (T4, kontrakt C11/C15): plan → stos efemeryczny → migracja →
zasiew → ocena → manifest → artefakt + raport.

Punkt wejścia ``python -m wdeval.run``. Walidacje argumentów, korpusów i binarek
robi ``wdeval.cli.plan_run`` PRZED podniesieniem stosu (kody 2/3 wg C11); tutaj
jest już tylko I/O: Docker, migracja Alembic (synchronicznie, bo env.py robi
własne ``asyncio.run``), baza i LLM (kody 0/1). ``WD_DB_*`` bierzemy wyłącznie
z env wypisanego przez stos — nigdy z ``os.environ``.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from alembic.config import Config
from pydantic import SecretStr

from alembic import command
from app.core.config import Settings
from app.parsing.types import PdfStrategy
from app.services.datasets import DEFAULT_PARSER_CONFIG
from wdeval.cli import BETA_DATASET_PATH, PreflightError, RunPlan, UsageError, plan_run
from wdeval.dataset import LANGUAGES, SOURCES
from wdeval.evaluate import RunResult, make_ask, make_judge, run_evaluation
from wdeval.judge_env import judge_endpoint_from_env
from wdeval.judge_prompt import JUDGE_PROMPT_VERSION
from wdeval.llm_models import model_family
from wdeval.manifest import build_manifest, config_fingerprint, validate_manifest
from wdeval.metrics import ChunkView
from wdeval.profiles import LAYOUT_BY_ARM
from wdeval.provenance import beta_inputs, codex_inputs, git_commit, git_dirty
from wdeval.report import build_artifact, render_report, write_artifact
from wdeval.router_predict import RouterCounts, predict_router, sum_counts
from wdeval.seed import (
    CHAT_CONFIG,
    ArmSeed,
    all_chunks,
    create_eval_user,
    register_models,
    running_worker,
    seed_arm,
)
from wdeval.stack import REPO_ROOT, ephemeral_stack

_SEED_TIMEOUT_S = 2400.0  # limit zasiewu jednego ramienia (nightly: pełny korpus bety, OCR)

# Ramię → strategia PDF dla predykcji routera: fast/auto wprost; vision, bo
# layout_recognize (nazwa modelu) nie należy do _LAYOUT_PLAIN
# (app/services/ingest_pipeline.py:56, app/services/ingest_convert.py:37).
_STRATEGY_BY_ARM: dict[str, PdfStrategy] = {"fast": "fast", "auto": "auto", "vision": "vision"}


def _services(llm: str) -> tuple[str, ...]:
    """Usługi stosu: fake dokłada fake-llm (C11)."""
    return ("mariadb-test", "fake-llm") if llm == "fake" else ("mariadb-test",)


def _settings(env: dict[str, str], *, llm: str, storage_root: str) -> Settings:
    """Ustawienia biegu z env stosu; przy fake OCR wyłączony, klucz LLM "fake"."""
    fields: dict[str, Any] = {
        "env": "test",
        "db_host": env["WD_DB_HOST"],
        "db_port": int(env["WD_DB_PORT"]),
        "db_user": env["WD_DB_USER"],
        "db_password": SecretStr(env["WD_DB_PASSWORD"]),
        "db_name": env["WD_DB_NAME"],
        "storage_root": storage_root,
        "worker_poll_s": 0.05,
    }
    if llm == "fake":
        fields["llm_base_url"] = env["WD_LLM_BASE_URL"]
        fields["llm_api_key"] = SecretStr("fake")
        fields["ocr_engine"] = "none"
    else:
        fields["llm_base_url"] = os.environ["WD_LLM_BASE_URL"]
        fields["llm_api_key"] = SecretStr(os.environ["WD_LLM_API_KEY"])
    return Settings(**fields)


def _migrate(settings: Settings) -> None:
    """Migracja synchronicznie, przed ``asyncio.run`` (wzorzec helpers.alembic_cfg)."""
    cfg = Config(str(REPO_ROOT / "backend" / "alembic.ini"))
    cfg.attributes["settings"] = settings
    command.upgrade(cfg, "head")


def _router_of_arm(plan: RunPlan, arm: str) -> RouterCounts:
    """Predykcja routera po plikach PDF z dysku; brak PDF-ów → same zera."""
    strategy = _STRATEGY_BY_ARM[arm]
    return sum_counts(
        predict_router(
            doc.path,
            strategy,
            vision_available=bool(plan.models.image2text),
            ocr_available=False,
        )
        for doc in plan.docs
        if doc.path is not None and doc.path.suffix.lower() == ".pdf"
    )


def _arm_entry(plan: RunPlan, arm: str, seed: ArmSeed) -> dict[str, Any]:
    """Wpis ``arms`` manifestu (kształt C8)."""
    chunk_token_num = int(DEFAULT_PARSER_CONFIG["chunk_token_num"])
    return {
        "arm": arm,
        "dataset_name": seed.spec.dataset_name,
        "layout_recognize": seed.spec.layout_recognize,
        "config_fingerprint": config_fingerprint(
            files=list(seed.documents),
            layout_recognize=seed.spec.layout_recognize,
            embedding_model=plan.models.embedding,
            embedding_dim=plan.models.dimension,
            chunk_token_num=chunk_token_num,
            chat_config=CHAT_CONFIG,
        ),
        "chat_config": CHAT_CONFIG,
        "embedding_model": plan.models.embedding,
        "dimension": plan.models.dimension,
        "chunk_token_num": chunk_token_num,
        "documents": list(seed.documents),
        "doc_count": len(seed.documents),
        "documents_failed": [{"name": name, "error": error} for name, error in seed.failed],
        "chunk_count": seed.chunk_count,
        "router": asdict(_router_of_arm(plan, arm)),
        "parse_seconds": seed.parse_seconds,
    }


def _manifest(
    plan: RunPlan,
    seeds: dict[str, ArmSeed],
    result: RunResult,
    settings: Settings,
    *,
    judge_endpoint: str,
) -> dict[str, Any]:
    """Manifest biegu ze wszystkimi polami C8; ``judge_endpoint`` wg C5 (bez URL-a/klucza)."""
    return build_manifest(
        run_id=plan.run_id,
        timestamp=datetime.now(UTC).isoformat(),
        git_commit=git_commit(REPO_ROOT),
        git_dirty=git_dirty(REPO_ROOT),
        profile=plan.profile.name,
        llm=plan.llm,
        k_list=plan.k_list,
        retrieval={
            "top_n": CHAT_CONFIG["top_n"],
            "similarity_threshold": CHAT_CONFIG["similarity_threshold"],
            "vector_similarity_weight": CHAT_CONFIG["vector_similarity_weight"],
        },
        answering_model={
            "name": plan.models.chat,
            "family": model_family(plan.models.chat, fake=plan.llm == "fake"),
        },
        embedding_model={"name": plan.models.embedding, "dimension": plan.models.dimension},
        judge_model={
            "name": plan.models.judge,
            "family": model_family(plan.models.judge, fake=plan.llm == "fake"),
            "mode": plan.models.judge_mode,
            "endpoint": judge_endpoint,
        },
        judge_prompt_version=JUDGE_PROMPT_VERSION,
        inputs={
            "beta": (
                beta_inputs(
                    BETA_DATASET_PATH,
                    plan.beta_corpus,
                    sum(1 for item in plan.items if item.source == "beta"),
                )
                if plan.beta_corpus is not None
                else None
            ),
            "codex": (
                codex_inputs(
                    plan.codex_corpus,
                    gold_item_count=sum(1 for item in plan.items if item.source == "codex-gold"),
                    poquad_path=plan.poquad_path,
                    poquad_sample=plan.profile.poquad_n,
                    poquad_seed=plan.poquad_seed,
                )
                if plan.codex_corpus is not None
                else None
            ),
        },
        item_count=len(plan.items),
        item_count_by_source={
            source: sum(1 for item in plan.items if item.source == source)
            for source in SOURCES
            if any(item.source == source for item in plan.items)
        },
        item_count_by_language={
            language: sum(1 for item in plan.items if item.language == language)
            for language in LANGUAGES
            if any(item.language == language for item in plan.items)
        },
        arms=[_arm_entry(plan, arm, seeds[arm]) for arm in plan.arms],
        comparisons=result.comparisons,
        ocr_engine=settings.ocr_engine,
    )


async def run_pipeline(plan: RunPlan, settings: Settings) -> tuple[dict[str, Any], str]:
    """Zasiew ramion i ocena na działającym stosie; zwraca (artefakt, raport)."""
    # Sędzia z osobnego endpointu (C4): fake nie czyta env sędziego wcale, live czyta
    # os.environ — częściowa konfiguracja pada tu, przed podniesieniem bazy.
    endpoint = None if plan.llm == "fake" else judge_endpoint_from_env(os.environ)
    seeds: dict[str, ArmSeed] = {}
    kb: dict[str, list[ChunkView]] = {}
    async with running_worker(settings) as container:
        await register_models(container, plan.models, register_judge=endpoint is None)
        principal = await create_eval_user(container)
        for arm in plan.arms:
            layout = plan.models.image2text if arm == "vision" else LAYOUT_BY_ARM[arm]
            seed = await seed_arm(
                container,
                principal,
                arm,
                layout,
                plan.docs,
                plan.models,
                timeout_s=_SEED_TIMEOUT_S,
            )
            seeds[arm] = seed
            kb[arm] = await all_chunks(container, seed.spec.dataset_id)

        async def chunks_of(arm: str) -> list[ChunkView]:
            return kb[arm]

        result = await run_evaluation(
            plan.items,
            list(plan.arms),
            ask=make_ask(
                container,
                principal,
                {name: seeds[name].spec.chat_id for name in plan.arms},
                {name: {view.chunk_id: view for view in kb[name]} for name in plan.arms},
            ),
            judge=make_judge(container, plan.models, endpoint),
            all_chunks=chunks_of,
            documents={name: set(seeds[name].documents) for name in plan.arms},
            k_list=plan.k_list,
        )

    manifest = _manifest(
        plan,
        seeds,
        result,
        settings,
        judge_endpoint="judge_env" if endpoint else "gateway",
    )
    errors = validate_manifest(manifest)
    if errors:
        raise RuntimeError("manifest: " + "; ".join(errors))
    artifact = build_artifact(
        manifest,
        [item_result for _, item_result in result.results],
        result.aggregates,
        result.comparisons,
    )
    report = render_report(
        result.aggregates,
        k_list=plan.k_list,
        header={
            "run_id": plan.run_id,
            "profile": plan.profile.name,
            "llm": plan.llm,
            "items": len(plan.items),
        },
    )
    return artifact, report


def main(argv: list[str] | None = None) -> int:
    """Punkt wejścia ``python -m wdeval.run``; kody wyjścia wg C11."""
    t0 = time.monotonic()
    try:
        plan = plan_run(argv, environ=os.environ, now=datetime.now(UTC))
    except UsageError as exc:
        for message in exc.messages:
            print(message, file=sys.stderr)
        return 2
    except PreflightError as exc:
        for message in exc.messages:
            print(message, file=sys.stderr)
        return 3
    try:
        with (
            ephemeral_stack(_services(plan.llm)) as env,
            tempfile.TemporaryDirectory() as tmp,
        ):
            settings = _settings(env, llm=plan.llm, storage_root=tmp)
            _migrate(settings)
            artifact, report = asyncio.run(run_pipeline(plan, settings))
    except Exception as exc:  # noqa: BLE001 — granica CLI: każdy błąd biegu → kod 1
        print(f"eval: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    write_artifact(plan.out, artifact)
    print(report)
    print(f"eval: artefakt {plan.out}", file=sys.stderr)
    print(f"eval: czas biegu {time.monotonic() - t0:.1f} s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
