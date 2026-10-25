"""Komenda ``verify``: zgodność celu ze źródłem i uwagi ``Issue`` (kontrakt E4-6c §4, §5)."""

import asyncio

from app.core.config import Settings
from app.core.timeutil import iso, now_ms
from app.db.engine import make_engine, make_sessionmaker
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import Issue, RunContext
from app.tools.ragflow_migrate.verify_contract import run_contract_sample
from app.tools.ragflow_migrate.verify_counts import CountsPart, collect_counts
from app.tools.ragflow_migrate.verify_parse import collect_parse
from app.tools.ragflow_migrate.verify_types import (
    ContractSample,
    ParseSummary,
    VerifyReport,
)


async def run_verify(src: Source, settings: Settings, ctx: RunContext) -> VerifyReport:
    """Buduje raport ``verify``: liczniki, pliki, modele, parsowanie, próbka i uwagi (§4).

    Otwiera własną sesję celu (``make_engine``/``make_sessionmaker``) i zamyka ją po biegu;
    źródło należy do wołającego (CLI zamyka je w ``finally``).
    """
    started_at = iso(now_ms())
    engine = make_engine(settings)
    try:
        sessionmaker = make_sessionmaker(engine)
        async with sessionmaker() as session:
            counts = await collect_counts(src, session, ctx.model_map)
            parse = await collect_parse(session)
            # Próbka kontraktowa stawia aplikację in-process (TestClient) — stąd wątek.
            contract = await asyncio.to_thread(run_contract_sample, src, settings)
    finally:
        await engine.dispose()
    return VerifyReport(
        started_at=started_at,
        finished_at=iso(now_ms()),
        counts=counts.counts,
        missing_blob=counts.missing_blob,
        size_mismatch=counts.size_mismatch,
        embedding_mismatch_chats=counts.embedding_mismatch_chats,
        unmapped_models=counts.unmapped_models,
        orphan_access=counts.orphan_access,
        parse=parse,
        contract=contract,
        issues=_issues(counts, parse, contract),
    )


def _issues(counts: CountsPart, parse: ParseSummary, contract: ContractSample) -> list[Issue]:
    """Uwagi raportu — kody i wagi dosłownie z kontraktu §3.2."""
    issues: list[Issue] = []
    for entry in counts.counts:
        if entry.missing_ids:
            issues.append(
                Issue(
                    severity="critical" if entry.critical else "warning",
                    code="count_missing",
                    message=(f"brak {len(entry.missing_ids)} wierszy tabeli {entry.table} w celu"),
                    ids=list(entry.missing_ids),
                )
            )
    if counts.missing_blob:
        issues.append(
            Issue(
                severity="warning",
                code="blob_missing",
                message="dokumenty celu bez bloba w magazynie",
                ids=list(counts.missing_blob),
            )
        )
    if counts.size_mismatch:
        issues.append(
            Issue(
                severity="warning",
                code="blob_size_mismatch",
                message="rozmiar bloba nie zgadza się z rozmiarem deklarowanym w źródle",
                ids=list(counts.size_mismatch),
            )
        )
    if counts.embedding_mismatch_chats:
        issues.append(
            Issue(
                severity="warning",
                code="chat_embedding_mismatch",
                message="datasety czatu mają różne modele embeddingu",
                ids=list(counts.embedding_mismatch_chats),
            )
        )
    if counts.unmapped_models:
        issues.append(
            Issue(
                severity="warning",
                code="model_unmapped",
                message="model źródła bez odpowiednika w tabeli models celu ani w mapie modeli",
                ids=list(counts.unmapped_models),
            )
        )
    if counts.orphan_access:
        issues.append(
            Issue(
                severity="warning",
                code="access_orphan",
                message="dostęp do dialogu spoza źródła — nie jest rozbieżnością",
                ids=list(counts.orphan_access),
            )
        )
    failed = [failure.document_id for failure in parse.failures]
    if failed:
        issues.append(
            Issue(
                severity="warning",
                code="parse_failed",
                message="dokumenty celu, których parsowanie zakończyło się błędem",
                ids=failed,
            )
        )
    if contract.mismatches:
        issues.append(
            Issue(
                severity="critical",
                code="contract_mismatch",
                message="odpowiedzi API nie zgadzają się z wierszami źródła",
                ids=sorted({mismatch.id for mismatch in contract.mismatches}),
            )
        )
    return issues
