"""CLI narzędzia migracji: ``plan``, ``run``, ``reparse``, ``verify``, ``diff`` (kontrakt §1)."""

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, NoReturn

from pydantic import SecretStr

from app.core.config import Settings
from app.core.ids import UuidV7Generator
from app.core.timeutil import SystemClock, iso, now_ms
from app.db.engine import make_engine, make_sessionmaker
from app.storage.filesystem import FilesystemStorage
from app.tools.ragflow_migrate.diff import run_diff
from app.tools.ragflow_migrate.model_map import ModelMap
from app.tools.ragflow_migrate.reparse import run_reparse
from app.tools.ragflow_migrate.report import Report, write_named, write_report
from app.tools.ragflow_migrate.runner import plan_all, run_all
from app.tools.ragflow_migrate.since import parse_since
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.stages.base import RunContext, StageInventory, StageResult
from app.tools.ragflow_migrate.verify import run_verify

ENV_SRC_MYSQL = "WD_MIGRATE_SRC_MYSQL"
ENV_SRC_SP_CRYPTO_KEY = "WD_MIGRATE_SRC_SP_CRYPTO_KEY"

Mode = Literal["plan", "run"]

#: ``--priority`` komendy ``reparse`` → priorytet zadania parsowania (05-ingestion: -1 = tło).
PRIORITY_CODES: dict[str, int] = {"low": -1, "normal": 0}

_SRC_MYSQL_HELP = f"DSN źródła (mysql://user:pass@host:port/db); domyślnie env {ENV_SRC_MYSQL}"
_REPORT_DIR_HELP = "katalog raportu (domyślnie .)"


def main(argv: list[str] | None = None) -> int:
    """Kod wyjścia: 0 = OK, 1 = błąd/argumenty, 2 = uwagi ``critical`` (raport zawsze)."""
    args = _build_parser().parse_args(argv)
    if args.command == "reparse":
        return _main_reparse(args)
    if args.command == "verify":
        return _main_verify(args)
    if args.command == "diff":
        return _main_diff(args)
    return _main_migrate(args)


def _main_migrate(args: argparse.Namespace) -> int:
    """``plan`` i ``run`` — jak dotąd; ``run`` obsługuje dodatkowo ``--since``."""
    dsn = _require_dsn(args)
    if dsn is None:
        return 1
    mode: Mode = args.command
    since_text = str(args.since) if mode == "run" and args.since else None
    try:
        since_ms = None if since_text is None else parse_since(since_text)
    except ValueError as exc:
        print(f"błędny --since: {exc}", file=sys.stderr)
        return 1
    model_map_path = Path(args.model_map) if args.model_map else None
    try:
        report = _migrate(
            mode=mode,
            dsn=dsn,
            model_map_path=model_map_path,
            only=args.only,
            dry_run=bool(getattr(args, "dry_run", False)),
            since_ms=since_ms,
            src_files_dir=args.src_files_dir,
            src_sp_crypto_key=args.src_sp_crypto_key,
        )
    except Exception as exc:  # noqa: BLE001 — kontrakt §1: każdy błąd biegu → kod 1
        print(f"błąd migracji: {exc}", file=sys.stderr)
        return 1
    _print_report_paths(*write_report(report, Path(args.report_dir)))
    return 2 if report.has_critical() else 0


def _migrate(  # noqa: PLR0913 — parametry jednego biegu zgodne z kontraktem §2
    *,
    mode: Mode,
    dsn: str,
    model_map_path: Path | None,
    only: Sequence[str] | None,
    dry_run: bool,
    since_ms: int | None,
    src_files_dir: Path | None,
    src_sp_crypto_key: str | None,
) -> Report:
    """Jeden bieg: ``plan`` (inwentarz) albo ``run`` (zapis do WD); zwraca gotowy raport."""
    started_at = iso(now_ms())
    settings = Settings()
    ctx = _new_context(settings, model_map_path, since_ms)
    ctx.src_files_dir = src_files_dir
    ctx.src_sp_crypto_key = SecretStr(src_sp_crypto_key) if src_sp_crypto_key else None
    src = Source.connect(dsn)
    inventories: list[StageInventory] = []
    results: list[StageResult] = []
    try:
        if mode == "plan":
            inventories = plan_all(src, ctx, only)
        else:
            results = asyncio.run(_run_mode(src, settings, ctx, only, dry_run))
    finally:
        src.close()
    return Report(
        mode=mode,
        dry_run=dry_run,
        started_at=started_at,
        finished_at=iso(now_ms()),
        inventories=inventories,
        results=results,
    )


async def _run_mode(
    src: Source,
    settings: Settings,
    ctx: RunContext,
    only: Sequence[str] | None,
    dry_run: bool,
) -> list[StageResult]:
    engine = make_engine(settings)
    try:
        return await run_all(src, make_sessionmaker(engine), ctx, only, dry_run)
    finally:
        await engine.dispose()


def _main_reparse(args: argparse.Namespace) -> int:
    """``reparse``: tylko cel (bez źródła); kolejkowanie parsowania przez ``Container``."""
    datasets_text = str(args.datasets or "")
    if not datasets_text:
        print("brak --datasets (all albo lista id datasetów po przecinku)", file=sys.stderr)
        return 1
    priority = PRIORITY_CODES[str(args.priority)]
    try:
        # Pusta lista id (np. ``--datasets ","``) to błąd, nie „wszystkie” (``_parse_datasets``).
        datasets = _parse_datasets(datasets_text)
        report = asyncio.run(run_reparse(Settings(), datasets, priority))
        json_path, md_path = write_named(
            "reparse-report",
            report.to_json(),
            report.to_markdown(),
            Path(args.report_dir),
            report.finished_at,
        )
    except Exception as exc:  # noqa: BLE001 — kontrakt §1: każdy błąd komendy (i zapisu) → kod 1
        print(f"błąd reparse: {exc}", file=sys.stderr)
        return 1
    _print_report_paths(json_path, md_path)
    return 0


def _main_verify(args: argparse.Namespace) -> int:
    """``verify``: źródło + cel; kod 2, gdy raport ma uwagi ``critical`` (kontrakt §4)."""
    dsn = _require_dsn(args)
    if dsn is None:
        return 1
    settings = Settings()
    model_map_path = Path(args.model_map) if args.model_map else None
    ctx = _new_context(settings, model_map_path)
    src: Source | None = None
    try:
        src = Source.connect(dsn)
        report = asyncio.run(run_verify(src, settings, ctx))
    except Exception as exc:  # noqa: BLE001 — kontrakt §4: wyjątek biegu → kod 1
        print(f"błąd verify: {exc}", file=sys.stderr)
        return 1
    finally:
        if src is not None:
            src.close()
    json_path, md_path = write_named(
        "verify-report",
        report.to_json(),
        report.to_markdown(),
        Path(args.report_dir),
        report.finished_at,
    )
    _print_report_paths(json_path, md_path)
    return 2 if report.has_critical() else 0


def _main_diff(args: argparse.Namespace) -> int:
    """``diff``: tylko cel; ``--since`` wymagane (kontrakt §1, §3.3)."""
    since_text = str(args.since or "")
    if not since_text:
        print("brak --since (ISO 8601, np. 2026-09-30T12:00:00Z)", file=sys.stderr)
        return 1
    try:
        since_ms = parse_since(since_text)
    except ValueError as exc:
        print(f"błędny --since: {exc}", file=sys.stderr)
        return 1
    try:
        report = asyncio.run(run_diff(Settings(), since_ms))
    except Exception as exc:  # noqa: BLE001 — kontrakt §1: każdy błąd komendy → kod 1
        print(f"błąd diff: {exc}", file=sys.stderr)
        return 1
    json_path, md_path = write_named(
        "diff-report",
        report.to_json(),
        report.to_markdown(),
        Path(args.report_dir),
        report.finished_at,
    )
    _print_report_paths(json_path, md_path)
    return 0


def _require_dsn(args: argparse.Namespace) -> str | None:
    """DSN źródła z ``--src-mysql`` albo env; brak → komunikat na stderr i ``None`` (kod 1)."""
    dsn = str(args.src_mysql or "")
    if not dsn:
        print(f"brak DSN źródła: podaj --src-mysql albo ustaw {ENV_SRC_MYSQL}", file=sys.stderr)
        return None
    return dsn


def _new_context(
    settings: Settings, model_map_path: Path | None, since_ms: int | None = None
) -> RunContext:
    """Kontekst biegu wspólny dla ``plan``/``run`` i ``verify`` (kontrakt §2, §4)."""
    return RunContext(
        model_map=ModelMap.load(model_map_path),
        settings=settings,
        clock=SystemClock(),
        id_gen=UuidV7Generator(),
        shared={},
        storage=FilesystemStorage(Path(settings.storage_root)),
        since_ms=since_ms,
    )


def _print_report_paths(json_path: Path, md_path: Path) -> None:
    """Ścieżki raportów na stdout — tak samo dla każdej komendy (kontrakt §1)."""
    print(f"raport JSON: {json_path}")
    print(f"raport Markdown: {md_path}")


def _parse_datasets(value: str) -> list[str] | None:
    """``all`` → ``None`` (wszystkie datasety); inaczej id po przecinku.

    Puste pozycje są odrzucane; gdy po odrzuceniu nic nie zostaje (``--datasets ","``) —
    ``ValueError``: pusta lista to błąd, nie „wszystkie” (kod 1).
    """
    if value.strip() == "all":
        return None
    ids = [item.strip() for item in value.split(",") if item.strip()]
    if not ids:
        raise ValueError("--datasets: pusta lista id (użyj all, by objąć wszystkie)")
    return ids


def _parse_only(value: str) -> list[str] | None:
    names = [item.strip() for item in value.split(",") if item.strip()]
    return names or None


class _ArgumentParser(argparse.ArgumentParser):
    """Błędne argumenty kończą się kodem 1 (kontrakt §1), a nie domyślnym 2 argparse."""

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="python -m app.tools.ragflow_migrate",
        description="Migracja danych z RAGFlow v0.24 do Wawelskiego Smoka.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="inwentarz źródła bez zapisu do WD")
    _add_common_args(plan)
    run = sub.add_parser("run", help="właściwa migracja do WD")
    _add_common_args(run)
    run.add_argument("--dry-run", action="store_true", help="zapis w transakcji wycofanej na końcu")
    run.add_argument(
        "--since",
        default=None,
        help="przyrost: tylko wiersze zmienione od ISO 8601 (bez strefy = UTC)",
    )
    reparse = sub.add_parser("reparse", help="ponowne kolejkowanie parsowania blobów w celu")
    reparse.add_argument(
        "--datasets", default=None, help="all albo id datasetów po przecinku (wymagane)"
    )
    reparse.add_argument(
        "--priority",
        choices=list(PRIORITY_CODES),
        default="normal",
        help="priorytet zadania parsowania: low = -1 (tło), normal = 0",
    )
    reparse.add_argument("--report-dir", default=".", help=_REPORT_DIR_HELP)
    verify = sub.add_parser("verify", help="sprawdzenie zgodności celu ze źródłem")
    verify.add_argument("--src-mysql", default=os.environ.get(ENV_SRC_MYSQL), help=_SRC_MYSQL_HELP)
    verify.add_argument("--model-map", default=None, help="plik YAML z mapą modeli")
    verify.add_argument("--report-dir", default=".", help=_REPORT_DIR_HELP)
    diff = sub.add_parser("diff", help="zmiany w tabelach celu od znacznika czasu (tylko SELECT)")
    diff.add_argument("--since", default=None, help="ISO 8601, np. 2026-09-30T12:00:00Z (wymagane)")
    diff.add_argument("--report-dir", default=".", help=_REPORT_DIR_HELP)
    return parser


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--src-mysql", default=os.environ.get(ENV_SRC_MYSQL), help=_SRC_MYSQL_HELP)
    parser.add_argument("--model-map", default=None, help="plik YAML z mapą modeli")
    parser.add_argument("--report-dir", default=".", help=_REPORT_DIR_HELP)
    parser.add_argument("--only", type=_parse_only, default=None, help="etapy po przecinku")
    parser.add_argument(
        "--src-files-dir",
        type=Path,
        default=None,
        help="katalog plików źródłowych RAGFlow (DIR/<bucket>/<location>)",
    )
    parser.add_argument(
        "--src-sp-crypto-key",
        default=os.environ.get(ENV_SRC_SP_CRYPTO_KEY),
        help=f"klucz HEX do sekretów SharePoint (domyślnie env {ENV_SRC_SP_CRYPTO_KEY})",
    )
