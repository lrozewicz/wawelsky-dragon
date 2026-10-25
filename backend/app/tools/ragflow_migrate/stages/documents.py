"""Etap ``documents``: ``file``/``document``/``file2document`` → tabele celu.

Kontrakt WP E4-6b1 §5 i §6. Etap czyta źródło **raz** (fazy dostają gotowe wiersze), a fazy
piszą w tej samej sesji; wynik etapu to suma faz. Fazy: ``files`` (T4a), ``documents`` (T4b)
i ``file2document`` (T4c); ``plan`` wg §7 liczy inwentarz i sprawdza bloby źródła.
"""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.tools.ragflow_migrate.blobs import BlobEntry, SourceFiles, plan_blobs
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import (
    Issue,
    PhaseResult,
    RunContext,
    StageInventory,
    StageResult,
)
from app.tools.ragflow_migrate.stages.doc_docs import (
    BLOB_MISSING,
    BLOB_SIZE_MISMATCH,
    run_documents,
)
from app.tools.ragflow_migrate.stages.doc_files import run_files
from app.tools.ragflow_migrate.stages.doc_links import run_links

#: Tabele źródłowe etapu (liczniki inwentarza).
SOURCE_TABLES: tuple[str, ...] = ("file", "document", "file2document")

#: Tabela źródłowa mapowań elementów SharePoint → dokumenty (CONTRACT §7, WP E4-6c).
SOURCE_MAPPINGS = "ai_hub_integration_file_mappings"

#: Kod Issue krytycznej: brak ``--src-files-dir`` tam, gdzie bloby są potrzebne.
SRC_FILES_DIR_MISSING = "src_files_dir_missing"

#: Kod Issue informacyjnej z licznikami blobów (kontrakt §6).
BLOBS = "blobs"


def _needs_blobs(
    files: Sequence[Mapping[str, Any]], documents: Sequence[Mapping[str, Any]]
) -> bool:
    """Prawda, gdy etap napotka dokument albo plik nie-folder (czyli cokolwiek do skopiowania)."""
    return bool(documents) or any(_text(row.get("type")) != "folder" for row in files)


def _text(value: Any) -> str:
    """Wartość kolumny jako tekst; ``None`` → ``''``."""
    return "" if value is None else str(value)


async def _present_document_ids(
    session: AsyncSession, documents: Sequence[Mapping[str, Any]]
) -> set[str]:
    """Id dokumentów źródła obecne w ``documents`` celu po fazie (dla E4-6b2, kontrakt §6)."""
    ids = [_text(row.get("id")) for row in documents]
    if not ids:
        return set()
    statement = text("SELECT id FROM documents WHERE id IN :ids").bindparams(
        bindparam("ids", expanding=True)
    )
    result = await session.execute(statement, {"ids": ids})
    return {str(value) for value in result.scalars().all()}


def _document_source_refs(src: Source) -> dict[str, str]:
    """Id dokumentu → ``source_ref`` z mapowań SharePoint (CONTRACT §7, WP E4-6c).

    Klucz elementu to ``"<integration_id>:<drive_id>:<external_item_id>"``. Bierzemy pierwszy
    wiersz mapowania w kolejności ``(integration_id, drive_id, external_item_id)``, gdy kilka
    mapowań wskazuje ten sam dokument. Brak tabeli mapowań w źródle → pusta mapa (etap zachowuje
    się jak przed zmianą).
    """
    if not src.has_table(SOURCE_MAPPINGS):
        return {}
    rows = sorted(
        src.rows(SOURCE_MAPPINGS),
        key=lambda row: (
            int(row["integration_id"]),
            _text(row["drive_id"]),
            _text(row["external_item_id"]),
        ),
    )
    refs: dict[str, str] = {}
    for row in rows:
        refs.setdefault(
            _text(row["ragflow_document_id"]),
            ":".join(
                (
                    _text(row["integration_id"]),
                    _text(row["drive_id"]),
                    _text(row["external_item_id"]),
                )
            ),
        )
    return refs


def _owner_ids(entry: BlobEntry) -> list[str]:
    """Id właścicieli wpisu bez prefiksu (``document:``/``file:``), bez powtórzeń, w kolejności."""
    ids: list[str] = []
    for owner in entry.owners:
        owner_id = owner.split(":", 1)[1]
        if owner_id not in ids:
            ids.append(owner_id)
    return ids


def _plan_issues(
    files: Sequence[Mapping[str, Any]],
    documents: Sequence[Mapping[str, Any]],
    links: Sequence[Mapping[str, Any]],
    src_files_dir: Path,
) -> list[Issue]:
    """Uwagi ``plan`` o blobach źródła: ``blob_missing`` / ``blob_size_mismatch`` (kontrakt §7)."""
    source = SourceFiles(src_files_dir)
    missing: list[str] = []
    mismatched: list[str] = []
    for entry in plan_blobs(files, documents, links).entries.values():
        info = source.inspect(entry.ref)
        if info is None:
            missing.extend(_owner_ids(entry))
        elif info.size != entry.expected_size:
            mismatched.extend(_owner_ids(entry))
    issues: list[Issue] = []
    if missing:
        issues.append(
            Issue(
                severity="warning",
                code=BLOB_MISSING,
                message=(
                    f"brak bloba w źródle dla {len(missing)} id — wiersze przeniesione bez kopii"
                ),
                ids=missing,
            )
        )
    if mismatched:
        issues.append(
            Issue(
                severity="warning",
                code=BLOB_SIZE_MISMATCH,
                message=(
                    f"rozmiar bloba niezgodny z deklarowanym w źródle dla {len(mismatched)} id"
                ),
                ids=mismatched,
            )
        )
    return issues


def _blob_issue(counters: Mapping[str, int]) -> Issue:
    """Issue ``info`` z licznikami blobów po wpisach (kontrakt §6)."""
    return Issue(
        severity="info",
        code=BLOBS,
        message=(
            f"bloby: skopiowane {counters['copied']}, bez zmian {counters['unchanged']},"
            f" brak {counters['missing']}, zły rozmiar {counters['size_mismatch']}"
        ),
        ids=[],
    )


class DocumentsStage:
    """Pliki i dokumenty źródła → ``files``/``documents``/``file2document`` (kontrakt §5)."""

    name = "documents"

    def plan(self, src: Source, ctx: RunContext) -> StageInventory:
        """Inwentarz etapu wg kontraktu §7: liczniki tabel źródłowych i problemy z blobami.

        Bez ``--src-files-dir`` zgłaszamy tylko ``warning`` ``src_files_dir_missing``. Plan
        niczego nie pisze: ``plan_blobs`` i ``SourceFiles.inspect`` czytają wyłącznie źródło.
        """
        files = src.rows("file")
        documents = src.rows("document")
        links = src.rows("file2document")
        counts = {"file": len(files), "document": len(documents), "file2document": len(links)}
        if ctx.src_files_dir is None:
            issues = [
                Issue(
                    severity="warning",
                    code=SRC_FILES_DIR_MISSING,
                    message="brak --src-files-dir — plan nie sprawdza blobów źródła",
                    ids=[],
                )
            ]
        else:
            issues = _plan_issues(files, documents, links, ctx.src_files_dir)
        return StageInventory(stage=self.name, source_counts=counts, issues=issues, not_migrated={})

    def _total(self, results: Sequence[PhaseResult], issues_extra: Sequence[Issue]) -> StageResult:
        """Suma faz: liczniki sumowane, uwagi w kolejności faz i ``issues_extra`` (§5)."""
        return StageResult(
            stage=self.name,
            source_count=sum(result.source_count for result in results),
            created=sum(result.created for result in results),
            updated=sum(result.updated for result in results),
            skipped=sum(result.skipped for result in results),
            target_count=sum(result.target_count for result in results),
            issues=[issue for result in results for issue in result.issues] + list(issues_extra),
        )

    async def run(self, src: Source, session: AsyncSession, ctx: RunContext) -> StageResult:
        """Fazy ``files``, ``documents`` i ``file2document``; bez ``--src-files-dir`` nic nie pisze.

        Brak ``--src-files-dir`` przy choćby jednym dokumencie/pliku nie-folderze → jedno
        Issue ``critical`` i zero zapisów (rollback całego biegu robi runner).

        ``--since`` (kontrakt §2) zawęża wiersze do upsertu w każdej z trzech faz, ale plan
        blobów i ``ctx.shared['document_ids']`` liczymy z PEŁNYCH tabel: plan z wierszy po
        filtrze wskazałby inne miejsce docelowe i inne źródło bloba dla zmienionego dokumentu.
        """
        files = src.rows("file")
        documents = src.rows("document")
        links = src.rows("file2document")
        if ctx.src_files_dir is None and _needs_blobs(files, documents):
            return self._total(
                [],
                [
                    Issue(
                        severity="critical",
                        code=SRC_FILES_DIR_MISSING,
                        message=(
                            "brak --src-files-dir, a źródło ma dokumenty albo pliki nie-folderowe"
                            " — etap nie pisze żadnej tabeli"
                        ),
                        ids=[],
                    )
                ],
            )
        plan = plan_blobs(files, documents, links)
        source_refs = _document_source_refs(src)
        ctx.shared["documents_blobs"] = {
            "copied": 0,
            "unchanged": 0,
            "missing": 0,
            "size_mismatch": 0,
        }
        ctx.shared["_blob_counted"] = set()  # wpisy planu już policzone w tym biegu (§6)
        ctx.shared.setdefault("new_blob_keys", [])
        now_ms = ctx.clock.now_ms()
        # Wiersze do upsertu: przy `--since` tylko zmienione; drzewo plików (`files`) zostaje pełne.
        since = ctx.since_ms
        changed_files = files if since is None else src.rows_changed("file", since)
        changed_documents = documents if since is None else src.rows_changed("document", since)
        changed_links = links if since is None else src.rows_changed("file2document", since)
        results = [
            await run_files(changed_files, files, session, ctx, plan, now_ms),
            await run_documents(changed_documents, session, ctx, plan, now_ms, source_refs),
            await run_links(changed_links, session, ctx, now_ms),
        ]
        ctx.shared["document_ids"] = await _present_document_ids(session, documents)
        return self._total(results, [_blob_issue(ctx.shared["documents_blobs"])])
