"""Etap ``integrations``: tabele ``ai_hub_*`` → tabele integracji WD (kontrakt §8 i §9 WP E4-6b1).

Kolejność zapisu: ``integrations`` → ``integration_sharepoint`` → ``integration_containers`` →
``integration_item_mappings``; ``integration_sync_runs``/``integration_sync_events`` niezależnie.
Sekret klienta SharePoint odszyfrowujemy kluczem źródłowym i szyfrujemy kodem WD (AAD per
integracja) — jawny sekret, szyfrogram źródła ani żaden klucz nie trafiają do raportu ani Issues.
Mapowanie wierszy: ``integration_rows.py``; kolumny i SQL: ``integration_sql.py``.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import Issue, RunContext, StageInventory, StageResult
from app.tools.ragflow_migrate.stages.integration_rows import (
    Row,
    container_row,
    event_row,
    integration_row,
    mapping_row,
    run_row,
    sharepoint_row,
)
from app.tools.ragflow_migrate.stages.integration_sql import (
    CONTAINER_TARGET,
    DATASET_OWNERS,
    DOCUMENT_IDS,
    EVENT_TARGET,
    MAPPING_TARGET,
    RUN_TARGET,
    SHAREPOINT_TARGET,
    SOURCE_DRIVES,
    SOURCE_EVENTS,
    SOURCE_INTEGRATIONS,
    SOURCE_MAPPINGS,
    SOURCE_RUNS,
    SOURCE_TABLES,
    TARGET_COUNT,
    Target,
    integrations_target,
    write_rows,
)
from app.tools.ragflow_migrate.stages.sp_secret import SourceSecretError, decrypt_source_secret


def _rows(src: Source, table: str) -> list[Row]:
    """Wiersze tabeli źródłowej; brak tabeli → pusto (etap raportuje zerowy inwentarz)."""
    return src.rows(table) if src.has_table(table) else []


async def _select_ids(session: AsyncSession, sql: str, ids: list[str]) -> list[tuple[Any, ...]]:
    """Wiersze zapytania `SELECT … IN :ids`; puste ``ids`` → brak zapytania (pusta lista)."""
    if not ids:
        return []
    statement = text(sql).bindparams(bindparam("ids", expanding=True))
    result = await session.execute(statement, {"ids": ids})
    return [tuple(row) for row in result.all()]


def _resolve_secrets(rows: list[Row], ctx: RunContext) -> tuple[dict[int, str], list[Issue]]:
    """Id integracji → jawny sekret; brak klucza/błąd odszyfrowania → ``critical`` (kontrakt §9).

    Komunikaty Issues zawierają wyłącznie id integracji — nigdy klucza, szyfrogramu ani sekretu.
    """
    if not rows:
        return {}, []
    if ctx.src_sp_crypto_key is None:
        return {}, [
            Issue(
                severity="critical",
                code="sp_key_missing",
                message="brak klucza źródłowego sekretów SharePoint (--src-sp-crypto-key)",
                ids=[str(row["id"]) for row in rows],
            )
        ]
    key = ctx.src_sp_crypto_key.get_secret_value()
    secrets: dict[int, str] = {}
    issues: list[Issue] = []
    for row in rows:
        try:
            secrets[int(row["id"])] = decrypt_source_secret(
                key, str(row["client_secret_encrypted"])
            )
        except SourceSecretError:
            issues.append(
                Issue(
                    severity="critical",
                    code="sp_decrypt_failed",
                    message=f"nie udało się odszyfrować sekretu integracji {row['id']}",
                    ids=[str(row["id"])],
                )
            )
    return secrets, issues


async def _dataset_owners(session: AsyncSession, dataset_ids: list[str]) -> dict[str, str]:
    """Id datasetu → jego ``created_by`` w celu (kontrakt §8: ``owner_id``)."""
    rows = await _select_ids(session, DATASET_OWNERS, list(dict.fromkeys(dataset_ids)))
    return {str(row[0]): str(row[1]) for row in rows}


async def _known_documents(session: AsyncSession, document_ids: list[str]) -> set[str]:
    """Id dokumentów obecnych w tabeli ``documents`` celu (kontrakt §8)."""
    rows = await _select_ids(session, DOCUMENT_IDS, list(dict.fromkeys(document_ids)))
    return {str(row[0]) for row in rows}


async def _target_count(session: AsyncSession) -> int:
    """Liczba wierszy ``integrations`` w celu po etapie (``StageResult.target_count``)."""
    return int((await session.execute(text(TARGET_COUNT))).scalar_one())


@dataclass(frozen=True)
class _SourceRows:
    """Wiersze pięciu tabel źródłowych etapu."""

    integrations: list[Row]
    drives: list[Row]
    runs: list[Row]
    events: list[Row]
    mappings: list[Row]


@dataclass(frozen=True)
class _Prepared:
    """Wiersze celu gotowe do zapisu (kolejność: integracje, sharepoint, containers, mappings)."""

    integrations: list[Row]
    sharepoint: list[Row]
    containers: list[Row]
    mappings: list[Row]
    runs: list[Row]
    events: list[Row]


def _source_rows(src: Source) -> _SourceRows:
    """Wiersze tabel źródłowych etapu; brakująca tabela → pusto (kontrakt §8)."""
    return _SourceRows(
        integrations=_rows(src, SOURCE_INTEGRATIONS),
        drives=_rows(src, SOURCE_DRIVES),
        runs=_rows(src, SOURCE_RUNS),
        events=_rows(src, SOURCE_EVENTS),
        mappings=_rows(src, SOURCE_MAPPINGS),
    )


def _source_count(rows: _SourceRows) -> int:
    """Suma wierszy źródła po 6 tabelach celu (``integration_sharepoint`` dzieli źródło)."""
    return (
        2 * len(rows.integrations)
        + len(rows.drives)
        + len(rows.runs)
        + len(rows.events)
        + len(rows.mappings)
    )


async def _prepare(
    session: AsyncSession,
    rows: _SourceRows,
    secrets: dict[int, str],
    owners: dict[str, str],
    wd_key: str,
) -> tuple[_Prepared, list[Issue]]:
    """Wiersze źródła → wiersze celu; pominięte integracje dostają Issue (kontrakt §8)."""
    issues: list[Issue] = []
    writable: set[int] = set()
    for row in rows.integrations:
        integration_id = int(row["id"])
        if integration_id not in secrets:
            continue
        if str(row["dataset_id"]) not in owners:
            issues.append(
                Issue(
                    severity="warning",
                    code="integration_dataset_missing",
                    message=(
                        f"dataset integracji {integration_id} nie istnieje w celu"
                        " — integracja i jej dzieci pominięte"
                    ),
                    ids=[str(integration_id)],
                )
            )
            continue
        writable.add(integration_id)
    integration_rows: list[Row] = []
    sharepoint_rows: list[Row] = []
    for row in rows.integrations:
        integration_id = int(row["id"])
        if integration_id not in writable:
            continue
        target, row_issues = integration_row(
            row, secrets[integration_id], owners[str(row["dataset_id"])], wd_key
        )
        issues.extend(row_issues)
        integration_rows.append(target)
        sharepoint_rows.append(sharepoint_row(row))
    mapping_rows = [row for row in rows.mappings if int(row["integration_id"]) in writable]
    known_documents = await _known_documents(
        session, [str(row["ragflow_document_id"]) for row in mapping_rows]
    )
    mapping_targets: list[Row] = []
    for row in mapping_rows:
        target, row_issues = mapping_row(row, known_documents)
        issues.extend(row_issues)
        mapping_targets.append(target)
    run_targets: list[Row] = []
    for row in rows.runs:
        target, row_issues = run_row(row)
        issues.extend(row_issues)
        run_targets.append(target)
    return (
        _Prepared(
            integrations=integration_rows,
            sharepoint=sharepoint_rows,
            containers=[
                container_row(row) for row in rows.drives if int(row["integration_id"]) in writable
            ],
            mappings=mapping_targets,
            runs=run_targets,
            events=[event_row(row) for row in rows.events],
        ),
        issues,
    )


class IntegrationsStage:
    """Integracje SharePoint: ``ai_hub_*`` → tabele ``integrations*`` z przeszyfrowaniem sekretu."""

    name = "integrations"

    def plan(self, src: Source, ctx: RunContext) -> StageInventory:
        """Inwentarz: liczniki 5 tabel źródłowych i walidacja klucza sekretów (bez zapisu)."""
        rows = _rows(src, SOURCE_INTEGRATIONS)
        _secrets, issues = _resolve_secrets(rows, ctx)
        return StageInventory(
            stage=self.name,
            source_counts={table: len(_rows(src, table)) for table in SOURCE_TABLES},
            issues=issues,
            not_migrated={},
        )

    async def run(self, src: Source, session: AsyncSession, ctx: RunContext) -> StageResult:
        """Zapis wszystkich tabel integracji; liczniki sumują się po 6 tabelach celu."""
        rows = _source_rows(src)
        secrets, issues = _resolve_secrets(rows.integrations, ctx)
        owners = await _dataset_owners(
            session, [str(row["dataset_id"]) for row in rows.integrations]
        )
        wd_key = ctx.settings.crypto_key.get_secret_value()
        prepared, row_issues = await _prepare(session, rows, secrets, owners, wd_key)
        issues.extend(row_issues)
        targets: tuple[tuple[Target, list[Row]], ...] = (
            (integrations_target(wd_key, secrets), prepared.integrations),
            (SHAREPOINT_TARGET, prepared.sharepoint),
            (CONTAINER_TARGET, prepared.containers),
            (RUN_TARGET, prepared.runs),
            (EVENT_TARGET, prepared.events),
            (MAPPING_TARGET, prepared.mappings),
        )
        created = updated = 0
        for target, target_rows in targets:
            table_created, table_updated, _table_skipped = await write_rows(
                session, target, target_rows
            )
            created += table_created
            updated += table_updated
        source_count = _source_count(rows)
        return StageResult(
            stage=self.name,
            source_count=source_count,
            created=created,
            updated=updated,
            skipped=source_count - created - updated,
            target_count=await _target_count(session),
            issues=issues,
        )
