"""Testy wdeval.run — sklejenie biegu: kody wyjścia CLI i ścieżka sukcesu na łatach (T4, C11/C15).

Bez Dockera: stos, migracja i potok podmienione łatami; ``plan_run`` działa na
prawdziwych, minimalnych korpusach (pliki bety bez treści + fixture Codex).
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

import wdeval.run as run_module
from wdeval.cli import BETA_DATASET_PATH
from wdeval.dataset import load_dataset
from wdeval.profiles import PROFILES
from wdeval.stack import STACK_ENV_KEYS

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "wdeval"

# Pełne env stosu (klucze jak STACK_ENV_KEYS) — atrapa ephemeral_stack.
STOS_ENV: dict[str, str] = {
    "COMPOSE_PROJECT_NAME": "wd-test-agent-x-eval",
    "WD_TEST_DB_PORT": "18400",
    "WD_TEST_LLM_PORT": "18401",
    "WD_TEST_API_PORT": "18402",
    "WD_TEST_WEB_PORT": "18403",
    "WD_DB_HOST": "host-stosu",
    "WD_DB_PORT": "18400",
    "WD_DB_USER": "uzytkownik-stosu",
    "WD_DB_PASSWORD": "haslo-stosu",
    "WD_DB_NAME": "baza-stosu",
    "WD_LLM_BASE_URL": "http://host-stosu:18401/v1",
}

ARTEFAKT: dict[str, Any] = {"manifest": {}, "items": ["x"]}
RAPORT = "run_id: test\n"


def _pliki_profilu_dev() -> list[str]:
    """Unikalne pliki źródeł pozycji dev (kolejność wystąpienia w dataset.jsonl)."""
    pozycje_dev = PROFILES["dev"].beta_items
    assert pozycje_dev is not None
    nazwy: list[str] = []
    for pozycja in load_dataset(BETA_DATASET_PATH):
        if pozycja.id in pozycje_dev:
            for zrodlo in pozycja.sources:
                if zrodlo.file not in nazwy:
                    nazwy.append(zrodlo.file)
    return nazwy


def _zaloz_korpusy(tmp_path: Path) -> tuple[Path, Path]:
    """Minimalne korpusy dev: pliki bety (puste) + fixture Codex z mini-PoQuAD."""
    beta = tmp_path / "beta"
    beta.mkdir()
    for nazwa in _pliki_profilu_dev():
        (beta / nazwa).write_bytes(b"dane")

    codex = tmp_path / "codex"
    shutil.copytree(FIXTURES / "codex", codex)
    for katalog, nazwy in (
        (codex / "documents" / "en" / "pdf", ["x.pdf"]),
        (codex / "documents" / "pl" / "md", ["y.md"]),
        (codex / "documents" / "en" / "md", ["z.md"]),
    ):
        katalog.mkdir(parents=True, exist_ok=True)
        for nazwa in nazwy:
            (katalog / nazwa).write_bytes(b"dane")
    (codex / "benchmarks" / "poquad").mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / "poquad-mini.json", codex / "benchmarks" / "poquad" / "poquad-dev.json")
    return beta, codex


def _laty_sukcesu(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[tuple[str, ...]], list[tuple[str, str]], dict[str, Any]]:
    """Łaty: stos, migracja, potok, binarki; zwraca (usługi, migracje, przechwycone)."""
    assert set(STACK_ENV_KEYS) <= set(STOS_ENV)
    uslugi: list[tuple[str, ...]] = []

    @contextmanager
    def atrapa_stos(services: tuple[str, ...]) -> Iterator[dict[str, str]]:
        uslugi.append(services)
        yield dict(STOS_ENV)

    migracje: list[tuple[str, str]] = []

    def atrapa_migracji(cfg: Any, rewizja: str) -> None:
        migracje.append((str(cfg.attributes["settings"].db_name), rewizja))

    przechwycone: dict[str, Any] = {}

    async def atrapa_potoku(plan: Any, settings: Any) -> tuple[dict[str, Any], str]:
        przechwycone["plan"] = plan
        przechwycone["settings"] = settings
        return json.loads(json.dumps(ARTEFAKT)), RAPORT

    monkeypatch.setattr(run_module, "ephemeral_stack", atrapa_stos)
    monkeypatch.setattr(run_module.command, "upgrade", atrapa_migracji)
    monkeypatch.setattr(run_module, "run_pipeline", atrapa_potoku)
    monkeypatch.setattr("wdeval.cli.shutil.which", lambda nazwa: "/usr/bin/istnieje")
    return uslugi, migracje, przechwycone


def _argv(beta: Path, codex: Path, tmp_path: Path) -> list[str]:
    return [
        "--llm",
        "fake",
        "--profile",
        "dev",
        "--beta-corpus",
        str(beta),
        "--codex-corpus",
        str(codex),
        "--out",
        str(tmp_path / "artefakt.json"),
    ]


# --- błędy użycia i preflight -------------------------------------------------


def test_nieznany_profil_systemexit_2(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        run_module.main(["--llm", "fake", "--profile", "nieznany"])
    assert excinfo.value.code == 2  # noqa: PLR2004 — kod argparse dla złych argumentów


def test_vision_przy_fake_kod_2(capsys: pytest.CaptureFixture[str]) -> None:
    kod = run_module.main(["--llm", "fake", "--profile", "dev", "--arms", "vision"])
    assert kod == 2  # noqa: PLR2004 — UsageError
    assert "vision" in capsys.readouterr().err


def test_brak_korpusu_kod_3(capsys: pytest.CaptureFixture[str]) -> None:
    kod = run_module.main(["--llm", "fake", "--profile", "codex", "--codex-corpus", "/nie/ma"])
    assert kod == 3  # noqa: PLR2004 — PreflightError
    assert "/nie/ma" in capsys.readouterr().err


# --- ścieżka sukcesu -----------------------------------------------------------


def test_sukces_kod_0_i_artefakt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    beta, codex = _zaloz_korpusy(tmp_path)
    uslugi, migracje, przechwycone = _laty_sukcesu(monkeypatch)
    # pułapki w otoczeniu: WD_DB_* musi przyjść ze stosu, nigdy z os.environ
    monkeypatch.setenv("WD_DB_NAME", "pulapka")
    monkeypatch.setenv("WD_DB_PORT", "59999")

    kod = run_module.main(_argv(beta, codex, tmp_path))

    assert kod == 0
    assert uslugi == [("mariadb-test", "fake-llm")]
    assert migracje == [("baza-stosu", "head")]
    artefakt = json.loads((tmp_path / "artefakt.json").read_text(encoding="utf-8"))
    assert artefakt == ARTEFAKT

    plan = przechwycone["plan"]
    assert plan.llm == "fake"
    assert plan.profile.name == "dev"
    assert plan.out == tmp_path / "artefakt.json"

    settings = przechwycone["settings"]
    assert settings.env == "test"
    assert settings.db_host == "host-stosu"
    assert settings.db_port == 18400  # noqa: PLR2004 — port ze stosu, nie pułapka 59999
    assert settings.db_user == "uzytkownik-stosu"
    assert settings.db_password.get_secret_value() == "haslo-stosu"
    assert settings.db_name == "baza-stosu"
    assert settings.llm_base_url == "http://host-stosu:18401/v1"
    assert settings.llm_api_key.get_secret_value() == "fake"
    assert settings.ocr_engine == "none"
    assert settings.worker_poll_s == 0.05  # noqa: PLR2004 — częste odpytywanie workera
    assert isinstance(settings.storage_root, str) and settings.storage_root

    wyjscie = capsys.readouterr()
    assert RAPORT in wyjscie.out
    assert "artefakt" in wyjscie.err
    assert "czas biegu" in wyjscie.err


def test_wyjatek_potoku_kod_1(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    beta, codex = _zaloz_korpusy(tmp_path)
    _laty_sukcesu(monkeypatch)

    async def wybuchowy_potok(plan: Any, settings: Any) -> tuple[dict[str, Any], str]:
        raise RuntimeError("bieg wybuchł")

    monkeypatch.setattr(run_module, "run_pipeline", wybuchowy_potok)

    kod = run_module.main(_argv(beta, codex, tmp_path))

    assert kod == 1
    assert "eval: RuntimeError: bieg wybuchł" in capsys.readouterr().err
    assert not (tmp_path / "artefakt.json").exists()
