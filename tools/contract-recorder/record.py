# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "httpx==0.28.1",
#     "pyyaml==6.0.3",
#     "pycryptodomex==3.23.0",
#     "mcp==1.30.0",
# ]
# ///
"""Contract-recorder: stawia oficjalny stos RAGFlow z fake-llm i nagrywa kontrakt API (SP-5, C2).

Cykl zycia compose: down -v (porzadki) -> up -d --build -> wait_ready -> bootstrap
-> scenariusze YAML (runner.py) -> down -v w finally (takze przy wyjatku i Ctrl-C).
`--keep` zostawia stos i zapisuje sesje, `--attach` dolacza do stosu z sesji bez compose
i bootstrapu, `--out` wskazuje katalog zlota. Jedyny publikowany port: 18380 -> 9380.

`--mcp` (tylko v0.27.2) dokłada override compose z serwerem MCP upstream i kieruje kroki
wzorcow spod `mcp_scenarios/` do mcp_runner.py (reszta do runner.py); bez `--mcp` bieg
jest identyczny jak dotad (bez override).
"""

import argparse
import signal
import subprocess
import sys
import time
from pathlib import Path

from mcp_runner import load_mcp_scenario, run_mcp_scenario
from rf_bootstrap import (
    RagflowSession,
    bootstrap,
    load_session,
    save_session,
    session_path,
    wait_ready,
)
from runner import load_scenario, run_scenario

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
GOLDEN_ROOT = REPO_ROOT / "backend" / "tests" / "contract" / "golden"
PROJECT_PREFIX = "wd-rec-"
BASE_URL = "http://host.docker.internal:18380"
MCP_BASE_URL = "http://host.docker.internal:19382"
MCP_OVERRIDE = "compose.v0.27.2.mcp.yml"
MCP_SCENARIO_DIR = "mcp_scenarios"
WAIT_TIMEOUT_S = 900.0


def _interrupt(signum: int, _frame: object) -> None:
    """Zamienia SIGINT/SIGTERM na wyjatek, zeby finally (down -v) zdazyl posprzatac."""
    raise KeyboardInterrupt(f"przerwano sygnalem {signum}")


def _compose_cmd(project: str, compose_paths: list[Path], *args: str) -> list[str]:
    files = [flag for path in compose_paths for flag in ("-f", str(path))]
    return ["docker", "compose", "-p", project, *files, *args]


def _compose(
    project: str, compose_paths: list[Path], *args: str, check: bool
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(_compose_cmd(project, compose_paths, *args), check=check)


def _dump_ragflow_logs(project: str, compose_paths: list[Path]) -> None:
    """Diagnostyka przy porazce: ostatnie 200 linii logow uslugi ragflow na stderr."""
    cmd = _compose_cmd(project, compose_paths, "logs", "--tail", "200", "ragflow")
    subprocess.run(cmd, check=False, stdout=sys.stderr)


def _is_mcp_scenario(path: Path) -> bool:
    """Rozpoznanie po katalogu: wzorce pod ``mcp_scenarios/`` ida do mcp_runner."""
    return path.parent == SCRIPT_DIR / MCP_SCENARIO_DIR


def _run_scenarios(
    session: RagflowSession,
    scenario_paths: list[Path],
    version: str,
    out_root: Path,
    mcp_base_url: str,
) -> tuple[int, int]:
    """Uruchamia scenariusze sekwencyjnie; FAIL jednego nie przerywa reszty."""
    files_total = 0
    fails = 0
    for path in scenario_paths:
        scenario: dict | None = None
        try:
            if _is_mcp_scenario(path):
                scenario = load_mcp_scenario(path)
                saved = run_mcp_scenario(session, scenario, out_root, mcp_base_url)
            else:
                scenario = load_scenario(path)
                saved = run_scenario(session, scenario, version, out_root)
        except Exception as exc:  # noqa: BLE001 — celowo szeroko: scenariusz FAIL,
            # przyczyna na stdout, reszta scenariuszy leci dalej, stos sprzatany w finally
            fails += 1
            name = scenario["name"] if scenario else path.stem
            print(f"SCENARIO {name} FAIL files=0 {exc}", flush=True)
            continue
        files_total += saved
        print(f"SCENARIO {scenario['name']} OK files={saved}", flush=True)
    return files_total, fails


def _collect_scenarios(patterns: list[str]) -> list[Path]:
    """Sciezki scenariuszy ze wszystkich wzorcow (bez duplikatow, posortowane)."""
    return sorted({p for pattern in patterns for p in SCRIPT_DIR.glob(pattern)})


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Nagrywa kontrakt API RAGFlow na oficjalnym stosie z fake-llm."
    )
    parser.add_argument(
        "--version",
        required=True,
        choices=("v0.24.0", "v0.27.2"),
        help="Wersja stosu RAGFlow.",
    )
    parser.add_argument(
        "--bootstrap-only",
        action="store_true",
        help="Tylko stos + bootstrap konta i modeli (bez scenariuszy).",
    )
    parser.add_argument(
        "--mcp",
        action="store_true",
        help="Wlacz serwer MCP upstream (override compose; tylko v0.27.2).",
    )
    parser.add_argument(
        "--scenarios",
        nargs="+",
        default=["scenarios/*.yaml"],
        help="Jeden lub wiecej wzorcow glob scenariuszy wzgledem katalogu narzedzia.",
    )
    state = parser.add_mutually_exclusive_group()
    state.add_argument(
        "--keep",
        action="store_true",
        help="Nie usuwaj stosu na koncu; zapisz sesje do /tmp (do trybu --attach).",
    )
    state.add_argument(
        "--attach",
        action="store_true",
        help="Nie stawiaj stosu ani bootstrapu — wczytaj sesje zapisana przez --keep.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Katalog glowny zlota (domyslnie backend/tests/contract/golden).",
    )
    return parser.parse_args(argv)


def main() -> int:
    args = _parse_args()
    if args.mcp and args.version != "v0.27.2":
        print("--mcp dziala tylko z --version v0.27.2", file=sys.stderr)
        return 2
    compose_paths = [SCRIPT_DIR / f"compose.{args.version}.yml"]
    if args.mcp:
        compose_paths.append(SCRIPT_DIR / MCP_OVERRIDE)
    for compose_path in compose_paths:
        if not args.attach and not compose_path.exists():
            print(f"Brak pliku compose: {compose_path}", file=sys.stderr)
            return 2
    scenario_paths = _collect_scenarios(args.scenarios)
    if not scenario_paths and not args.bootstrap_only:
        print(
            f"Brak scenariuszy dla wzorcow: {' '.join(args.scenarios)}", file=sys.stderr
        )
        return 2
    project = PROJECT_PREFIX + args.version.replace(".", "-")
    out_root = args.out if args.out is not None else GOLDEN_ROOT
    signal.signal(signal.SIGINT, _interrupt)
    signal.signal(signal.SIGTERM, _interrupt)
    started = time.monotonic()
    message = ""
    rc = 0
    try:
        if args.attach:
            try:
                session = load_session(args.version)
            except FileNotFoundError:
                print(
                    f"Brak pliku sesji {session_path(args.version)} — "
                    f"uruchom najpierw z --keep",
                    file=sys.stderr,
                )
                return 2
        else:
            _compose(
                project, compose_paths, "down", "-v", "--remove-orphans", check=False
            )
            _compose(project, compose_paths, "up", "-d", "--build", check=True)
            wait_ready(BASE_URL, WAIT_TIMEOUT_S)
            session = bootstrap(BASE_URL)
            if args.keep:
                save_session(session, args.version)
        seconds = round(time.monotonic() - started, 1)
        if args.bootstrap_only:
            message = (
                f"BOOTSTRAP OK version={args.version} chat={session.chat_model} "
                f"embd={session.embd_model} seconds={seconds}"
            )
        else:
            files, fails = _run_scenarios(
                session, scenario_paths, args.version, out_root, MCP_BASE_URL
            )
            seconds = round(time.monotonic() - started, 1)
            message = (
                f"RECORD version={args.version} scenarios={len(scenario_paths)} "
                f"files={files} fail={fails} seconds={seconds}"
            )
            rc = 0 if fails == 0 else 1
    except BaseException:
        if not args.attach:
            _dump_ragflow_logs(project, compose_paths)
        raise
    finally:
        if not args.keep and not args.attach:
            _compose(
                project, compose_paths, "down", "-v", "--remove-orphans", check=False
            )
    print(message)
    return rc


if __name__ == "__main__":
    sys.exit(main())
