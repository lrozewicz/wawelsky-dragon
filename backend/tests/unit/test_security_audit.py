"""Testy `tools/security_audit.py` (H16) — bieg przez verify-fast.

Test leży w backend/tests/unit (a nie w tools/tests), bo tylko ten katalog uruchamia
`./.claude/verify-fast.sh`; skrypt z tools/ ładujemy przez importlib,
a PyYAML jest w backend/uv.lock.
Sprawdzane są wyłącznie funkcje czyste (bez sieci): allowlista, ocena wygaśnięcia, filtr znalezisk.
"""

import importlib.util
from datetime import date
from pathlib import Path
from types import ModuleType

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "tools" / "security_audit.py"
TODAY = date(2026, 10, 2)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("tools_security_audit", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _LazyScript:
    """Skrypt z tools/ ładowany przy pierwszym użyciu atrybutu — obraz test-ocr nie ma /tools."""

    def __init__(self) -> None:
        self._module: ModuleType | None = None

    def __getattr__(self, attribute: str) -> object:
        if self._module is None:
            self._module = _load_script()
        return getattr(self._module, attribute)


security_audit = _LazyScript()


def _write_allowlist(tmp_path: Path, entries: list[dict]) -> Path:
    target = tmp_path / "audit-allowlist.yaml"
    target.write_text(yaml.safe_dump({"entries": entries}), encoding="utf-8")
    return target


def _entry(entry_id: str, tool: str, expires: date, approved_by: str = "owner") -> dict:
    return {
        "id": entry_id,
        "tool": tool,
        "package": "przyklad",
        "reason": "brak poprawki",
        "expires": expires,
        "approved_by": approved_by,
    }


def test_repo_allowlist_is_empty() -> None:
    """Domyślna allowlista repozytorium ma zero pozycji."""
    assert security_audit.load_allowlist(REPO_ROOT / "security" / "audit-allowlist.yaml") == []


def test_valid_entry_passes(tmp_path: Path) -> None:
    path = _write_allowlist(
        tmp_path, [_entry("GHSA-aaaa-bbbb-cccc", "pip-audit", date(2026, 12, 31))]
    )
    entries = security_audit.load_allowlist(path)
    assert security_audit.allowlist_violations(entries, TODAY) == []


def test_expired_entry_is_violation(tmp_path: Path) -> None:
    path = _write_allowlist(
        tmp_path, [_entry("GHSA-aaaa-bbbb-cccc", "pip-audit", date(2026, 1, 1))]
    )
    violations = security_audit.allowlist_violations(security_audit.load_allowlist(path), TODAY)
    assert any("GHSA-aaaa-bbbb-cccc" in v and "wygasł" in v for v in violations)


def test_missing_expires_is_violation(tmp_path: Path) -> None:
    entry = _entry("GHSA-aaaa-bbbb-cccc", "pip-audit", date(2026, 12, 31))
    del entry["expires"]
    path = _write_allowlist(tmp_path, [entry])
    violations = security_audit.allowlist_violations(security_audit.load_allowlist(path), TODAY)
    assert any("brak poprawnej daty expires" in v for v in violations)


def test_pending_approval_is_violation(tmp_path: Path) -> None:
    entry = _entry("GHSA-aaaa-bbbb-cccc", "pip-audit", date(2026, 12, 31), approved_by="PENDING")
    path = _write_allowlist(tmp_path, [entry])
    violations = security_audit.allowlist_violations(security_audit.load_allowlist(path), TODAY)
    assert any("PENDING" in v for v in violations)


def test_active_ids_skips_expired_and_pending(tmp_path: Path) -> None:
    entries = [
        _entry("GHSA-valid", "pip-audit", date(2026, 12, 31)),
        _entry("GHSA-expired", "pip-audit", date(2026, 1, 1)),
        _entry("GHSA-pending", "pip-audit", date(2026, 12, 31), approved_by="PENDING"),
        _entry("GHSA-other-tool", "bun-audit", date(2026, 12, 31)),
    ]
    assert security_audit.active_ids(entries, TODAY, "pip-audit") == {"GHSA-VALID"}


def _pip_payload(id_: str, *aliases: str) -> dict:
    return {
        "dependencies": [
            {
                "name": "przyklad",
                "version": "1.0.0",
                "vulns": [
                    {
                        "id": id_,
                        "aliases": list(aliases),
                        "fix_versions": [],
                        "description": "opis",
                    }
                ],
            }
        ]
    }


def test_pip_finding_matched_by_id_is_filtered() -> None:
    payload = _pip_payload("GHSA-aaaa-bbbb-cccc")
    assert security_audit.blocking_pip_findings(payload, {"GHSA-AAAA-BBBB-CCCC"}) == []


def test_pip_finding_matched_by_alias_is_filtered() -> None:
    payload = _pip_payload("PYSEC-2026-1", "GHSA-aaaa-bbbb-cccc")
    assert security_audit.blocking_pip_findings(payload, {"GHSA-AAAA-BBBB-CCCC"}) == []


def test_pip_finding_without_valid_exception_blocks() -> None:
    payload = _pip_payload("GHSA-aaaa-bbbb-cccc")
    blocking = security_audit.blocking_pip_findings(payload, {"GHSA-zzzz-yyyy-xxxx"})
    assert [finding["id"] for finding in blocking] == ["GHSA-aaaa-bbbb-cccc"]


def _bun_payload(
    severity: str, url: str = "https://github.com/advisories/GHSA-aaaa-bbbb-cccc"
) -> dict:
    return {
        "przyklad": [
            {
                "id": 42,
                "url": url,
                "title": "tytuł",
                "severity": severity,
                "vulnerable_versions": "<1.0.0",
            }
        ]
    }


def test_bun_high_severity_blocks() -> None:
    blocking, informational = security_audit.split_bun_advisories(_bun_payload("high"), set())
    assert [record["id"] for record in blocking] == ["GHSA-aaaa-bbbb-cccc"]
    assert informational == []


def test_bun_moderate_is_informational() -> None:
    blocking, informational = security_audit.split_bun_advisories(_bun_payload("moderate"), set())
    assert blocking == []
    assert [record["id"] for record in informational] == ["GHSA-aaaa-bbbb-cccc"]


def test_bun_exception_filters_high() -> None:
    blocking, informational = security_audit.split_bun_advisories(
        _bun_payload("critical"), {"GHSA-AAAA-BBBB-CCCC"}
    )
    assert blocking == []
    assert [record["id"] for record in informational] == ["GHSA-aaaa-bbbb-cccc"]


def test_bun_ghsa_extracted_from_url_with_suffix() -> None:
    url = "https://github.com/advisories/GHSA-aaaa-bbbb-cccc?query=1#frag"
    blocking, _ = security_audit.split_bun_advisories(_bun_payload("high", url=url), set())
    assert [record["id"] for record in blocking] == ["GHSA-aaaa-bbbb-cccc"]
