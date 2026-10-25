"""Testy raportu ``verify`` bez bazy: kształt JSON/Markdown i uwagi wg kontraktu E4-6c §3.2."""

import json

from app.tools.ragflow_migrate.stages.base import Issue
from app.tools.ragflow_migrate.verify import _issues
from app.tools.ragflow_migrate.verify_counts import CountsPart
from app.tools.ragflow_migrate.verify_types import (
    ContractMismatch,
    ContractSample,
    CountEntry,
    ParseFailure,
    ParseSummary,
    VerifyReport,
)

STARTED_AT = "2026-01-02T03:04:05Z"
FINISHED_AT = "2026-01-02T03:04:06Z"


def _report(issues: list[Issue]) -> VerifyReport:
    """Raport z jedną brakującą tabelą krytyczną i pełnymi sekcjami szczegółów."""
    return VerifyReport(
        started_at=STARTED_AT,
        finished_at=FINISHED_AT,
        counts=[
            CountEntry(table="users", source=2, target=1, missing_ids=["u1"], critical=True),
            CountEntry(table="datasets", source=2, target=2, missing_ids=[], critical=False),
        ],
        missing_blob=["doc-blob"],
        size_mismatch=["doc-size"],
        embedding_mismatch_chats=["chat-embed"],
        unmapped_models=["llm@Factory"],
        orphan_access=["a@b.c:dialog-1"],
        parse=ParseSummary(
            unstarted=1,
            running=2,
            cancelled=3,
            done=4,
            failed=5,
            chunks_total=6,
            failures=[ParseFailure(document_id="doc-1", reason="błąd")],
        ),
        contract=ContractSample(
            chats_checked=1,
            sessions_checked=2,
            mismatches=[ContractMismatch("chat", "chat-1", "name", "oczekiwana", "inna")],
            skipped_no_key=["chat-2"],
        ),
        issues=issues,
    )


def test_to_json_keys_are_per_contract() -> None:
    payload = _report([]).to_json()

    assert sorted(payload) == [
        "command",
        "contract_sample",
        "counts",
        "embedding_mismatch_chats",
        "files",
        "finished_at",
        "issues",
        "ok",
        "orphan_access",
        "parse",
        "started_at",
        "unmapped_models",
        "version",
    ]
    assert payload["version"] == 1
    assert payload["command"] == "verify"
    assert payload["started_at"] == STARTED_AT
    assert payload["finished_at"] == FINISHED_AT


def test_to_json_count_entry_shape() -> None:
    payload = _report([]).to_json()

    assert payload["counts"] == [
        {
            "table": "users",
            "source": 2,
            "target": 1,
            "missing_ids": ["u1"],
            "critical": True,
        },
        {
            "table": "datasets",
            "source": 2,
            "target": 2,
            "missing_ids": [],
            "critical": False,
        },
    ]


def test_to_json_files_parse_and_contract_sections() -> None:
    payload = _report([]).to_json()

    assert payload["files"] == {"missing_blob": ["doc-blob"], "size_mismatch": ["doc-size"]}
    assert payload["embedding_mismatch_chats"] == ["chat-embed"]
    assert payload["unmapped_models"] == ["llm@Factory"]
    assert payload["orphan_access"] == ["a@b.c:dialog-1"]
    assert payload["parse"] == {
        "unstarted": 1,
        "running": 2,
        "cancelled": 3,
        "done": 4,
        "failed": 5,
        "chunks_total": 6,
        "failures": [{"document_id": "doc-1", "reason": "błąd"}],
    }
    assert payload["contract_sample"] == {
        "chats_checked": 1,
        "sessions_checked": 2,
        "ok": False,
        "mismatches": [
            {
                "kind": "chat",
                "id": "chat-1",
                "field": "name",
                "expected": "oczekiwana",
                "actual": "inna",
            }
        ],
        "skipped_no_key": ["chat-2"],
    }


def test_to_json_issues_and_ok_flag() -> None:
    warning = Issue("warning", "model_unmapped", "brak mapy", ["llm@Factory"])
    critical = Issue("critical", "count_missing", "brak 1 wierszy tabeli users w celu", ["u1"])

    assert _report([]).to_json()["ok"] is True
    assert _report([warning]).to_json()["ok"] is True
    payload = _report([warning, critical]).to_json()
    assert payload["ok"] is False
    assert payload["issues"] == [
        {
            "severity": "warning",
            "code": "model_unmapped",
            "message": "brak mapy",
            "ids": ["llm@Factory"],
        },
        {
            "severity": "critical",
            "code": "count_missing",
            "message": "brak 1 wierszy tabeli users w celu",
            "ids": ["u1"],
        },
    ]


def test_to_json_round_trips_through_dumps() -> None:
    payload = _report([]).to_json()

    assert json.loads(json.dumps(payload, ensure_ascii=False)) == payload


def test_to_markdown_has_header_counts_and_issue_table() -> None:
    critical = Issue("critical", "count_missing", "brak 1 wierszy tabeli users w celu", ["u1"])
    markdown = _report([critical]).to_markdown()

    assert markdown.startswith("# Verify RAGFlow → WD\n")
    assert "| users | 2 | 1 | 1 | tak |" in markdown
    assert "| datasets | 2 | 2 | 0 | nie |" in markdown
    assert "- users: u1" in markdown
    assert "## Parsowanie" in markdown
    assert "doc-1: błąd" in markdown
    assert "## Próbka kontraktowa" in markdown
    assert "chat-1 name" in markdown
    assert "| critical | count_missing | brak 1 wierszy tabeli users w celu | u1 |" in markdown


def test_to_markdown_without_details_uses_dash() -> None:
    report = VerifyReport(
        started_at=STARTED_AT,
        finished_at=FINISHED_AT,
        counts=[CountEntry(table="users", source=0, target=0, missing_ids=[], critical=False)],
        missing_blob=[],
        size_mismatch=[],
        embedding_mismatch_chats=[],
        unmapped_models=[],
        orphan_access=[],
        parse=ParseSummary(0, 0, 0, 0, 0, 0, []),
        contract=ContractSample(0, 0, [], []),
        issues=[],
    )
    markdown = report.to_markdown()

    assert "- brak bloba: —" in markdown
    assert markdown.endswith("|---|---|---|---|\n")
    assert "| users | 0 | 0 | 0 | nie |" in markdown


def _counts_part(**overrides: object) -> CountsPart:
    """Pusta część liczników z polami nadpisanymi w teście."""
    fields: dict[str, object] = {
        "counts": [],
        "missing_blob": [],
        "size_mismatch": [],
        "embedding_mismatch_chats": [],
        "unmapped_models": [],
        "orphan_access": [],
    }
    return CountsPart(**{**fields, **overrides})  # type: ignore[arg-type]


def test_issues_cover_every_section_of_the_contract() -> None:
    """Kody i wagi uwag wg §3.2 — także dla sekcji, których stuby T7 jeszcze nie wypełniają."""
    counts = _counts_part(
        counts=[
            CountEntry("users", 2, 1, ["u1"], critical=True),
            CountEntry("datasets", 2, 1, ["ds-1"], critical=False),
            CountEntry("chats", 2, 2, [], critical=False),
        ],
        missing_blob=["doc-blob"],
        size_mismatch=["doc-size"],
        embedding_mismatch_chats=["chat-embed"],
        unmapped_models=["llm@Factory"],
        orphan_access=["a@b.c:dialog-1"],
    )
    parse = ParseSummary(0, 0, 0, 0, 1, 0, [ParseFailure(document_id="doc-1", reason="błąd")])
    contract = ContractSample(
        chats_checked=1,
        sessions_checked=1,
        mismatches=[ContractMismatch("chat", "chat-1", "name", "oczekiwana", "inna")],
        skipped_no_key=[],
    )

    assert [
        (issue.severity, issue.code, issue.ids) for issue in _issues(counts, parse, contract)
    ] == [
        ("critical", "count_missing", ["u1"]),
        ("warning", "count_missing", ["ds-1"]),
        ("warning", "blob_missing", ["doc-blob"]),
        ("warning", "blob_size_mismatch", ["doc-size"]),
        ("warning", "chat_embedding_mismatch", ["chat-embed"]),
        ("warning", "model_unmapped", ["llm@Factory"]),
        ("warning", "access_orphan", ["a@b.c:dialog-1"]),
        ("warning", "parse_failed", ["doc-1"]),
        ("critical", "contract_mismatch", ["chat-1"]),
    ]


def test_issues_are_empty_without_findings() -> None:
    """Puste sekcje nie tworzą żadnej uwagi (czysty bieg może mieć zero uwag)."""
    assert (
        _issues(_counts_part(), ParseSummary(0, 0, 0, 0, 0, 0, []), ContractSample(0, 0, [], []))
        == []
    )
