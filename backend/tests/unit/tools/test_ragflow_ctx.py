"""Test RunContext, opcji CLI i sprzątania blobów w runnerze (brief T1, WP E4-6b1)."""

from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.ids import UuidV7Generator
from app.core.timeutil import SystemClock
from app.storage.filesystem import FilesystemStorage
from app.storage.keys import StorageKey
from app.tools.ragflow_migrate import stages
from app.tools.ragflow_migrate.cli import ENV_SRC_SP_CRYPTO_KEY, _build_parser
from app.tools.ragflow_migrate.model_map import ModelMap
from app.tools.ragflow_migrate.runner import run_all
from app.tools.ragflow_migrate.stages.base import Issue, RunContext, StageResult

BLOB_KEY = StorageKey("files/a/b/original.txt")

# Wartość tylko przechodzi przez parser (dysk nie jest dotykany) — S108 to fałszywy alarm.
SRC_FILES_DIR = "/tmp/d"  # noqa: S108


def test_parser_reads_src_paths() -> None:
    """Jawne opcje CLI lądują w argumentach bez zmiany typu."""
    args = _build_parser().parse_args(
        ["plan", "--src-mysql", "x", "--src-files-dir", SRC_FILES_DIR, "--src-sp-crypto-key", "abc"]
    )
    assert args.src_files_dir == Path(SRC_FILES_DIR)
    assert args.src_sp_crypto_key == "abc"


def test_parser_falls_back_to_env_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bez opcji klucz bierze się z env; katalog plików pozostaje ``None``."""
    monkeypatch.setenv(ENV_SRC_SP_CRYPTO_KEY, "zzz")
    args = _build_parser().parse_args(["plan", "--src-mysql", "x"])
    assert args.src_files_dir is None
    assert args.src_sp_crypto_key == "zzz"


def test_help_does_not_print_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--help`` nie ujawnia wartości klucza z env (ani w plan, ani w run)."""
    monkeypatch.setenv(ENV_SRC_SP_CRYPTO_KEY, "zzz")
    parser = _build_parser()
    for argv in (["--help"], ["plan", "--help"], ["run", "--help"]):
        with pytest.raises(SystemExit):
            parser.parse_args(argv)
        assert "zzz" not in capsys.readouterr().out


def test_run_context_defaults() -> None:
    """Bez nowych argumentów pola są ``None``/``False`` (zgodność z E4-6a)."""
    ctx = RunContext(
        model_map=ModelMap({}),
        settings=Settings(env="test"),
        clock=SystemClock(),
        id_gen=UuidV7Generator(),
        shared={},
    )
    assert ctx.storage is None
    assert ctx.src_files_dir is None
    assert ctx.src_sp_crypto_key is None
    assert ctx.dry_run is False


class FakeSession:
    """Atrapa sesji: tylko ``rollback``/``commit``/``close``, bez bazy."""

    def __init__(self) -> None:
        self.rolled_back = False
        self.committed = False
        self.closed = False

    async def rollback(self) -> None:
        self.rolled_back = True

    async def commit(self) -> None:
        self.committed = True

    async def close(self) -> None:
        self.closed = True


class FakeStage:
    """Etap-atrapa: zapisuje blob, dopisuje klucz i opcjonalnie zwraca Issue critical."""

    name = "fake"

    def __init__(self, *, critical: bool) -> None:
        self.critical = critical
        self.dry_run_seen: bool | None = None

    async def run(self, src: object, session: object, ctx: RunContext) -> StageResult:
        assert ctx.storage is not None
        await ctx.storage.put(BLOB_KEY, b"x")
        ctx.shared.setdefault("new_blob_keys", []).append(str(BLOB_KEY))
        self.dry_run_seen = ctx.dry_run
        issues = [Issue("critical", "boom", "test", [])] if self.critical else []
        return StageResult("fake", 0, 0, 0, 0, 0, issues)


def _ctx(storage: FilesystemStorage) -> RunContext:
    return RunContext(
        model_map=ModelMap({}),
        settings=Settings(env="test"),
        clock=SystemClock(),
        id_gen=UuidV7Generator(),
        shared={},
        storage=storage,
    )


async def _run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stage: FakeStage,
    *,
    dry_run: bool,
) -> tuple[FilesystemStorage, FakeSession]:
    monkeypatch.setattr(stages, "ORDER", ("fake",))
    monkeypatch.setitem(stages.STAGES, "fake", stage)
    storage = FilesystemStorage(tmp_path / "wd-storage")
    sessions: list[FakeSession] = []

    def fake_sessionmaker() -> FakeSession:
        session = FakeSession()
        sessions.append(session)
        return session

    await run_all(None, fake_sessionmaker, _ctx(storage), only=["fake"], dry_run=dry_run)  # type: ignore[arg-type]
    return storage, sessions[0]


async def test_critical_removes_new_blob(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Issue critical → rollback i usunięcie pliku zapisanego w tym biegu."""
    storage, session = await _run(monkeypatch, tmp_path, FakeStage(critical=True), dry_run=False)
    assert session.rolled_back is True
    assert session.committed is False
    assert await storage.exists(BLOB_KEY) is False


async def test_clean_run_keeps_blob(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Bez critical i bez dry-run → commit, plik zostaje."""
    stage = FakeStage(critical=False)
    storage, session = await _run(monkeypatch, tmp_path, stage, dry_run=False)
    assert session.committed is True
    assert session.rolled_back is False
    assert stage.dry_run_seen is False
    assert await storage.exists(BLOB_KEY) is True


async def test_dry_run_removes_new_blob(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``dry_run`` widać w etapie; po rollbacku nowy blob znika."""
    stage = FakeStage(critical=False)
    storage, session = await _run(monkeypatch, tmp_path, stage, dry_run=True)
    assert stage.dry_run_seen is True
    assert session.rolled_back is True
    assert await storage.exists(BLOB_KEY) is False
