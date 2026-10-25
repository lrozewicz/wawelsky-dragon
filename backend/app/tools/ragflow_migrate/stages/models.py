"""Etap ``models``: używane modele źródła RAGFlow → tabela ``models`` WD (kontrakt §4, WP E4-6a).

Zbieranie używanych modeli i rozstrzyganie nazw jest czystą funkcją
:func:`resolve_models` — testowalną bez bazy (brief T5).
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import from_ms
from app.tools.ragflow_migrate.model_map import ModelMap
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import (
    Issue,
    RunContext,
    StageInventory,
    StageResult,
)

#: Pola tenanta z domyślnymi modelami i typem wynikającym z pola źródła (kontrakt §4).
_TENANT_MODEL_FIELDS: tuple[tuple[str, str], ...] = (
    ("llm_id", "chat"),
    ("embd_id", "embedding"),
    ("rerank_id", "rerank"),
    ("img2txt_id", "image2text"),
)

#: Od ilu różnych fabryk ta sama goła nazwa jest niejednoznaczna (kontrakt §4).
_MIN_FACTORIES_FOR_AMBIGUOUS = 2

_INSERT_SQL = text(
    "INSERT INTO models (id, name, model_type, provider, display_name, base_url, api_key_enc,"
    " max_tokens, dimension, extra, is_default, is_active, created_by,"
    " create_time, create_date, update_time, update_date)"
    " VALUES (:id, :name, :model_type, 'litellm', NULL, NULL, NULL,"
    " NULL, :dimension, NULL, 0, 1, NULL, :create_time, :create_date, :update_time, :update_date)"
)


@dataclass(frozen=True)
class UsedModel:
    """Używany model źródła: klucz ``llm_name@factory`` i typ z pola źródłowego."""

    key: str
    llm_name: str
    factory: str  # puste, gdy wartość nie ma `@`
    source_type: str  # chat|embedding|rerank|image2text — z pola, z którego pochodzi wartość


@dataclass(frozen=True)
class ResolvedModel:
    """Model docelowy WD: nazwa, typ i wymiar po rozstrzygnięciu mapy modeli."""

    name: str
    model_type: str
    dimension: int | None


def collect_used(src: Source) -> list[UsedModel]:
    """Używane modele źródła: ``knowledgebase.embd_id``, ``dialog.llm_id``, domyślne tenanta.

    Tabela ``dialog`` może nie istnieć w wąskim źródle — wtedy ``llm_id`` dialogów pomijamy.
    """
    used: list[UsedModel] = []
    for row in src.rows("knowledgebase"):
        _append(used, row.get("embd_id"), "embedding")
    if src.has_table("dialog"):
        for row in src.rows("dialog"):
            _append(used, row.get("llm_id"), "chat")
    for row in src.rows("tenant"):
        for field, source_type in _TENANT_MODEL_FIELDS:
            _append(used, row.get(field), source_type)
    return used


def tenant_llm_types(rows: list[dict[str, Any]]) -> dict[tuple[str, str], str]:
    """Typ modelu z ``tenant_llm``: ``(llm_name, llm_factory)`` → ``model_type``."""
    types: dict[tuple[str, str], str] = {}
    for row in rows:
        name = row.get("llm_name")
        model_type = row.get("model_type")
        if not name or not model_type:
            continue
        types.setdefault((str(name), str(row.get("llm_factory") or "")), str(model_type))
    return types


def resolve_models(
    used: list[UsedModel],
    tenant_llm_types: dict[tuple[str, str], str],
    model_map: ModelMap,
) -> tuple[dict[str, ResolvedModel], list[Issue]]:
    """Rozstrzyga nazwy i typy używanych modeli (czysta funkcja, bez bazy).

    Wpis w mapie wygrywa (``name``, opcjonalnie ``model_type`` i ``dimension``). Bez wpisu
    używamy gołej ``llm_name``, ale gdy ta sama goła nazwa występuje pod ≥ 2 różnymi
    fabrykami — Issue ``model_ambiguous`` (critical) i modelu **nie** piszemy.
    """
    unique = _unique_used(used)
    ambiguous = _ambiguous_names(unique, model_map)
    resolved: dict[str, ResolvedModel] = {}
    for model in unique:
        entry = model_map.get(model.key)
        if entry is not None:
            resolved[model.key] = ResolvedModel(
                name=entry.name,
                model_type=entry.model_type or _model_type(model, tenant_llm_types),
                dimension=entry.dimension,
            )
        elif model.llm_name not in ambiguous:
            resolved[model.key] = ResolvedModel(
                name=model.llm_name,
                model_type=_model_type(model, tenant_llm_types),
                dimension=None,
            )
    issues: list[Issue] = []
    for name in sorted(ambiguous):
        issues.append(
            Issue(
                severity="critical",
                code="model_ambiguous",
                message=(
                    f"model {name!r} występuje pod wieloma fabrykami i nie ma wpisu w mapie"
                    " modeli; dodaj wpis do --model-map"
                ),
                ids=sorted(model.key for model in unique if model.llm_name == name),
            )
        )
    for model in unique:
        if model_map.get(model.key) is None and model.llm_name not in ambiguous:
            issues.append(
                Issue(
                    severity="warning",
                    code="model_unmapped_default",
                    message=(
                        f"brak wpisu w mapie modeli dla {model.key!r};"
                        f" użyto nazwy {model.llm_name!r}"
                    ),
                    ids=[model.key],
                )
            )
    return resolved, issues


class ModelsStage:
    """Etap ``models``: ``plan`` liczy i ostrzega, ``run`` pisze używane modele do WD."""

    name = "models"

    def plan(self, src: Source, ctx: RunContext) -> StageInventory:
        """Inwentarz: liczniki tabel, uwagi o mapowaniu i katalog ``llm`` jako nieprzenoszony."""
        rows = _tenant_llm_rows(src)
        used = collect_used(src)
        _resolved, issues = resolve_models(used, tenant_llm_types(rows), ctx.model_map)
        unused = _unused_count(rows, used)
        if unused:
            issues.append(
                Issue(
                    severity="info",
                    code="models_unused",
                    message=(
                        f"{unused} modeli z tabeli tenant_llm nie jest używanych w źródle;"
                        " nie zostaną zmigrowane"
                    ),
                    ids=[],
                )
            )
        counts = {"tenant_llm": src.count("tenant_llm")}
        if src.has_table("llm"):
            counts["llm"] = src.count("llm")
        counts["knowledgebase"] = src.count("knowledgebase")
        return StageInventory(
            stage=self.name,
            source_counts=counts,
            issues=issues,
            not_migrated={"llm": counts.get("llm", 0)},
        )

    async def run(self, src: Source, session: AsyncSession, ctx: RunContext) -> StageResult:
        """Zapis używanych modeli; idempotencja po ``(name, model_type)`` → ``skipped``."""
        rows = _tenant_llm_rows(src)
        used = collect_used(src)
        resolved, issues = resolve_models(used, tenant_llm_types(rows), ctx.model_map)
        names: dict[str, str] = ctx.shared.setdefault("model_names", {})
        now = ctx.clock.now_ms()
        created = 0
        skipped = 0
        for key, model in resolved.items():
            exists = (
                await session.execute(
                    text("SELECT name FROM models WHERE name = :name AND model_type = :model_type"),
                    {"name": model.name, "model_type": model.model_type},
                )
            ).first()
            if exists is not None:
                skipped += 1
            else:
                await session.execute(
                    _INSERT_SQL,
                    {
                        "id": ctx.id_gen.new_id(),
                        "name": model.name,
                        "model_type": model.model_type,
                        "dimension": model.dimension,
                        "create_time": now,
                        "create_date": from_ms(now),
                        "update_time": now,
                        "update_date": from_ms(now),
                    },
                )
                created += 1
            names[key] = model.name
        return StageResult(
            stage=self.name,
            source_count=len(_unique_used(used)),
            created=created,
            updated=0,
            skipped=skipped,
            target_count=await _target_count(session, resolved),
            issues=issues,
        )


def _append(used: list[UsedModel], value: Any, source_type: str) -> None:
    """Dopisuje niepustą wartość pola źródła jako :class:`UsedModel`."""
    if value is None:
        return
    raw = str(value).strip()
    if not raw:
        return
    llm_name, _, factory = raw.partition("@")
    used.append(UsedModel(key=raw, llm_name=llm_name, factory=factory, source_type=source_type))


def _unique_used(used: list[UsedModel]) -> list[UsedModel]:
    """Pierwsze wystąpienie każdego klucza (kolejność zbierania zachowana)."""
    unique: dict[str, UsedModel] = {}
    for model in used:
        unique.setdefault(model.key, model)
    return list(unique.values())


def _ambiguous_names(used: list[UsedModel], model_map: ModelMap) -> set[str]:
    """Gołe nazwy bez wpisu w mapie, występujące pod ≥ 2 różnymi fabrykami."""
    factories: dict[str, set[str]] = {}
    for model in used:
        if model_map.get(model.key) is None:
            factories.setdefault(model.llm_name, set()).add(model.factory)
    return {name for name, seen in factories.items() if len(seen) >= _MIN_FACTORIES_FOR_AMBIGUOUS}


def _model_type(model: UsedModel, tenant_llm_types: dict[tuple[str, str], str]) -> str:
    """Typ z ``tenant_llm`` dla (llm_name, factory), inaczej typ z pola źródłowego."""
    return tenant_llm_types.get((model.llm_name, model.factory)) or model.source_type


def _tenant_llm_rows(src: Source) -> list[dict[str, Any]]:
    """Wiersze ``tenant_llm``; brak tabeli → pusto (wąskie źródło)."""
    return src.rows("tenant_llm") if src.has_table("tenant_llm") else []


def _unused_count(rows: list[dict[str, Any]], used: list[UsedModel]) -> int:
    """Liczba wpisów ``tenant_llm``, których model nie jest używany w źródle."""
    used_keys = {model.key for model in used}
    unused = 0
    for row in rows:
        key = _key_of(row.get("llm_name"), row.get("llm_factory"))
        if key is not None and key not in used_keys:
            unused += 1
    return unused


def _key_of(llm_name: Any, llm_factory: Any) -> str | None:
    """Klucz ``llm_name@factory`` dla wiersza ``tenant_llm`` (bez ``@``, gdy brak fabryki)."""
    if llm_name is None:
        return None
    name = str(llm_name).strip()
    if not name:
        return None
    factory = str(llm_factory).strip() if llm_factory else ""
    return f"{name}@{factory}" if factory else name


async def _target_count(session: AsyncSession, resolved: dict[str, ResolvedModel]) -> int:
    """Liczba wierszy ``models`` celujących w rozstrzygnięte pary ``(name, model_type)``."""
    pairs = {(model.name, model.model_type) for model in resolved.values()}
    if not pairs:
        return 0
    rows = (await session.execute(text("SELECT name, model_type FROM models"))).all()
    return sum(1 for row in rows if (str(row[0]), str(row[1])) in pairs)
