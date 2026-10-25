"""Typy raportu ``verify`` — kształty dosłownie z kontraktu E4-6c §3.2."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from app.tools.ragflow_migrate.stages.base import Issue

VERSION = 1
COMMAND = "verify"

#: Tabele, których brak wierszy w celu jest rozbieżnością krytyczną (kontrakt §3.2).
CRITICAL_TABLES = frozenset(
    {"users", "chats", "assistant_access", "integrations", "datasets", "documents", "api_keys"}
)


@dataclass
class CountEntry:
    """Porównanie liczby wierszy jednej tabeli: źródło vs cel."""

    # tabela WD: users, datasets, documents, files, chats, chat_sessions,
    # assistant_access, api_keys, integrations
    table: str
    # liczba wierszy źródła (po wyłączeniu osieroconych dla chat_sessions/assistant_access)
    source: int
    target: int  # liczba wierszy celu (te same kryteria)
    missing_ids: list[str]  # id źródła nieobecne w celu
    critical: bool  # True gdy missing_ids niepuste i table in CRITICAL_TABLES


@dataclass
class ParseFailure:
    """Dokument, którego parsowanie w celu się nie udało."""

    document_id: str
    reason: str  # documents.error albo progress_msg, obcięte do 200 znaków


@dataclass
class ParseSummary:
    """Stan parsowania dokumentów w celu (liczniki ``documents.run``)."""

    unstarted: int  # documents.run = '0'
    running: int  # '1'
    cancelled: int  # '2'
    done: int  # '3'
    failed: int  # '4'
    chunks_total: int  # SUM(documents.chunk_count)
    failures: list[ParseFailure]


@dataclass
class ContractMismatch:
    """Jedna niezgodność próbki kontraktowej API."""

    kind: Literal["chat", "session"]
    id: str
    field: str  # "missing", "name", "datasets", "message_count"
    expected: str
    actual: str


@dataclass
class ContractSample:
    """Wynik próbki kontraktowej API (kontrakt §6)."""

    chats_checked: int
    sessions_checked: int
    mismatches: list[ContractMismatch]
    skipped_no_key: list[str]  # id czatów, których właściciel nie ma klucza API w źródle


@dataclass
class VerifyReport:
    """Raport ``verify``: liczniki, pliki, modele, parsowanie i Issues (kontrakt §3.2)."""

    started_at: str
    finished_at: str
    counts: list[CountEntry]
    missing_blob: list[str]  # documents.error LIKE 'migration: blob missing%'
    size_mismatch: list[str]  # documents.error LIKE 'migration: blob size mismatch%'
    embedding_mismatch_chats: list[str]  # czaty, których datasety mają różne embedding_model
    # 'llm_name@factory' użyte w źródle (dialog/knowledgebase), którym nie odpowiada
    # żaden model w celu ani w model-map
    unmapped_models: list[str]
    orphan_access: list[str]  # "<email>:<dialog_id>" wiersze access bez dialogu w źródle
    parse: ParseSummary
    contract: ContractSample
    issues: list[Issue]  # Issue z stages/base.py

    def has_critical(self) -> bool:
        """True, gdy jakakolwiek uwaga ma wagę ``critical``."""
        return any(issue.severity == "critical" for issue in self.issues)

    def to_json(self) -> dict[str, Any]:
        """JSON raportu wg §3.2 — wyłącznie id i liczniki, bez haseł, tokenów i kluczy."""
        return {
            "version": VERSION,
            "command": COMMAND,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "ok": not self.has_critical(),
            "counts": [
                {
                    "table": entry.table,
                    "source": entry.source,
                    "target": entry.target,
                    "missing_ids": list(entry.missing_ids),
                    "critical": entry.critical,
                }
                for entry in self.counts
            ],
            "files": {
                "missing_blob": list(self.missing_blob),
                "size_mismatch": list(self.size_mismatch),
            },
            "embedding_mismatch_chats": list(self.embedding_mismatch_chats),
            "unmapped_models": list(self.unmapped_models),
            "orphan_access": list(self.orphan_access),
            "parse": {
                "unstarted": self.parse.unstarted,
                "running": self.parse.running,
                "cancelled": self.parse.cancelled,
                "done": self.parse.done,
                "failed": self.parse.failed,
                "chunks_total": self.parse.chunks_total,
                "failures": [
                    {"document_id": failure.document_id, "reason": failure.reason}
                    for failure in self.parse.failures
                ],
            },
            "contract_sample": {
                "chats_checked": self.contract.chats_checked,
                "sessions_checked": self.contract.sessions_checked,
                "ok": not self.contract.mismatches,
                "mismatches": [
                    {
                        "kind": mismatch.kind,
                        "id": mismatch.id,
                        "field": mismatch.field,
                        "expected": mismatch.expected,
                        "actual": mismatch.actual,
                    }
                    for mismatch in self.contract.mismatches
                ],
                "skipped_no_key": list(self.contract.skipped_no_key),
            },
            "issues": [
                {
                    "severity": issue.severity,
                    "code": issue.code,
                    "message": issue.message,
                    "ids": list(issue.ids),
                }
                for issue in self.issues
            ],
        }

    def to_markdown(self) -> str:
        """Markdown raportu: nagłówek, tabela liczników, sekcje szczegółów i tabela uwag."""
        lines = [
            "# Verify RAGFlow → WD",
            "",
            f"- start: {self.started_at}",
            f"- koniec: {self.finished_at}",
            f"- uwagi krytyczne: {'tak' if self.has_critical() else 'nie'}",
            "",
            "## Liczniki",
            "",
            "| tabela | źródło | cel | brakujące | krytyczne |",
            "|---|---|---|---|---|",
        ]
        for entry in self.counts:
            lines.append(
                f"| {entry.table} | {entry.source} | {entry.target}"
                f" | {len(entry.missing_ids)} | {'tak' if entry.critical else 'nie'} |"
            )
        lines += ["", "## Brakujące id", "", *_missing_bullets(self.counts)]
        lines += [
            "",
            "## Pliki",
            "",
            f"- brak bloba: {_joined(self.missing_blob)}",
            f"- niezgodny rozmiar: {_joined(self.size_mismatch)}",
        ]
        lines += ["", "## Modele bez odpowiednika w celu", "", *_bullets(self.unmapped_models)]
        lines += ["", "## Osierocone dostępy", "", *_bullets(self.orphan_access)]
        lines += [
            "",
            "## Czaty z różnym embeddingiem",
            "",
            *_bullets(self.embedding_mismatch_chats),
        ]
        lines += [
            "",
            "## Parsowanie",
            "",
            f"- nierozpoczęte: {self.parse.unstarted}",
            f"- w toku: {self.parse.running}",
            f"- anulowane: {self.parse.cancelled}",
            f"- zakończone: {self.parse.done}",
            f"- nieudane: {self.parse.failed}",
            f"- kawałki: {self.parse.chunks_total}",
            "",
            "### Nieudane dokumenty",
            "",
            *_bullets(
                [f"{failure.document_id}: {failure.reason}" for failure in self.parse.failures]
            ),
        ]
        lines += [
            "",
            "## Próbka kontraktowa",
            "",
            f"- czaty sprawdzone: {self.contract.chats_checked}",
            f"- sesje sprawdzone: {self.contract.sessions_checked}",
            f"- czaty bez klucza właściciela: {_joined(self.contract.skipped_no_key)}",
            "",
            "### Niezgodności",
            "",
            *_bullets(
                [
                    f"{mismatch.kind} {mismatch.id} {mismatch.field}:"
                    f" oczekiwane {mismatch.expected!r}, jest {mismatch.actual!r}"
                    for mismatch in self.contract.mismatches
                ]
            ),
        ]
        lines += ["", "## Uwagi", "", "| waga | kod | komunikat | id |", "|---|---|---|---|"]
        for issue in self.issues:
            lines.append(
                f"| {issue.severity} | {issue.code} | {issue.message} | {', '.join(issue.ids)} |"
            )
        return "\n".join(lines) + "\n"


def _joined(ids: Sequence[str]) -> str:
    """Lista wartości jedną linią albo ``—``, gdy pusta."""
    return ", ".join(ids) if ids else "—"


def _bullets(values: Sequence[str]) -> list[str]:
    """Lista wartości jako punkty Markdown albo ``—``, gdy pusta."""
    return [f"- {value}" for value in values] or ["—"]


def _missing_bullets(counts: Sequence[CountEntry]) -> list[str]:
    """Linie ``tabela: id, id`` dla wpisów liczników z niepustym ``missing_ids``."""
    lines = [
        f"- {entry.table}: {_joined(entry.missing_ids)}" for entry in counts if entry.missing_ids
    ]
    return lines or ["—"]
