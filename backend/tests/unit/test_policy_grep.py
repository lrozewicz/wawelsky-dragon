"""Grep-test polityki (kontrakt C3): decyzje o dostępie zapadają tylko w app/domain/policy."""

import re
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2] / "app"
# Wyjątek C3: repozytorium users.py operuje na kolumnach SQL — decyzji tam nie zapada.
WYJATKI = {"app/db/repositories/users.py"}

_SUPERUSER_RE = re.compile(r"\b(if|elif|while|assert|and|or|not)\b|==|!=|\bis\b|\belse\b")
_TENANT_RE = re.compile(
    r"\b(tenant_id|created_by)\s*[!=]=|[!=]=\s*[\w.]*\b(tenant_id|created_by)\b"
)


def violations(text: str) -> list[int]:
    """Numery linii (od 1) łamiących regułę, po odcięciu komentarza ``#``."""
    broken: list[int] = []
    for no, line in enumerate(text.splitlines(), start=1):
        code = line.split("#", 1)[0]
        if ("is_superuser" in code and _SUPERUSER_RE.search(code)) or _TENANT_RE.search(code):
            broken.append(no)
    return broken


def test_no_access_decisions_outside_policy_module() -> None:
    """Przegląd całego app/ (poza modułem polityki i wyjątkami): lista naruszeń musi być pusta."""
    found: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        rel = path.relative_to(APP_ROOT.parent).as_posix()
        if rel.startswith("app/domain/policy") or rel in WYJATKI:
            continue
        found.extend(f"{rel}:{line}" for line in violations(path.read_text(encoding="utf-8")))
    assert found == []


def test_violations_on_synthetic_lines() -> None:
    """Sztuczne linie z kontraktu C3 przechodzą przez tę samą funkcję violations()."""
    assert violations("if principal.is_superuser:\n    pass\n") == [1]
    assert violations('x = {"is_superuser": u.is_superuser}\n') == []
    assert violations("ok = ds.tenant_id == principal.user_id\n") == [1]
    assert violations("y = 1  # if is_superuser\n") == []
