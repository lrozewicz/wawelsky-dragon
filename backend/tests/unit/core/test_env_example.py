"""Test zgodności .env.example z Settings — reguły z K8 część A.

Poprawka zmiany 11: plik dzieli się na trzy sekcje (główna, compose, live).
"""

import re
from pathlib import Path

from app.core.config import Settings

ENV_EXAMPLE_PATH = Path(__file__).resolve().parents[4] / ".env.example"
COMPOSE_MARKER = "# --- tylko compose ---"
LIVE_MARKER = "# --- tylko tools/dev/live.sh ---"
ENV_LINE_RE = re.compile(r"^(WD_[A-Z0-9_]+)=")
VAR_LINE_RE = re.compile(r"^([A-Z0-9_]+)=")
ASSIGNMENT_RE = re.compile(r"^[A-Z0-9_]+=")
COMPOSE_VAR_COUNT = 14
COMPOSE_VARS: tuple[str, ...] = (
    "WD_DB_ROOT_PASSWORD",
    "TZ",
    "PORT",
    "WD_API_UPSTREAM",
    "KEYCLOAK_URL",
    "KEYCLOAK_REALM",
    "KEYCLOAK_CLIENT_ID",
    "DOCS_URL",
    "FEATURE_AGENT",
    "FEATURE_MEMORY",
    "FEATURE_SEARCH",
    "FEATURE_FILES",
    "WD_WORKER_MEM_LIMIT",
    "WD_NET_NAME",
)
LIVE_VAR_COUNT = 8
LIVE_VARS: tuple[str, ...] = (
    "WD_JUDGE_BASE_URL",
    "WD_JUDGE_API_KEY",
    "WD_JUDGE_MODEL",
    "WD_JUDGE_PROVIDER",
    "WD_SP_TEST_TENANT_ID",
    "WD_SP_TEST_CLIENT_ID",
    "WD_SP_TEST_CLIENT_SECRET",
    "WD_SP_TEST_SITE_URL",
)


def _sections() -> tuple[list[str], list[str], list[str]]:
    """Linie .env.example rozdzielone markerami sekcji compose i live."""
    main: list[str] = []
    compose: list[str] = []
    live: list[str] = []
    current = main
    for line in ENV_EXAMPLE_PATH.read_text(encoding="utf-8").splitlines():
        if line == COMPOSE_MARKER:
            current = compose
            continue
        if line == LIVE_MARKER:
            current = live
            continue
        current.append(line)
    return main, compose, live


def _env_names(lines: list[str]) -> set[str]:
    return {match.group(1) for line in lines if (match := ENV_LINE_RE.match(line))}


def _var_names(lines: list[str]) -> set[str]:
    return {match.group(1) for line in lines if (match := VAR_LINE_RE.match(line))}


def test_main_section_covers_settings_fields() -> None:
    main, _, _ = _sections()
    expected = {f"WD_{name.upper()}" for name in Settings.model_fields}
    assert _env_names(main) == expected


def test_compose_section_has_exactly_the_fourteen_vars() -> None:
    _, compose, _ = _sections()
    names = _var_names(compose)
    assert names == set(COMPOSE_VARS)
    assert len(names) == len(COMPOSE_VARS) == COMPOSE_VAR_COUNT


def test_live_section_has_exactly_the_eight_vars() -> None:
    _, _, live = _sections()
    names = _var_names(live)
    assert names == set(LIVE_VARS)
    assert len(names) == len(LIVE_VARS) == LIVE_VAR_COUNT


def test_live_vars_are_not_settings_fields() -> None:
    _, _, live = _sections()
    settings_vars = {f"WD_{name.upper()}" for name in Settings.model_fields}
    assert _var_names(live).isdisjoint(settings_vars)


def test_every_value_line_is_assignment() -> None:
    main, compose, live = _sections()
    for line in [*main, *compose, *live]:
        if line.strip() and not line.lstrip().startswith("#"):
            assert ASSIGNMENT_RE.match(line), f"linia bez NAZWA=...: {line!r}"


def test_marker_present_once() -> None:
    text = ENV_EXAMPLE_PATH.read_text(encoding="utf-8")
    assert text.count(COMPOSE_MARKER + "\n") == 1
    assert text.count(LIVE_MARKER + "\n") == 1


def test_markers_in_order_compose_then_live() -> None:
    lines = ENV_EXAMPLE_PATH.read_text(encoding="utf-8").splitlines()
    assert COMPOSE_MARKER in lines
    assert LIVE_MARKER in lines
    assert lines.index(COMPOSE_MARKER) < lines.index(LIVE_MARKER)
