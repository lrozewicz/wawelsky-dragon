"""Eksport dokumentu OpenAPI do backend/openapi.json (K6 §4, kontrakt C2.3).

Plik wynikowy jest commitowany i nigdy nie edytowany ręcznie — regeneracja:
``cd backend && uv run --frozen python -m app.api.openapi_export``.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from app.core.config import Settings
from app.main import create_app

OPENAPI_PATH: Path = Path(__file__).resolve().parents[2] / "openapi.json"
STALE_MESSAGE = (
    "backend/openapi.json nieaktualny — uruchom: "
    "cd backend && uv run --frozen python -m app.api.openapi_export"
)


def export_settings() -> Settings:
    """Ustawienia eksportu: dev jawne, niezależne od WD_* i .env (K6 §4)."""
    return Settings(env="dev")


def render() -> str:
    """Dokument OpenAPI jako tekst: indent 2, ensure_ascii=False, końcowy znak nowej linii."""
    return json.dumps(create_app(export_settings()).openapi(), indent=2, ensure_ascii=False) + "\n"


def main(argv: Sequence[str] | None = None, path: Path = OPENAPI_PATH) -> int:
    """Zapis dokumentu; ``--check``: 0 gdy plik aktualny, inaczej 1 i STALE_MESSAGE na stderr."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if not args.check:
        path.write_text(render(), encoding="utf-8")
        return 0
    if path.exists() and path.read_text(encoding="utf-8") == render():
        return 0
    print(STALE_MESSAGE, file=sys.stderr)
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
