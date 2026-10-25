"""Zbieranie stanu parsowania dokumentów w celu (kontrakt E4-6c §5).

Stan czytamy wyłącznie z tabeli ``documents`` celu: liczniki wg ``run`` i suma ``chunk_count``
w jednym zapytaniu agregującym, a dokumenty nieudane (``run = '4'``) osobnym zapytaniem.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.tools.ragflow_migrate.verify_types import ParseFailure, ParseSummary

#: Długość komunikatu o nieudanym parsowaniu (kontrakt §3.2: ``reason`` obcięte do 200 znaków).
REASON_LIMIT = 200

#: Liczniki wg ``run`` i suma kawałków — jedna agregacja, kolumny jawne (kontrakt §5).
_SELECT_PARSE_COUNTS = text(
    "SELECT"
    " COALESCE(SUM(CASE WHEN run = '0' THEN 1 ELSE 0 END), 0) AS unstarted,"
    " COALESCE(SUM(CASE WHEN run = '1' THEN 1 ELSE 0 END), 0) AS running,"
    " COALESCE(SUM(CASE WHEN run = '2' THEN 1 ELSE 0 END), 0) AS cancelled,"
    " COALESCE(SUM(CASE WHEN run = '3' THEN 1 ELSE 0 END), 0) AS done,"
    " COALESCE(SUM(CASE WHEN run = '4' THEN 1 ELSE 0 END), 0) AS failed,"
    " COALESCE(SUM(chunk_count), 0) AS chunks_total"
    " FROM documents"
)

#: Dokumenty nieudane: ``reason`` to ``error``, a gdy puste — ``progress_msg`` (kontrakt §3.2).
_SELECT_PARSE_FAILURES = text(
    "SELECT id, COALESCE(NULLIF(error, ''), progress_msg, '') AS reason"
    " FROM documents WHERE run = '4' ORDER BY id"
)


async def collect_parse(session: AsyncSession) -> ParseSummary:
    """Stan parsowania (liczniki ``documents.run``, ``chunk_count``, błędy) — kontrakt §5."""
    counts = (await session.execute(_SELECT_PARSE_COUNTS)).mappings().one()
    failure_rows = (await session.execute(_SELECT_PARSE_FAILURES)).mappings().all()
    return ParseSummary(
        unstarted=int(counts["unstarted"]),
        running=int(counts["running"]),
        cancelled=int(counts["cancelled"]),
        done=int(counts["done"]),
        failed=int(counts["failed"]),
        chunks_total=int(counts["chunks_total"]),
        failures=[
            ParseFailure(document_id=str(row["id"]), reason=str(row["reason"] or "")[:REASON_LIMIT])
            for row in failure_rows
        ],
    )
