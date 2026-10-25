"""Wersja aplikacji: jedno źródło i brak rozjazdu między backendem a frontem (K20 §3)."""

import json
import tomllib
from pathlib import Path

from app.core.version import APP_VERSION

BACKEND_DIR = Path(__file__).resolve().parents[3]
REPO_DIR = BACKEND_DIR.parent


def test_app_version_matches_pyproject_and_package_json() -> None:
    """``APP_VERSION``, ``pyproject.toml`` i ``frontend/package.json`` mają tę samą wartość.

    Rozjazd którejkolwiek z trzech wartości to czerwony test (K20 §3, wymóg briefu T1 p. 6).
    """
    pyproject = tomllib.loads((BACKEND_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    package = json.loads((REPO_DIR / "frontend" / "package.json").read_text(encoding="utf-8"))
    assert APP_VERSION == "1.3.0"
    assert pyproject["project"]["version"] == APP_VERSION
    assert package["version"] == APP_VERSION
