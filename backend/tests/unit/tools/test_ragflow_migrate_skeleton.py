"""Testy szkieletu narzędzia migracji — bez bazy (brief T2, p. 8)."""

import json
import runpy
import sys
from pathlib import Path

import pymysql
import pytest

from app.core.config import Settings
from app.core.ids import UuidV7Generator
from app.core.timeutil import SystemClock
from app.tools.ragflow_migrate import cli, stages
from app.tools.ragflow_migrate.model_map import MappedModel, ModelMap
from app.tools.ragflow_migrate.report import Report, write_report
from app.tools.ragflow_migrate.runner import plan_all, run_all
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import (
    Issue,
    RunContext,
    StageInventory,
    StageResult,
)

_SRC_PORT = 3307


def _inventory(stage: str, issues: list[Issue]) -> StageInventory:
    return StageInventory(stage=stage, source_counts={}, issues=issues, not_migrated={})


def _result(stage: str, issues: list[Issue]) -> StageResult:
    return StageResult(
        stage=stage,
        source_count=1,
        created=1,
        updated=0,
        skipped=0,
        target_count=1,
        issues=issues,
    )


class FakeStage:
    """Etap-atrapa: nie dotyka źródła, zwraca zadaną uwagę."""

    def __init__(self, name: str, issue: Issue | None = None) -> None:
        self.name = name
        self.issue = issue

    def plan(self, src: Source, ctx: RunContext) -> StageInventory:
        return _inventory(self.name, [] if self.issue is None else [self.issue])

    async def run(self, src: Source, session: object, ctx: RunContext) -> StageResult:
        return _result(self.name, [] if self.issue is None else [self.issue])


class FakeSession:
    """Sesja-atrapa: zapisuje kolejność commit/rollback/close."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def commit(self) -> None:
        self.calls.append("commit")

    async def rollback(self) -> None:
        self.calls.append("rollback")

    async def close(self) -> None:
        self.calls.append("close")


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
    """Połączenie-atrapa dla ``Source.connect``."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, object]] = []
        self.closed = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def ctx() -> RunContext:
    return RunContext(
        model_map=ModelMap.load(None),
        settings=Settings(env="test", db_name="wawelsky_test"),
        clock=SystemClock(),
        id_gen=UuidV7Generator(),
        shared={},
    )


@pytest.mark.parametrize("table", ["user; DROP TABLE x", "us er", "users`", "User", "users-1", ""])
def test_rows_rejects_bad_table_identifier(table: str) -> None:
    src = Source(None)  # połączenie nie jest dotykane — walidacja biegnie pierwsza
    with pytest.raises(ValueError):
        src.rows(table)


def test_rows_uses_validated_identifier_and_params() -> None:
    conn = FakeConnection()
    src = Source(conn)
    assert src.rows("users", where="id = %s", params=["u1"]) == []
    assert conn.executed == [("SELECT * FROM `users` WHERE id = %s", ("u1",))]
    assert src.count("user") == 0
    assert conn.executed[-1] == ("SELECT COUNT(*) AS n FROM `user`", None)
    assert src.has_table("api_token") is False
    assert "table_name = %s" in conn.executed[-1][0]


def test_source_connect_parses_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConnection()
    kwargs: dict[str, object] = {}

    def fake_connect(**options: object) -> FakeConnection:
        kwargs.update(options)
        return conn

    monkeypatch.setattr(pymysql, "connect", fake_connect)
    src = Source.connect("mysql://root:p%40ss@src-db:3307/rf_src")

    assert kwargs["host"] == "src-db"
    assert kwargs["port"] == _SRC_PORT
    assert kwargs["user"] == "root"
    assert kwargs["password"] == "p@ss"  # noqa: S105 — atrapa hasła z DSN
    assert kwargs["database"] == "rf_src"
    assert kwargs["cursorclass"] is pymysql.cursors.DictCursor
    assert kwargs["charset"] == "utf8mb4"
    assert kwargs["autocommit"] is False
    assert conn.executed == [("SET SESSION TRANSACTION READ ONLY", None)]

    src.close()
    assert conn.closed is True


def test_source_connect_rejects_non_mysql_dsn() -> None:
    with pytest.raises(ValueError):
        Source.connect("postgres://root@src-db/db")


def test_model_map_load_none_is_empty() -> None:
    assert ModelMap.load(None).get("fake-chat@Tongyi-Qianwen") is None


def test_model_map_load_valid(tmp_path: Path) -> None:
    path = tmp_path / "model-map.yaml"
    path.write_text(
        "models:\n"
        '  "fake-chat@Tongyi-Qianwen": {name: "fake-chat-tongyi", model_type: chat}\n'
        '  "fake-embed-1024@OpenAI-API-Compatible": {name: "fake-embed-1024", dimension: 1024}\n',
        encoding="utf-8",
    )
    model_map = ModelMap.load(path)

    assert model_map.get("fake-chat@Tongyi-Qianwen") == MappedModel(
        name="fake-chat-tongyi", model_type="chat", dimension=None
    )
    assert model_map.get("fake-embed-1024@OpenAI-API-Compatible") == MappedModel(
        name="fake-embed-1024", model_type=None, dimension=1024
    )
    assert model_map.get("brak@Nigdzie") is None


def test_model_map_load_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.yaml"
    path.write_text("", encoding="utf-8")
    assert ModelMap.load(path).get("cokolwiek") is None


@pytest.mark.parametrize(
    "text",
    [
        'models:\n  "a@b": {name: x, nieznane: 1}\n',
        "nieznany_klucz: {}\n",
        'models:\n  "a@b": {model_type: chat}\n',
        'models:\n  "a@b": "tekst"\n',
        "- a\n",
        "models: [1, 2]\n",
    ],
)
def test_model_map_load_invalid(tmp_path: Path, text: str) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        ModelMap.load(path)


def _report(*, inventories: list[StageInventory], results: list[StageResult]) -> Report:
    return Report(
        mode="run",
        dry_run=False,
        started_at="2026-01-02T03:04:05Z",
        finished_at="2026-01-02T03:04:06Z",
        inventories=inventories,
        results=results,
    )


def test_report_json_shape_without_secrets() -> None:
    critical = Issue(
        severity="critical", code="email_collision", message="kolizja adresów", ids=["u1", "u2"]
    )
    report = _report(
        inventories=[
            StageInventory(
                stage="users",
                source_counts={"user": 3},
                issues=[critical],
                not_migrated={},
            )
        ],
        results=[
            StageResult(
                stage="users",
                source_count=3,
                created=2,
                updated=0,
                skipped=1,
                target_count=2,
                issues=[],
            )
        ],
    )
    payload = report.to_json()

    assert set(payload) == {
        "version",
        "mode",
        "dry_run",
        "started_at",
        "finished_at",
        "inventories",
        "results",
    }
    assert set(payload["inventories"][0]) == {"stage", "source_counts", "not_migrated", "issues"}
    assert set(payload["results"][0]) == {
        "stage",
        "source_count",
        "created",
        "updated",
        "skipped",
        "target_count",
        "issues",
    }
    assert set(payload["inventories"][0]["issues"][0]) == {"severity", "code", "message", "ids"}
    assert report.has_critical() is True

    text = json.dumps(payload)
    for secret in ("password", "token", "api_key", "secret"):
        assert secret not in text


def test_report_without_critical() -> None:
    warning = Issue(severity="warning", code="model_unmapped_default", message="brak mapy", ids=[])
    report = _report(inventories=[], results=[_result("models", [warning])])
    assert report.has_critical() is False
    assert "| warning | model_unmapped_default | brak mapy |  |" in report.to_markdown()


def test_write_report_names(tmp_path: Path) -> None:
    report = _report(inventories=[], results=[])
    json_path, md_path = write_report(report, tmp_path / "out")

    assert json_path.name == "migration-report-20260102T030406Z.json"
    assert md_path.name == "migration-report-20260102T030406Z.md"
    assert json.loads(json_path.read_text(encoding="utf-8"))["version"] == 1
    assert md_path.read_text(encoding="utf-8").startswith("# Migracja RAGFlow → WD — run")


def test_plan_all_in_order(monkeypatch: pytest.MonkeyPatch, ctx: RunContext) -> None:
    monkeypatch.setattr(
        stages,
        "STAGES",
        {"keys": FakeStage("keys"), "users": FakeStage("users")},
    )
    assert [inv.stage for inv in plan_all(Source(None), ctx)] == ["users", "keys"]


def test_plan_all_unknown_stage(monkeypatch: pytest.MonkeyPatch, ctx: RunContext) -> None:
    monkeypatch.setattr(stages, "STAGES", {"users": FakeStage("users")})
    with pytest.raises(ValueError):
        plan_all(Source(None), ctx, only=["nope"])


async def test_run_all_dry_run_rolls_back(monkeypatch: pytest.MonkeyPatch, ctx: RunContext) -> None:
    monkeypatch.setattr(stages, "STAGES", {"users": FakeStage("users")})
    session = FakeSession()

    results = await run_all(Source(None), lambda: session, ctx, dry_run=True)

    assert [res.stage for res in results] == ["users"]
    assert session.calls == ["rollback", "close"]


async def test_run_all_commits_without_critical(
    monkeypatch: pytest.MonkeyPatch, ctx: RunContext
) -> None:
    monkeypatch.setattr(stages, "STAGES", {"users": FakeStage("users")})
    session = FakeSession()

    await run_all(Source(None), lambda: session, ctx, dry_run=False)

    assert session.calls == ["commit", "close"]


async def test_run_all_rolls_back_on_critical(
    monkeypatch: pytest.MonkeyPatch, ctx: RunContext
) -> None:
    critical = Issue(severity="critical", code="dataset_name_collision", message="kolizja", ids=[])
    monkeypatch.setattr(stages, "STAGES", {"users": FakeStage("users", critical)})
    session = FakeSession()

    results = await run_all(Source(None), lambda: session, ctx, dry_run=False)

    assert session.calls == ["rollback", "close"]
    assert results[0].issues[0].severity == "critical"


async def test_run_all_unknown_stage(monkeypatch: pytest.MonkeyPatch, ctx: RunContext) -> None:
    session = FakeSession()
    with pytest.raises(ValueError):
        await run_all(Source(None), lambda: session, ctx, only=["nope"])
    assert session.calls == []


async def test_run_all_keeps_order_of_only(
    monkeypatch: pytest.MonkeyPatch, ctx: RunContext
) -> None:
    monkeypatch.setattr(
        stages,
        "STAGES",
        {"datasets": FakeStage("datasets"), "users": FakeStage("users")},
    )
    session = FakeSession()

    results = await run_all(Source(None), lambda: session, ctx, only=["datasets", "users"])

    assert [res.stage for res in results] == ["users", "datasets"]


def test_cli_run_help() -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["run", "--help"])
    assert excinfo.value.code == 0


def test_cli_missing_dsn(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(cli.ENV_SRC_MYSQL, raising=False)
    assert cli.main(["plan"]) == 1
    assert "DSN" in capsys.readouterr().err


def test_cli_argument_error_exits_with_1(capsys: pytest.CaptureFixture[str]) -> None:
    """Błąd argumentów → kod 1 (kontrakt §2), nie domyślne 2 argparse."""
    with pytest.raises(SystemExit) as unknown_flag:
        cli.main(["plan", "--nie-ma-takiej-flagi"])
    assert unknown_flag.value.code == 1

    with pytest.raises(SystemExit) as missing_command:
        cli.main([])
    assert missing_command.value.code == 1
    assert "error" in capsys.readouterr().err


def test_module_entrypoint_help(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["app.tools.ragflow_migrate", "--help"])
    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("app.tools.ragflow_migrate", run_name="__main__")
    assert excinfo.value.code == 0
