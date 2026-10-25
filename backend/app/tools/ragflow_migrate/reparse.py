"""Komenda ``reparse``: ponowne kolejkowanie parsowania blobów (kontrakt E4-6c §3.1).

Kolejkowanie wyłącznie przez ``Container.ingest.enqueue_parse`` (kontrakt §3.1) — żadnego
bezpośredniego INSERT-u do ``tasks``. Dokument kwalifikowany = ``run = '0'`` **i**
``content_hash <> ''``; brak bloba (``content_hash = ''``) i inne stany ``run`` trafiają
do raportu jako pominięte.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.container import Container
from app.core.timeutil import iso, now_ms
from app.db.repositories import task_lookup

VERSION = 1
COMMAND = "reparse"

#: Maksymalna liczba dokumentów jednego datasetu w jednym ``enqueue_parse`` (kontrakt §3.1).
BATCH_SIZE = 100

#: Stan ``tasks`` dokumentu bez zadania queued/running, ale z ``run='0'`` → traktowany jak '1'.
ACTIVE_RUN = "1"

_SELECT_DOCUMENTS = text(
    "SELECT id, dataset_id, run, content_hash FROM documents ORDER BY dataset_id, id"
)
_SELECT_DOCUMENTS_IN = text(
    "SELECT id, dataset_id, run, content_hash FROM documents"
    " WHERE dataset_id IN :dataset_ids ORDER BY dataset_id, id"
).bindparams(bindparam("dataset_ids", expanding=True))

_SELECT_DATASET_IDS = text("SELECT id FROM datasets ORDER BY id")
_SELECT_KNOWN_DATASETS = text("SELECT id FROM datasets WHERE id IN :ids").bindparams(
    bindparam("ids", expanding=True)
)


@dataclass
class ReparseReport:
    """Raport ``reparse`` (kontrakt §3.1); bez sekretów."""

    started_at: str
    finished_at: str
    priority: int
    datasets: list[str]
    queued_ids: list[str]
    skipped_no_blob: list[str]
    skipped_state: dict[str, list[str]]

    def to_json(self) -> dict[str, Any]:
        """JSON raportu dokładnie wg §3.1 (``queued`` = długość ``queued_ids``)."""
        return {
            "version": VERSION,
            "command": COMMAND,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "priority": self.priority,
            "datasets": list(self.datasets),
            "queued": len(self.queued_ids),
            "queued_ids": list(self.queued_ids),
            "skipped_no_blob": list(self.skipped_no_blob),
            "skipped_state": {run: list(ids) for run, ids in self.skipped_state.items()},
        }

    def to_markdown(self) -> str:
        """Markdown raportu: nagłówek, tabela liczników i listy id."""
        lines = [
            "# Reparse RAGFlow → WD",
            "",
            f"- start: {self.started_at}",
            f"- koniec: {self.finished_at}",
            f"- priorytet: {self.priority}",
            f"- datasety: {_joined(self.datasets)}",
            "",
            "| miara | liczba |",
            "|---|---|",
            f"| zakolejkowane | {len(self.queued_ids)} |",
            f"| bez bloba | {len(self.skipped_no_blob)} |",
        ]
        for run in sorted(self.skipped_state):
            lines.append(f"| pominięte (run={run}) | {len(self.skipped_state[run])} |")
        lines += ["", "## Zakolejkowane (queued_ids)", "", *_bullets(self.queued_ids)]
        lines += ["", "## Bez bloba (skipped_no_blob)", "", *_bullets(self.skipped_no_blob)]
        for run in sorted(self.skipped_state):
            lines += [
                "",
                f"## Pominięte, run={run} (skipped_state)",
                "",
                *_bullets(self.skipped_state[run]),
            ]
        return "\n".join(lines) + "\n"


def _joined(ids: Sequence[str]) -> str:
    """Lista id jedną linią albo ``—``, gdy pusta."""
    return ", ".join(ids) if ids else "—"


def _bullets(ids: Sequence[str]) -> list[str]:
    """Lista id jako punkty Markdown albo ``—``, gdy pusta."""
    return [f"- {doc_id}" for doc_id in ids] or ["—"]


async def run_reparse(
    settings: Settings, datasets: list[str] | None, priority: int
) -> ReparseReport:
    """Kolejkuje dokumenty datasetów do parsowania (``datasets=None`` = wszystkie).

    ``datasets=[]`` jest błędem (pusta lista ≠ all); nieznane id datasetu → ``ValueError``.
    """
    if datasets is not None and not datasets:
        raise ValueError("pusta lista datasetów (użyj all, by objąć wszystkie)")
    started_at = iso(now_ms())
    container = Container(settings)
    await container.start()
    try:
        rows, scope, active = await _select(container, datasets)
        queued_ids: list[str] = []
        by_dataset: dict[str, list[str]] = {}
        skipped_no_blob: list[str] = []
        skipped_state: dict[str, list[str]] = {}
        for row in rows:
            document_id = str(row["id"])
            state = str(row["run"])
            if not row["content_hash"]:
                skipped_no_blob.append(document_id)
            elif state != "0":
                skipped_state.setdefault(state, []).append(document_id)
            elif document_id in active:
                skipped_state.setdefault(ACTIVE_RUN, []).append(document_id)
            else:
                queued_ids.append(document_id)
                by_dataset.setdefault(str(row["dataset_id"]), []).append(document_id)
        for dataset_id in sorted(by_dataset):
            ids = by_dataset[dataset_id]
            for start in range(0, len(ids), BATCH_SIZE):
                batch = ids[start : start + BATCH_SIZE]
                await container.ingest.enqueue_parse(batch, priority=priority)
        return ReparseReport(
            started_at=started_at,
            finished_at=iso(now_ms()),
            priority=priority,
            datasets=scope,
            queued_ids=queued_ids,
            skipped_no_blob=skipped_no_blob,
            skipped_state=skipped_state,
        )
    finally:
        await container.aclose()


async def _select(
    container: Container, datasets: list[str] | None
) -> tuple[list[dict[str, Any]], list[str], set[str]]:
    """Wiersze dokumentów objętych biegiem, posortowane id datasetów i aktywne zadania.

    ``datasets=None`` → wszystkie datasety celu; inaczej każde podane id musi istnieć
    w ``datasets`` (inaczej ``ValueError``).
    """
    sessionmaker = container.sessionmaker
    if sessionmaker is None:
        raise RuntimeError("container not started")
    async with sessionmaker() as session:
        rows, scope = await _scope_rows(session, datasets)
        candidates = [str(row["id"]) for row in rows if row["content_hash"] and row["run"] == "0"]
        active = await task_lookup.active_parse_documents(session, candidates)
    return rows, scope, active


async def _scope_rows(
    session: AsyncSession, datasets: list[str] | None
) -> tuple[list[dict[str, Any]], list[str]]:
    """Dokumenty w zakresie (wiersze) i posortowana lista objętych id datasetów."""
    if datasets is None:
        result = await session.execute(_SELECT_DATASET_IDS)
        scope = [str(value) for value in result.scalars().all()]
        result = await session.execute(_SELECT_DOCUMENTS)
        return [dict(row) for row in result.mappings().all()], scope
    scope = sorted({str(dataset_id) for dataset_id in datasets})
    known = {
        str(value)
        for value in (await session.execute(_SELECT_KNOWN_DATASETS, {"ids": scope})).scalars().all()
    }
    missing = next((dataset_id for dataset_id in scope if dataset_id not in known), None)
    if missing is not None:
        raise ValueError(f"Nieznany dataset: {missing}")
    result = await session.execute(_SELECT_DOCUMENTS_IN, {"dataset_ids": scope})
    return [dict(row) for row in result.mappings().all()], scope
