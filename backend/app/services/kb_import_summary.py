"""Podsumowanie zwalidowanej paczki importu (K19 §3, CONTRACT E7-1b §2).

``build_summary`` zwraca zwykły ``dict`` o kształcie ``ImportSummary`` — warstwa usług nie
importuje ``app.api`` (import-linter „Warstwy”); walidację schematem robi trasa, wołając
``ImportSummary.model_validate(...)``. Zgodność docelowego modelu liczymy po wierszach
rejestru (``models``), tą samą drogą, którą tworzy dataset ``DatasetService.create``.

DEC-342: na świeżej instalacji model embeddingów ma ``dimension IS NULL`` aż do pierwszego
użycia, więc ``build_summary`` sonduje wymiar aktywnych modeli (model paczki i model domyślny)
poza transakcją odczytu — bez tego combobox w ``ImportDialog`` był pusty.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.timeutil import from_ms
from app.db.repositories import datasets as datasets_repo
from app.db.repositories import models as models_repo
from app.db.repositories.models import ModelRow
from app.db.uow import transaction
from app.services.datasets import EMBEDDING_PROBE_TEXT
from app.services.kb_package.reader import PackageReader
from app.services.kb_package.validate import ValidatedPackage

if TYPE_CHECKING:
    from app.core.container import Container
    from app.llm.gateway import LLMGateway
    from app.llm.registry import ModelRegistry

logger = logging.getLogger(__name__)

__all__ = ["MAX_NAME_LEN", "build_summary", "name_key"]

# Typ modelu embeddingów w kolumnie `models.model_type` (K5 §0).
EMBEDDING_MODEL_TYPE = "embedding"

# Sufiks proponowanej nazwy zajętej u aktora (K19 §3, Q46); data = dzień z zegara kontenera.
SUFFIX_DATE = " (import {date})"

# Limit długości nazwy datasetu (DDL `datasets.name VARCHAR(128)`).
MAX_NAME_LEN = 128


def name_key(name: str) -> str:
    """Klucz porównania nazwy datasetu: ``LOWER(name)`` — jak kolumna ``datasets.name_ci``.

    Unikat ``uq_datasets_tenant_name_ci`` działa na ``LOWER(name)`` (bez ``strip``), więc
    konflikt nazwy liczymy tą samą drogą w ``build_summary`` i w ``start_import`` (MINOR T6).
    """
    return name.lower()


def _available_models(rows: list[ModelRow]) -> list[dict[str, Any]]:
    """Modele embeddingów dostępne aktorowi: aktywne i ze znanym wymiarem (K19 §3 target.models).

    Brak osobnej ścieżki per aktor — rejestr jest instancyjny, więc filtr idzie po
    ``models_repo.list_all`` jak przy tworzeniu datasetu (ModelRegistry).
    """
    return [
        {"name": row.name, "dimension": row.dimension}
        for row in rows
        if row.model_type == EMBEDDING_MODEL_TYPE and row.is_active and row.dimension is not None
    ]


def _probe_names(
    rows: list[ModelRow], *, model_name: str, included: bool, default_row: ModelRow | None
) -> list[str]:
    """Nazwy modeli do sondy wymiaru: model paczki (gdy ``included``) i model domyślny.

    DEC-342 p. 1: sondujemy wyłącznie aktywne modele embeddingów z ``dimension IS NULL``
    (model ze znanym wymiarem nie jest sondowany — licznik wywołań ``embed`` = 0), i tylko
    kandydatów: nazwę modelu z manifestu (gdy paczka niesie wektory) oraz model domyślny.
    Kolejność: model paczki, potem domyślny; bez duplikatów.
    """
    wanted: list[str] = []
    if included:
        wanted.append(model_name)
    if default_row is not None and default_row.is_active:
        wanted.append(default_row.name)
    names: list[str] = []
    for name in wanted:
        if name in names:
            continue
        probeable = any(
            row.name == name
            and row.model_type == EMBEDDING_MODEL_TYPE
            and row.is_active
            and row.dimension is None
            for row in rows
        )
        if probeable:
            names.append(name)
    return names


async def _probe_dimensions(container: Container, names: list[str]) -> dict[str, int]:
    """Mierzy wymiar modeli z ``dimension IS NULL`` sondą embeddingu (DEC-342 p. 1 i 3).

    Sonda jest ta sama co w ``DatasetService._ensure_dimension`` i ``_target_dimension``:
    ``registry.resolve(name, "embedding")`` → ``llm.embed(ref, [EMBEDDING_PROBE_TEXT])`` →
    ``registry.set_dimension(ref.id, len(vector))`` (zapis trwały w ``models.dimension``).
    Dowolny wyjątek tej drogi (bramka LLM, brak modelu, ``OperationNotAllowed`` przy wyścigu)
    jest logowany i pomijany — model zostaje bez wymiaru i nie trafi do ``target.models``.
    ``try/except`` obejmuje wyłącznie wywołanie sondy; log bez treści i URL (tylko klasa).
    """
    if not names:
        return {}
    registry = cast("ModelRegistry", container.models)
    llm = cast("LLMGateway", container.llm)
    measured: dict[str, int] = {}
    for name in names:
        try:
            ref = await registry.resolve(name, "embedding")
            vector = (await llm.embed(ref, [EMBEDDING_PROBE_TEXT]))[0]
            dimension = len(vector)
            if ref.id is not None:  # model spoza rejestru (id None) nie ma wiersza do zapisu
                await registry.set_dimension(ref.id, dimension)
        except Exception as exc:  # noqa: BLE001 — sonda sieciowa: błąd nie wywraca uploadu
            logger.warning(
                "embedding dimension probe failed",
                extra={
                    "event": "embedding_probe_failed",
                    "model_name": name,
                    "exception": type(exc).__name__,
                },
            )
            continue
        measured[name] = dimension
    return measured


def _with_suffix(name: str, suffix: str) -> str:
    """Nazwa przycięta tak, by zmieścił się cały sufiks (limit ``MAX_NAME_LEN``).

    Skraca wyłącznie nazwę bazową — sufiks daty/licznika zostaje w całości.
    """
    return name[: MAX_NAME_LEN - len(suffix)] + suffix


def _suggest_name(name: str, taken: set[str], date_str: str) -> str:
    """Nazwa z paczki, a gdy zajęta u aktora — z sufiksem daty i licznikiem (K19 §3, Q46)."""
    if name_key(name) not in taken:
        return name
    suffix = SUFFIX_DATE.format(date=date_str)
    candidate = _with_suffix(name, suffix)
    if name_key(candidate) not in taken:
        return candidate
    counter = 2
    while True:
        tail = f" {counter}"
        candidate = _with_suffix(name, suffix + tail)
        if name_key(candidate) not in taken:
            return candidate
        counter += 1


def _estimated_reembed_tokens(pkg: ValidatedPackage) -> int:
    """Σ ``token_count`` chunków — czytane strumieniowo z paczki (K19 §3)."""
    return sum(chunk.token_count for chunk in PackageReader(pkg).chunks())


async def build_summary(
    container: Container, *, actor_id: str, pkg: ValidatedPackage
) -> dict[str, Any]:
    """Podsumowanie paczki dla aktora: zgodność modelu, wolna nazwa, koszt reembeddingu.

    Zwraca ``dict`` o kluczach ``ImportSummary`` (K19 §3) — dosłownie.
    """
    manifest = pkg.manifest
    embedding = manifest.embedding
    sessionmaker = cast(async_sessionmaker[AsyncSession], container.sessionmaker)
    async with transaction(sessionmaker) as session:
        rows = await models_repo.list_all(session)
        default_row = await models_repo.get_default(session, EMBEDDING_MODEL_TYPE)
        taken = await datasets_repo.names_taken(session, actor_id)
    # DEC-342 p. 1: sonda (sieciowa) poza transakcją odczytu (po jej zamknięciu).
    measured = await _probe_dimensions(
        container,
        _probe_names(
            rows,
            model_name=embedding.model_name,
            included=embedding.included,
            default_row=default_row,
        ),
    )
    if measured:
        rows = [
            replace(row, dimension=measured[row.name]) if row.name in measured else row
            for row in rows
        ]
    models = _available_models(rows)
    compatible = embedding.included and any(
        model["name"] == embedding.model_name and model["dimension"] == embedding.dimension
        for model in models
    )
    # DEC-342 p. 4: niezmiennik ``default_model`` ∈ models albo ``null`` — model domyślny
    # bez wymiaru po nieudanej sondzie nie trafia do selekta, więc nie może być domyślnym.
    if compatible:
        default_model: str | None = embedding.model_name
    elif (
        default_row is not None
        and default_row.is_active
        and any(model["name"] == default_row.name for model in models)
    ):
        default_model = default_row.name
    else:
        default_model = None
    date_str = from_ms(container.clock.now_ms()).strftime("%Y-%m-%d")
    return {
        "name": manifest.dataset.name,
        "description": manifest.dataset.description,
        "documents": manifest.counts.documents,
        "chunks": manifest.counts.chunks,
        "schema_version": manifest.schema_version,
        "wd_version": manifest.wd_version,
        "created_at": manifest.created_at,
        "embedding": {
            "model_name": embedding.model_name,
            "dimension": embedding.dimension,
            "included": embedding.included,
        },
        "target": {
            "compatible": compatible,
            "default_model": default_model,
            "models": models,
        },
        "suggested_name": _suggest_name(manifest.dataset.name, taken, date_str),
        "name_taken": name_key(manifest.dataset.name) in taken,
        "estimated_reembed_tokens": _estimated_reembed_tokens(pkg),
    }
