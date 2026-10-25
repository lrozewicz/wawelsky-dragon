"""Narzędzie egzekwujące limit rozmiaru plików źródłowych (kontrakt C2, WP E0-1a).

Użycie: python tools/check_file_size.py <katalog> --max N [--ext .py,.ts,.tsx] [--allowlist PLIK]
Naruszenie = liczba linii pliku większa niż N. Kod wyjścia: 0 — brak naruszeń,
1 — są naruszenia (lista na stderr), 2 — błąd użycia.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_EXTENSIONS = (".py", ".ts", ".tsx")
SKIPPED_DIRS = frozenset({"__pycache__", "node_modules", ".venv"})

EXIT_VIOLATIONS = 1
EXIT_USAGE = 2


def parse_allowlist(path: Path, repo_root: Path) -> set[Path]:
    """Zwraca zbiór zrozumiałych ścieżek z pliku allowlisty.

    Format linii: `<ścieżka>  # <uzasadnienie>` — wpis bez uzasadnienia kończy
    działanie kodem 2. Ścieżki są rozwiązywane względem korzenia repo
    (ścieżka absolutna zostaje absolutna).
    """
    allowed: set[Path] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        entry, separator, _justification = line.partition("#")
        if not separator:
            print(
                f"check_file_size: wpis allowlisty bez uzasadnienia: {raw_line}",
                file=sys.stderr,
            )
            sys.exit(EXIT_USAGE)
        allowed.add((repo_root / entry.strip()).resolve())
    return allowed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sprawdza, że pliki źródłowe nie przekraczają limitu linii."
    )
    parser.add_argument("directory", type=Path, help="katalog przeszukiwany rekurencyjnie")
    parser.add_argument("--max", type=int, required=True, dest="max_lines", help="limit linii")
    parser.add_argument(
        "--ext",
        default=",".join(DEFAULT_EXTENSIONS),
        help="lista rozszerzeń po przecinku (domyślnie .py,.ts,.tsx)",
    )
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=Path(__file__).resolve().parent / "file-size-allowlist.txt",
        help="plik wyjątków (używany tylko gdy istnieje)",
    )
    args = parser.parse_args(argv)

    directory = args.directory
    if not directory.is_dir():
        print(f"check_file_size: brak katalogu {directory}", file=sys.stderr)
        return EXIT_USAGE

    repo_root = Path(__file__).resolve().parent.parent
    allowed: set[Path] = set()
    if args.allowlist.is_file():
        allowed = parse_allowlist(args.allowlist, repo_root)

    extensions = {ext.strip() for ext in args.ext.split(",") if ext.strip()}
    violations: list[str] = []
    for file_path in sorted(
        candidate
        for candidate in directory.rglob("*")
        if candidate.is_file()
        and not SKIPPED_DIRS.intersection(candidate.parts)
        and candidate.suffix in extensions
    ):
        if file_path.resolve() in allowed:
            continue
        text = file_path.read_text(encoding="utf-8", errors="replace")
        line_count = len(text.splitlines())
        if line_count > args.max_lines:
            violations.append(f"{file_path}: {line_count} > {args.max_lines}")
    for violation in violations:
        print(violation, file=sys.stderr)
    return EXIT_VIOLATIONS if violations else 0


if __name__ == "__main__":
    sys.exit(main())
