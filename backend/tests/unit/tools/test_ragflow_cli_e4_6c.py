"""Testy rusztowania E4-6c: ``reparse``/``verify``/``diff``, ``--since``, typy (brief T1).

Bez bazy: komendy potrzebujące źródła/celu mają atrapy. ``reparse`` (T3), ``verify`` (T4)
i ``diff`` (T5) mają zaimplementowane ciała — tu sprawdzamy kształty ich raportów, okablowanie
CLI, kody wyjścia i gwarancje ``Source.rows_changed``.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings
from app.core.ids import UuidV7Generator
from app.core.timeutil import SystemClock
from app.tools.ragflow_migrate import cli
from app.tools.ragflow_migrate.diff import DiffReport, DiffTable
from app.tools.ragflow_migrate.model_map import ModelMap
from app.tools.ragflow_migrate.reparse import ReparseReport
from app.tools.ragflow_migrate.report import Report, write_named
from app.tools.ragflow_migrate.since import parse_since
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import Issue, RunContext
from app.tools.ragflow_migrate.verify_types import (
    CRITICAL_TABLES,
    ContractSample,
    CountEntry,
    ParseFailure,
    ParseSummary,
    VerifyReport,
)

FINISHED_AT = "2026-01-02T03:04:05Z"
MYSQL_DSN = "mysql://root@src-db:3307/rf_src"

#: ``2026-09-30T12:00:00Z`` w milisekundach epoki — wartość kontrolna kontraktu §1.
SINCE_MS_Z = 1790769600000
#: Kod wyjścia, gdy raport ma uwagi ``critical`` (kontrakt §1).
EXIT_CRITICAL = 2


@pytest.fixture
def wd_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """``Settings()`` w CLI musi przejść walidację — testy ustawiają ``WD_ENV=test``."""
    monkeypatch.setenv("WD_ENV", "test")


@pytest.fixture
def no_dsn_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Brak DSN w env — jak w bramkach ``plan``/``run``/``verify``."""
    monkeypatch.delenv(cli.ENV_SRC_MYSQL, raising=False)
    monkeypatch.setenv("WD_ENV", "test")


class FakeCursor:
    """Kursor-atrapa: notuje wykonane SQL-e i zwraca puste wyniki."""

    def __init__(self, conn: "FakeConnection") -> None:
        self._conn = conn

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False

    def execute(self, sql: str, params: object = None) -> None:
        self._conn.executed.append((sql, params))

    def fetchall(self) -> list[dict[str, object]]:
        return []

    def fetchone(self) -> dict[str, object]:
        return {"n": 0}


class FakeConnection:
    """Połączenie-atrapa źródła."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, object]] = []
        self.closed = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def close(self) -> None:
        self.closed = True


class FakeSource:
    """Atrapa źródła dla CLI: tylko ``close`` (CLI zamyka po błędzie)."""

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeReport:
    """Atrapa raportu komendy: ``to_json``/``to_markdown`` bez logiki (stuby są w T3/T4/T5)."""

    def __init__(self, command: str, finished_at: str, *, critical: bool = False) -> None:
        self.finished_at = finished_at
        self.critical = critical
        self._command = command

    def has_critical(self) -> bool:
        return self.critical

    def to_json(self) -> dict[str, Any]:
        return {"version": 1, "command": self._command, "ok": not self.critical}

    def to_markdown(self) -> str:
        return f"# {self._command}\n"


# --- since.py ---------------------------------------------------------------------------


def test_parse_since_utc_z() -> None:
    expected = int(datetime(2026, 9, 30, 12, tzinfo=UTC).timestamp() * 1000)
    assert parse_since("2026-09-30T12:00:00Z") == expected == SINCE_MS_Z


def test_parse_since_offset_is_east_of_utc() -> None:
    assert (
        parse_since("2026-09-30T12:00:00+02:00") == parse_since("2026-09-30T12:00:00Z") - 7_200_000
    )


def test_parse_since_naive_is_utc() -> None:
    assert parse_since("2026-09-30T12:00:00") == parse_since("2026-09-30T12:00:00Z")


def test_parse_since_date_only_is_midnight_utc() -> None:
    assert parse_since("2026-09-30") == int(datetime(2026, 9, 30, tzinfo=UTC).timestamp() * 1000)


@pytest.mark.parametrize(
    "text", ["wczoraj", "", "  ", "2026-13-01", "2026-09-30T25:00:00Z", "30.09.2026"]
)
def test_parse_since_rejects_bad_text(text: str) -> None:
    with pytest.raises(ValueError):
        parse_since(text)


# --- report.write_named -----------------------------------------------------------------


def test_write_named_names(tmp_path: Path) -> None:
    json_path, md_path = write_named("x-report", {"a": 1}, "# md", tmp_path, FINISHED_AT)

    assert json_path.name == "x-report-20260102T030405Z.json"
    assert md_path.name == "x-report-20260102T030405Z.md"
    assert json.loads(json_path.read_text(encoding="utf-8")) == {"a": 1}
    assert md_path.read_text(encoding="utf-8") == "# md"


def test_write_named_creates_directory(tmp_path: Path) -> None:
    json_path, md_path = write_named("y-report", {}, "# y", tmp_path / "out", FINISHED_AT)

    assert json_path.parent == tmp_path / "out"
    assert md_path.parent == tmp_path / "out"
    assert json_path.is_file() and md_path.is_file()


def test_write_report_keeps_migration_names(tmp_path: Path) -> None:
    report = Report(
        mode="plan",
        dry_run=False,
        started_at=FINISHED_AT,
        finished_at=FINISHED_AT,
        inventories=[],
        results=[],
    )
    json_path, md_path = cli.write_report(report, tmp_path)

    assert json_path.name == "migration-report-20260102T030405Z.json"
    assert md_path.name == "migration-report-20260102T030405Z.md"


# --- Source.rows_changed ----------------------------------------------------------------


def test_rows_changed_appends_update_time_param() -> None:
    conn = FakeConnection()
    src = Source(conn)

    assert src.rows_changed("user", SINCE_MS_Z) == []
    assert conn.executed == [
        ("SELECT * FROM `user` WHERE update_time >= %s", (SINCE_MS_Z,)),
    ]

    conn.executed.clear()
    assert src.rows_changed("user", 5, where="tenant_id = %s", params=["t1"]) == []
    assert conn.executed == [
        ("SELECT * FROM `user` WHERE tenant_id = %s AND update_time >= %s", ("t1", 5)),
    ]


def test_rows_changed_without_since_is_plain_rows() -> None:
    conn = FakeConnection()
    src = Source(conn)

    assert src.rows_changed("user", None) == []
    assert conn.executed == [("SELECT * FROM `user`", None)]


def test_rows_changed_rejects_bad_table() -> None:
    src = Source(None)  # połączenie nie jest dotykane — walidacja biegnie pierwsza
    with pytest.raises(ValueError):
        src.rows_changed("user; DROP TABLE x", 1)


# --- RunContext.since_ms ----------------------------------------------------------------


def test_run_context_since_ms_defaults_to_none() -> None:
    ctx = RunContext(
        model_map=ModelMap({}),
        settings=Settings(env="test"),
        clock=SystemClock(),
        id_gen=UuidV7Generator(),
        shared={},
    )
    assert ctx.since_ms is None
    assert ctx.dry_run is False


# --- verify_types -----------------------------------------------------------------------


def _verify_report(issues: list[Issue]) -> VerifyReport:
    return VerifyReport(
        started_at=FINISHED_AT,
        finished_at=FINISHED_AT,
        counts=[
            CountEntry(
                table="users",
                source=2,
                target=1,
                missing_ids=["u1"],
                critical=True,
            )
        ],
        missing_blob=["doc-blob"],
        size_mismatch=[],
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
            mismatches=[],
            skipped_no_key=["chat-1"],
        ),
        issues=issues,
    )


def test_verify_report_has_critical() -> None:
    warning = Issue("warning", "model_unmapped", "brak mapy", [])
    critical = Issue("critical", "count_missing", "tabela users", ["u1"])

    assert _verify_report([]).has_critical() is False
    assert _verify_report([warning]).has_critical() is False
    assert _verify_report([warning, critical]).has_critical() is True


def test_verify_report_json_and_markdown_are_ready() -> None:
    """``verify`` ma serializację od T4 (stuby zostały tylko w ``diff``)."""
    report = _verify_report([])
    assert report.to_json()["command"] == "verify"
    assert report.to_markdown().startswith("# Verify RAGFlow → WD")


def test_critical_tables_are_per_contract() -> None:
    assert sorted(CRITICAL_TABLES) == [
        "api_keys",
        "assistant_access",
        "chats",
        "datasets",
        "documents",
        "integrations",
        "users",
    ]


def test_reparse_report_json_and_diff_report_shape() -> None:
    reparse = ReparseReport(
        started_at=FINISHED_AT,
        finished_at=FINISHED_AT,
        priority=-1,
        datasets=["ds-1"],
        queued_ids=["doc-1"],
        skipped_no_blob=["doc-2"],
        skipped_state={"1": ["doc-3"]},
    )
    assert (reparse.priority, reparse.datasets, reparse.skipped_state) == (
        -1,
        ["ds-1"],
        {"1": ["doc-3"]},
    )
    assert reparse.to_json() == {
        "version": 1,
        "command": "reparse",
        "started_at": FINISHED_AT,
        "finished_at": FINISHED_AT,
        "priority": -1,
        "datasets": ["ds-1"],
        "queued": 1,
        "queued_ids": ["doc-1"],
        "skipped_no_blob": ["doc-2"],
        "skipped_state": {"1": ["doc-3"]},
    }
    assert "doc-1" in reparse.to_markdown()

    table = DiffTable(table="users", column="update_time", changed=2, ids=["u1"], truncated=False)
    diff = DiffReport(
        since="2026-09-30T12:00:00Z",
        since_ms=SINCE_MS_Z,
        started_at=FINISHED_AT,
        finished_at=FINISHED_AT,
        tables=[table],
    )
    assert diff.tables == [table]
    assert diff.to_json() == {
        "version": 1,
        "command": "diff",
        "since": "2026-09-30T12:00:00Z",
        "since_ms": SINCE_MS_Z,
        "started_at": FINISHED_AT,
        "finished_at": FINISHED_AT,
        "tables": [
            {
                "table": "users",
                "column": "update_time",
                "changed": 2,
                "ids": ["u1"],
                "truncated": False,
            }
        ],
    }
    assert "| users | update_time | 2 |" in diff.to_markdown()


# --- parser -----------------------------------------------------------------------------


def test_parser_reparse_args() -> None:
    args = cli._build_parser().parse_args(["reparse", "--datasets", "a,b", "--priority", "low"])

    assert args.command == "reparse"
    assert args.datasets == "a,b"
    assert args.priority == "low"
    assert args.report_dir == "."


def test_parser_run_has_since() -> None:
    args = cli._build_parser().parse_args(["run", "--since", "2026-09-30T12:00:00Z"])

    assert args.command == "run"
    assert args.since == "2026-09-30T12:00:00Z"


def test_parser_verify_and_diff_args() -> None:
    parser = cli._build_parser()
    verify = parser.parse_args(["verify", "--model-map", "m.yaml", "--report-dir", "out"])
    assert (verify.command, verify.model_map, verify.report_dir) == ("verify", "m.yaml", "out")

    diff = parser.parse_args(["diff", "--since", "2026-09-30", "--report-dir", "out"])
    assert (diff.command, diff.since, diff.report_dir) == ("diff", "2026-09-30", "out")


def test_parser_priority_rejects_unknown_value() -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli._build_parser().parse_args(["reparse", "--datasets", "all", "--priority", "high"])
    assert excinfo.value.code == 1


# --- CLI: gate'y i kody wyjścia ---------------------------------------------------------


def test_cli_diff_without_since_returns_1(
    no_dsn_env: None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["diff"]) == 1
    assert "--since" in capsys.readouterr().err


def test_cli_diff_with_bad_since_returns_1(
    no_dsn_env: None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["diff", "--since", "wczoraj"]) == 1
    assert "--since" in capsys.readouterr().err


def test_cli_verify_without_dsn_returns_1(
    no_dsn_env: None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["verify"]) == 1
    assert "DSN" in capsys.readouterr().err


def test_cli_run_with_bad_since_returns_1(wd_env: None, capsys: pytest.CaptureFixture[str]) -> None:
    """Błędny ``--since`` wychodzi przed dotknięciem źródła."""
    assert cli.main(["run", "--src-mysql", MYSQL_DSN, "--since", "wczoraj"]) == 1
    assert "--since" in capsys.readouterr().err


def test_cli_reparse_requires_datasets(wd_env: None, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["reparse"]) == 1
    assert "--datasets" in capsys.readouterr().err


def test_cli_reparse_empty_dataset_list_returns_1(
    wd_env: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--datasets ","`` to pusta lista id → błąd (kod 1), nigdy „wszystkie”."""
    assert cli.main(["reparse", "--datasets", ",", "--report-dir", str(tmp_path)]) == 1
    assert "pusta lista" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_cli_diff_error_returns_1(
    monkeypatch: pytest.MonkeyPatch,
    wd_env: None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Błąd biegu ``diff`` → kod 1, komunikat na stderr, bez plików raportu."""

    async def failing_run_diff(settings: Settings, since_ms: int) -> DiffReport:
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "run_diff", failing_run_diff)

    assert cli.main(["diff", "--since", "2026-09-30", "--report-dir", str(tmp_path)]) == 1
    assert "boom" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_cli_verify_error_returns_1(
    monkeypatch: pytest.MonkeyPatch,
    wd_env: None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Błąd biegu ``verify`` → kod 1, komunikat na stderr, źródło zamknięte, bez raportów."""
    src = FakeSource()
    monkeypatch.setattr(cli.Source, "connect", lambda dsn: src)

    argv = ["verify", "--src-mysql", MYSQL_DSN, "--report-dir", str(tmp_path)]
    assert cli.main(argv) == 1
    assert capsys.readouterr().err
    assert src.closed is True  # źródło zamykane także przy błędzie
    assert list(tmp_path.iterdir()) == []


# --- CLI: okablowanie raportów ----------------------------------------------------------


def test_cli_reparse_maps_all_and_priority(
    monkeypatch: pytest.MonkeyPatch, wd_env: None, tmp_path: Path
) -> None:
    seen: list[tuple[list[str] | None, int]] = []

    async def fake_run_reparse(
        settings: Settings, datasets: list[str] | None, priority: int
    ) -> FakeReport:
        seen.append((datasets, priority))
        return FakeReport("reparse", FINISHED_AT)

    monkeypatch.setattr(cli, "run_reparse", fake_run_reparse)

    assert cli.main(["reparse", "--datasets", "all", "--report-dir", str(tmp_path)]) == 0
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "reparse-report-20260102T030405Z.json",
        "reparse-report-20260102T030405Z.md",
    ]
    assert (
        cli.main(
            [
                "reparse",
                "--datasets",
                " a ,,b ",
                "--priority",
                "low",
                "--report-dir",
                str(tmp_path),
            ]
        )
        == 0
    )
    assert seen == [(None, 0), (["a", "b"], -1)]


def test_cli_verify_returns_2_on_critical(
    monkeypatch: pytest.MonkeyPatch, wd_env: None, tmp_path: Path
) -> None:
    src = FakeSource()
    monkeypatch.setattr(cli.Source, "connect", lambda dsn: src)

    async def fake_run_verify(source: object, settings: Settings, ctx: RunContext) -> FakeReport:
        assert ctx.since_ms is None
        return FakeReport("verify", FINISHED_AT, critical=True)

    monkeypatch.setattr(cli, "run_verify", fake_run_verify)

    argv = ["verify", "--src-mysql", MYSQL_DSN, "--report-dir", str(tmp_path)]
    assert cli.main(argv) == EXIT_CRITICAL
    assert src.closed is True
    payload = json.loads((tmp_path / "verify-report-20260102T030405Z.json").read_text("utf-8"))
    assert payload == {"version": 1, "command": "verify", "ok": False}


def test_cli_diff_writes_report(
    monkeypatch: pytest.MonkeyPatch, wd_env: None, tmp_path: Path
) -> None:
    seen: list[int] = []

    async def fake_run_diff(settings: Settings, since_ms: int) -> FakeReport:
        seen.append(since_ms)
        return FakeReport("diff", FINISHED_AT)

    monkeypatch.setattr(cli, "run_diff", fake_run_diff)

    argv = ["diff", "--since", "2026-09-30T12:00:00Z", "--report-dir", str(tmp_path)]
    assert cli.main(argv) == 0
    assert seen == [parse_since("2026-09-30T12:00:00Z")]
    assert (tmp_path / "diff-report-20260102T030405Z.md").is_file()


def test_cli_run_passes_since_ms_to_context(
    monkeypatch: pytest.MonkeyPatch, wd_env: None, tmp_path: Path
) -> None:
    seen: list[int | None] = []

    def fake_migrate(**kwargs: Any) -> Report:
        seen.append(kwargs["since_ms"])
        return Report(
            mode=kwargs["mode"],
            dry_run=False,
            started_at=FINISHED_AT,
            finished_at=FINISHED_AT,
            inventories=[],
            results=[],
        )

    monkeypatch.setattr(cli, "_migrate", fake_migrate)

    assert (
        cli.main(
            [
                "run",
                "--src-mysql",
                MYSQL_DSN,
                "--since",
                "2026-09-30T12:00:00Z",
                "--report-dir",
                str(tmp_path),
            ]
        )
        == 0
    )
    assert cli.main(["plan", "--src-mysql", MYSQL_DSN, "--report-dir", str(tmp_path)]) == 0
    assert seen == [parse_since("2026-09-30T12:00:00Z"), None]
