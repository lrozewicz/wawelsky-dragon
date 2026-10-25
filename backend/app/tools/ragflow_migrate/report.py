"""Raport z biegu migracji: JSON i Markdown (kontrakt §2, WP E4-6a)."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.tools.ragflow_migrate.stages.base import Issue, StageInventory, StageResult

VERSION = 1


@dataclass
class Report:
    """Zbiór inwentarzy (``plan``) albo wyników (``run``); bez sekretów."""

    mode: Literal["plan", "run"]
    dry_run: bool
    started_at: str
    finished_at: str
    inventories: list[StageInventory]
    results: list[StageResult]

    def has_critical(self) -> bool:
        """True, gdy jakakolwiek uwaga ma wagę ``critical``."""
        return any(issue.severity == "critical" for issue in self._issues())

    def to_json(self) -> dict[str, Any]:
        """Raport jako JSON-owalny słownik (tylko id i liczniki)."""
        return {
            "version": VERSION,
            "mode": self.mode,
            "dry_run": self.dry_run,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "inventories": [
                {
                    "stage": inv.stage,
                    "source_counts": dict(inv.source_counts),
                    "not_migrated": dict(inv.not_migrated),
                    "issues": [_issue_json(issue) for issue in inv.issues],
                }
                for inv in self.inventories
            ],
            "results": [
                {
                    "stage": res.stage,
                    "source_count": res.source_count,
                    "created": res.created,
                    "updated": res.updated,
                    "skipped": res.skipped,
                    "target_count": res.target_count,
                    "issues": [_issue_json(issue) for issue in res.issues],
                }
                for res in self.results
            ],
        }

    def to_markdown(self) -> str:
        """Raport jako Markdown (te same dane co JSON, czytelne dla człowieka)."""
        mode = f"{self.mode}{' (dry-run)' if self.dry_run else ''}"
        lines = [
            f"# Migracja RAGFlow → WD — {mode}",
            "",
            f"- start: {self.started_at}",
            f"- koniec: {self.finished_at}",
            f"- uwagi krytyczne: {'tak' if self.has_critical() else 'nie'}",
            "",
        ]
        lines += self._inventory_table()
        lines += self._result_table()
        lines += self._issue_table()
        return "\n".join(lines) + "\n"

    def _issues(self) -> list[Issue]:
        return [i for inv in self.inventories for i in inv.issues] + [
            i for res in self.results for i in res.issues
        ]

    def _inventory_table(self) -> list[str]:
        if not self.inventories:
            return []
        lines = [
            "## Inwentarz",
            "",
            "| etap | źródło | nieprzenoszone | uwagi |",
            "|---|---|---|---|",
        ]
        for inv in self.inventories:
            lines.append(
                f"| {inv.stage} | {_counts(inv.source_counts)} | {_counts(inv.not_migrated)}"
                f" | {len(inv.issues)} |"
            )
        return [*lines, ""]

    def _result_table(self) -> list[str]:
        if not self.results:
            return []
        lines = [
            "## Wyniki",
            "",
            "| etap | źródło | nowe | zmienione | pominięte | w celu | uwagi |",
            "|---|---|---|---|---|---|---|",
        ]
        for res in self.results:
            lines.append(
                f"| {res.stage} | {res.source_count} | {res.created} | {res.updated}"
                f" | {res.skipped} | {res.target_count} | {len(res.issues)} |"
            )
        return [*lines, ""]

    def _issue_table(self) -> list[str]:
        issues = self._issues()
        if not issues:
            return []
        lines = ["## Uwagi", "", "| waga | kod | komunikat | id |", "|---|---|---|---|"]
        for issue in issues:
            ids = ", ".join(issue.ids)
            lines.append(f"| {issue.severity} | {issue.code} | {issue.message} | {ids} |")
        return [*lines, ""]


def write_named(
    prefix: str,
    payload: dict[str, Any],
    markdown: str,
    directory: Path,
    finished_at: str,
) -> tuple[Path, Path]:
    """Zapisuje ``<prefix>-<stamp>.json`` i ``.md``; zwraca (json, markdown)."""
    directory.mkdir(parents=True, exist_ok=True)
    stamp = _stamp(finished_at)
    json_path = directory / f"{prefix}-{stamp}.json"
    md_path = directory / f"{prefix}-{stamp}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")
    return json_path, md_path


def write_report(report: Report, directory: Path) -> tuple[Path, Path]:
    """Zapisuje raport biegu migracji (``migration-report-…``); zwraca (json, markdown)."""
    return write_named(
        "migration-report",
        report.to_json(),
        report.to_markdown(),
        directory,
        report.finished_at,
    )


def _issue_json(issue: Issue) -> dict[str, Any]:
    return {
        "severity": issue.severity,
        "code": issue.code,
        "message": issue.message,
        "ids": list(issue.ids),
    }


def _counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{name}={count}" for name, count in sorted(counts.items())) or "—"


def _stamp(finished_at: str) -> str:
    """``2026-01-02T03:04:05Z`` → ``20260102T030405Z``."""
    return finished_at.replace("-", "").replace(":", "")
