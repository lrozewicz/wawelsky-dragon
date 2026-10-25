"""Testy scripts/gen-secrets.sh (kontrakt WP E0-3 C10, tabela wejście→wyjście z briefu)."""

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

from app.core.config import Settings

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "gen-secrets.sh"
EXAMPLE = Path(__file__).resolve().parents[4] / ".env.example"

SECRET_NAMES = (
    "WD_DB_PASSWORD",
    "WD_DB_ROOT_PASSWORD",
    "WD_SECRET_KEY",
    "WD_CRYPTO_KEY",
    "WD_HUB_COMPAT_API_SECRET",
)

FILE_MODE = 0o600
SECRET_KEY_MIN_BYTES = 32


def run_gen(*arguments: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - stałe argumenty, bez shell
        ["bash", str(SCRIPT), *arguments],  # noqa: S607 - bash ze ścieżki systemowej
        capture_output=True,
        text=True,
        input=stdin,
        check=False,
    )


def read_env(path: Path) -> dict[str, str]:
    """Parsuje linie `NAZWA=wartość` (bez komentarzy) na słownik."""
    return {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
    }


def generate(target: Path) -> subprocess.CompletedProcess[str]:
    result = run_gen(str(target))
    assert result.returncode == 0
    return result


def test_generation_creates_file_with_secrets(tmp_path: Path) -> None:
    target = tmp_path / "x.env"
    result = generate(target)
    assert result.stdout == f"wygenerowano {target}\n"
    assert result.stderr == ""
    assert stat.S_IMODE(target.stat().st_mode) == FILE_MODE

    values = read_env(target)
    for name in SECRET_NAMES:
        assert name in values
        assert values[name] != ""
    assert len(set(values[name] for name in SECRET_NAMES)) == len(SECRET_NAMES)
    assert re.fullmatch(r"[0-9a-f]{64}", values["WD_CRYPTO_KEY"])
    assert len(values["WD_SECRET_KEY"].encode()) >= SECRET_KEY_MIN_BYTES

    # linie sekretów występują dokładnie raz
    lines = target.read_text(encoding="utf-8").splitlines()
    for name in SECRET_NAMES:
        assert len([line for line in lines if line.startswith(f"{name}=")]) == 1

    # zbiór nazw zmiennych identyczny jak w .env.example
    assert set(values) == set(read_env(EXAMPLE))

    # sekrety nigdy nie trafiają na stdout/stderr
    for name in SECRET_NAMES:
        assert values[name] not in result.stdout
        assert values[name] not in result.stderr


def test_generated_secrets_pass_prod_settings_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "x.env"
    generate(target)
    values = read_env(target)

    for name in [key for key in os.environ if key.startswith("WD_")]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("WD_ENV", "prod")
    monkeypatch.setenv("WD_LLM_BASE_URL", "http://llm.invalid/v1")
    monkeypatch.setenv("WD_DB_PASSWORD", values["WD_DB_PASSWORD"])
    monkeypatch.setenv("WD_SECRET_KEY", values["WD_SECRET_KEY"])
    monkeypatch.setenv("WD_CRYPTO_KEY", values["WD_CRYPTO_KEY"])
    monkeypatch.setenv("WD_HUB_COMPAT_API_SECRET", values["WD_HUB_COMPAT_API_SECRET"])

    Settings()  # nie rzuca


def test_two_runs_produce_different_secrets(tmp_path: Path) -> None:
    first = tmp_path / "a.env"
    second = tmp_path / "b.env"
    generate(first)
    generate(second)
    assert read_env(first)["WD_SECRET_KEY"] != read_env(second)["WD_SECRET_KEY"]


def test_existing_file_without_force_fails(tmp_path: Path) -> None:
    target = tmp_path / "x.env"
    generate(target)
    original = target.read_text(encoding="utf-8")

    result = run_gen(str(target))
    assert result.returncode == 1
    assert "istnieje" in result.stderr
    assert target.read_text(encoding="utf-8") == original


def test_force_with_refusal_keeps_file(tmp_path: Path) -> None:
    target = tmp_path / "x.env"
    generate(target)
    original = target.read_text(encoding="utf-8")

    result = run_gen("--force", str(target), stdin="n\n")
    assert result.returncode == 1
    assert "nadpisać" in result.stderr
    assert target.read_text(encoding="utf-8") == original


def test_force_with_confirmation_overwrites(tmp_path: Path) -> None:
    target = tmp_path / "x.env"
    generate(target)
    old = read_env(target)

    result = run_gen("--force", str(target), stdin="t\n")
    assert result.returncode == 0
    new = read_env(target)
    assert new["WD_SECRET_KEY"] != old["WD_SECRET_KEY"]
    assert set(new) == set(old)
