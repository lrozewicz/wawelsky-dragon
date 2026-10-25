#!/usr/bin/env python3
"""Krok security-audit (H16, WP E5-2b T2): pip-audit + bun audit + gitleaks z allowlistą wyjątków.

Uruchamianie (PyYAML jest tylko w backend/uv.lock — patrz CONTRACT.md WP E5-2b):
`uv run --frozen --project backend python tools/security_audit.py [--allowlist PATH] [--today YYYY-MM-DD] <komenda>`
Komendy:
- `check-allowlist` — waliduje allowlistę; naruszenia na stderr z id, kod 1.
- `run` — najpierw waliduje allowlistę, potem pip-audit (lockfile backendu), bun audit (frontend),
  gitleaks (`tools/dev/security-audit.sh`); kod 1 przy znalezisku blokującym albo braku sieci.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ALLOWLIST = REPO_ROOT / "security" / "audit-allowlist.yaml"

# GHSA w URLu doradztwa — bun audit podaje identyfikator wyłącznie w `url` (nie ma osobnego pola).
_GHSA_RE = re.compile(r"ghsa-[0-9a-z]{4}-[0-9a-z]{4}-[0-9a-z]{4}", re.IGNORECASE)
# Tylko niskie/średnie wypisujemy; high, critical i nieznany poziom blokują.
_INFORMATIONAL_SEVERITIES = {"low", "moderate"}


def _as_date(value: object) -> date | None:
    """Data z YAML-a: PyYAML parsuje niecytowane `YYYY-MM-DD` do `datetime.date`."""
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def load_allowlist(path: Path) -> list[dict]:
    """Lista wyjątków; brak pliku = pusta lista (domyślnie `entries: []`)."""
    if not path.is_file():
        return []
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = document.get("entries") or []
    return [entry for entry in entries if isinstance(entry, dict)]


def allowlist_violations(entries: list[dict], today: date) -> list[str]:
    """Naruszenia allowlisty: przeterminowana, bez `expires`, `approved_by` puste/PENDING."""
    violations: list[str] = []
    for entry in entries:
        entry_id = str(entry.get("id") or "(bez id)")
        expires = _as_date(entry.get("expires"))
        if expires is None:
            violations.append(f"{entry_id}: brak poprawnej daty expires (YYYY-MM-DD)")
        elif expires < today:
            violations.append(f"{entry_id}: wygasł {expires.isoformat()} (dziś {today.isoformat()})")
        approved = str(entry.get("approved_by") or "").strip()
        if approved in ("", "PENDING"):
            violations.append(
                f"{entry_id}: approved_by={approved or '(puste)'} — wymaga zatwierdzenia właściciela"
            )
    return violations


def active_ids(entries: list[dict], today: date, tool: str) -> set[str]:
    """Identyfikatory ważnych wyjątków danego narzędzia (wielkie litery do porównań)."""
    active: set[str] = set()
    for entry in entries:
        if str(entry.get("tool") or "") != tool:
            continue
        if str(entry.get("approved_by") or "").strip() in ("", "PENDING"):
            continue
        expires = _as_date(entry.get("expires"))
        if expires is None or expires < today:
            continue
        entry_id = entry.get("id")
        if entry_id:
            active.add(str(entry_id).upper())
    return active


def _excepted(ids: list[str], active: set[str]) -> bool:
    return any(value.upper() in active for value in ids if value)


def blocking_pip_findings(payload: dict, active: set[str]) -> list[dict]:
    """Znaleziska pip-audit bez ważnego wyjątku; brak poziomów — każde blokuje."""
    blocking: list[dict] = []
    for dependency in payload.get("dependencies") or []:
        for vuln in dependency.get("vulns") or []:
            ids = [str(vuln.get("id") or "")] + [str(alias) for alias in vuln.get("aliases") or []]
            if _excepted(ids, active):
                continue
            blocking.append(
                {
                    "package": dependency.get("name"),
                    "id": vuln.get("id"),
                    "fixes": vuln.get("fix_versions") or [],
                }
            )
    return blocking


def split_bun_advisories(payload: dict, active: set[str]) -> tuple[list[dict], list[dict]]:
    """Dzieli doradztwa bun audit (mapa pakiet → lista) na blokujące i informacyjne."""
    blocking: list[dict] = []
    informational: list[dict] = []
    for package, advisories in payload.items():
        for advisory in advisories or []:
            match = _GHSA_RE.search(str(advisory.get("url") or ""))
            advisory_id = match.group(0) if match else str(advisory.get("id") or "")
            record = {
                "package": package,
                "id": advisory_id,
                "severity": str(advisory.get("severity") or "").lower(),
                "title": advisory.get("title"),
            }
            ids = [advisory_id, str(advisory.get("id") or "")]
            if _excepted(ids, active) or record["severity"] in _INFORMATIONAL_SEVERITIES:
                informational.append(record)
            else:
                blocking.append(record)
    return blocking, informational


def _pip_audit(root: Path, requirements: Path, active: set[str]) -> tuple[list[dict], int, str | None]:
    """(blokujące znaleziska, liczba pakietów, komunikat błędu albo None)."""
    proc = subprocess.run(
        [
            "uv",
            "run",
            "--frozen",
            "pip-audit",
            "-r",
            str(requirements),
            "--no-deps",
            "--disable-pip",
            "--strict",
            "-f",
            "json",
        ],
        cwd=root / "backend",
        capture_output=True,
        text=True,
    )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return [], 0, "brak sieci albo usługa audytu niedostępna (pip-audit)"
    found = blocking_pip_findings(payload, active)
    return found, len(payload.get("dependencies") or []), None


def _bun_audit(root: Path, active: set[str]) -> tuple[list[dict], list[dict], str | None]:
    """(blokujące, informacyjne, komunikat błędu). `ensure_bun` w tej samej powłoce ustawia PATH."""
    proc = subprocess.run(
        [
            "bash",
            "-c",
            '. "$1/tools/dev/ensure-tools.sh"; ensure_bun || exit 1; cd "$1/frontend"; exec bun audit --json',
            "_",
            str(root),
        ],
        capture_output=True,
        text=True,
    )
    if not proc.stdout.strip():
        return [], [], "brak sieci albo usługa audytu niedostępna (bun-audit)"
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return [], [], "brak sieci albo usługa audytu niedostępna (bun-audit)"
    blocking, informational = split_bun_advisories(payload, active)
    return blocking, informational, None


def _gitleaks(root: Path) -> tuple[bool, str]:
    proc = subprocess.run(
        [str(root / "tools" / "dev" / "security-audit.sh"), "gitleaks"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        return True, "OK"
    return False, proc.stderr.strip() or proc.stdout.strip() or f"rc={proc.returncode}"


def run(root: Path, allowlist_path: Path, today: date) -> int:
    """pip-audit + bun audit + gitleaks, poprzedzone walidacją allowlisty. 0 = zielono."""
    entries = load_allowlist(allowlist_path)
    violations = allowlist_violations(entries, today)
    for violation in violations:
        print(f"security-audit: allowlist: {violation}", file=sys.stderr)
    if violations:
        return 1

    failed = False
    tmp = Path(tempfile.mkdtemp())
    requirements = tmp / "requirements.txt"
    export = subprocess.run(
        ["uv", "export", "--frozen", "--no-hashes", "--no-emit-project", "-o", str(requirements)],
        cwd=root / "backend",
        capture_output=True,
        text=True,
    )
    if export.returncode != 0:
        print("security-audit: brak sieci albo usługa audytu niedostępna (pip-audit)", file=sys.stderr)
        print(export.stderr.strip(), file=sys.stderr)
        return 1

    pip_blocking, packages, pip_error = _pip_audit(
        root, requirements, active_ids(entries, today, "pip-audit")
    )
    if pip_error is not None:
        print(f"security-audit: {pip_error}", file=sys.stderr)
        failed = True
    for finding in pip_blocking:
        fixes = ", ".join(finding["fixes"]) or "brak poprawki"
        print(
            f"security-audit: pip-audit: {finding['package']} {finding['id']} (poprawki: {fixes})",
            file=sys.stderr,
        )
    if pip_blocking:
        failed = True
    print(f"security-audit: pip-audit: {packages} pakietów, {len(pip_blocking)} blokujących znalezisk")

    bun_blocking, bun_info, bun_error = _bun_audit(
        root, active_ids(entries, today, "bun-audit")
    )
    if bun_error is not None:
        print(f"security-audit: {bun_error}", file=sys.stderr)
        failed = True
    for record in bun_blocking:
        print(
            f"security-audit: bun-audit: {record['package']} {record['id']} {record['severity']}",
            file=sys.stderr,
        )
    if bun_blocking:
        failed = True
    for record in bun_info:
        print(
            f"security-audit: bun-audit (informacyjne): "
            f"{record['package']} {record['id']} {record['severity']}"
        )
    print(
        f"security-audit: bun-audit: {len(bun_blocking)} blokujących, "
        f"{len(bun_info)} informacyjnych"
    )

    gitleaks_ok, gitleaks_detail = _gitleaks(root)
    if not gitleaks_ok:
        print(f"security-audit: gitleaks: {gitleaks_detail}", file=sys.stderr)
        failed = True
    print(f"security-audit: gitleaks: {'OK' if gitleaks_ok else 'CZERWIEŃ'}")

    if failed:
        print("security-audit: CZERWIEŃ — znaleziska blokujące albo brak sieci", file=sys.stderr)
        return 1
    print("security-audit: OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="security_audit.py")
    parser.add_argument("--allowlist", type=Path, default=DEFAULT_ALLOWLIST)
    parser.add_argument("--today", default=None, help="YYYY-MM-DD (domyślnie dziś)")
    parser.add_argument("command", choices=["check-allowlist", "run"])
    args = parser.parse_args(argv)
    today = date.fromisoformat(args.today) if args.today else date.today()

    if args.command == "check-allowlist":
        entries = load_allowlist(args.allowlist)
        violations = allowlist_violations(entries, today)
        for violation in violations:
            print(f"security-audit: allowlist: {violation}", file=sys.stderr)
        if violations:
            return 1
        print(f"security-audit: allowlist OK ({len(entries)} pozycji)")
        return 0

    return run(REPO_ROOT, args.allowlist, today)


if __name__ == "__main__":
    sys.exit(main())
