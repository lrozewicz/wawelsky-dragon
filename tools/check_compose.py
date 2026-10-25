#!/usr/bin/env python3
"""Statyczna kontrola docker-compose.yml pod H11/H12 (WP E5-2b T3; docs/architecture/11-infrastruktura.md §9).

Uruchamianie: `python3 tools/check_compose.py [PLIK ...]` (domyślnie `docker-compose.yml`).
Wymaga PyYAML — w tym repo jest on w `backend/uv.lock`, więc w verify-full.sh krok woła
`uv run --frozen --project backend python tools/check_compose.py`. Kod 0 = brak naruszeń,
1 = naruszenia wypisane na stderr z prefiksem H11:/H12:.
"""

import re
import sys
from pathlib import Path

import yaml

# H12: sekret rozpoznajemy po nazwie zmiennej (kontrakt WP E5-2b).
_SECRET_NAME_RE = re.compile(r"PASSWORD|SECRET|KEY|TOKEN")

# H12: jawnie opcjonalne zmienne sekretopodobne (${VAR:-} z pustym domyślnym) — każda z uzasadnieniem.
_OPTIONAL_SECRET_VARS = {
    # opcjonalna integracja hub-compat; brak = funkcja wyłączona
    "WD_HUB_COMPAT_API_SECRET",
    # KEYCLOAK_* to konfiguracja opcjonalna, nie sekret — reguła łapie je przez podciąg "KEY"
    "KEYCLOAK_URL",
    "KEYCLOAK_REALM",
    "KEYCLOAK_CLIENT_ID",
    # bootstrap admina jest opcjonalny (`ensure_admin` pomija puste dane); forma `${...:-}` wymuszona
    # przez K8 „Poprawka 2026-10-04” p. 1; DEC-236
    "WD_ADMIN_PASSWORD",
}

# H11: usługi bez `user:` i bez `USER` w obrazie, dopuszczone jawnie.
_NON_ROOT_EXCEPTIONS = {
    # oficjalny obraz mariadb startuje jako root i sam zrzuca uprawnienia do użytkownika `mysql`
    "mariadb",
    # oficjalny obraz vllm/vllm-openai nie ustawia USER (root) — vLLM pobiera wagi modelu i zapisuje cache
    # Hugging Face do /root/.cache/huggingface (wolumen `ocr-hf-cache`); usługa jest w profilu `ocr`,
    # bez portu publicznego i wyłącznie w sieci `wd-net` (WP E5-H4a, #8)
    "ocr",
}

_ROOT_OWNERS = {"", "0", "root"}


def _is_non_root_user(value: object) -> bool:
    """True, gdy `user:`/`USER` wskazuje właściciela innego niż root (0/root)."""
    owner = str(value).strip().split(":", 1)[0]
    return owner not in _ROOT_OWNERS


def _dockerfile_user(dockerfile: Path, target: str | None) -> str | None:
    """Ostatni USER etapu Dockerfile'a (`target` albo ostatni etap) z dziedziczeniem po FROM.

    None = nikt nie ustawił USER, czyli root z obrazu bazowego.
    """
    stages: list[dict[str, object]] = []
    by_name: dict[str, int] = {}
    current: dict[str, object] | None = None
    for raw in dockerfile.read_text(encoding="utf-8").splitlines():
        parts = raw.strip().split()
        if not parts or parts[0].startswith("#"):
            continue
        keyword = parts[0].upper()
        if keyword == "FROM" and len(parts) > 1:
            image = parts[1]
            named = len(parts) > 3 and parts[2].upper() == "AS"
            stage: dict[str, object] = {
                "parent": by_name.get(image),
                "user": None,
            }
            stages.append(stage)
            by_name[parts[3] if named else image] = len(stages) - 1
            current = stage
        elif keyword == "USER" and current is not None and len(parts) > 1:
            current["user"] = " ".join(parts[1:])
    if not stages:
        return None
    stage = stages[by_name[target]] if target is not None and target in by_name else stages[-1]
    parent = stage
    while parent is not None:
        if parent["user"] is not None:
            return str(parent["user"])
        index = parent["parent"]
        parent = stages[index] if isinstance(index, int) else None
    return None


def _build_context(service: dict[str, object], base_dir: Path) -> tuple[Path, str | None]:
    """Katalog kontekstu budowy i etap docelowy (`build:` jako string albo mapa)."""
    build = service.get("build")
    if isinstance(build, dict):
        context = base_dir / str(build.get("context", "."))
        target = build.get("target")
        return context, str(target) if target is not None else None
    if isinstance(build, str):
        return base_dir / build, None
    return base_dir, None


def _mount_strings(service: dict[str, object]) -> list[str]:
    volumes = service.get("volumes")
    if not isinstance(volumes, list):
        return []
    mounts: list[str] = []
    for entry in volumes:
        if isinstance(entry, dict):
            mounts.extend(str(entry.get(key, "")) for key in ("source", "target"))
        else:
            mounts.append(str(entry))
    return mounts


def _as_bool(value: object) -> bool:
    return value is True or str(value).strip().lower() == "true"


def _tmpfs_entries(service: dict[str, object]) -> list[str]:
    tmpfs = service.get("tmpfs")
    if isinstance(tmpfs, dict):
        return [str(key) for key in tmpfs]
    if isinstance(tmpfs, list):
        return [str(entry).split(":", 1)[0] for entry in tmpfs]
    return []


def _env_entries(service: dict[str, object]) -> list[tuple[str, object]]:
    environment = service.get("environment")
    if isinstance(environment, dict):
        return list(environment.items())
    if isinstance(environment, list):
        entries: list[tuple[str, object]] = []
        for item in environment:
            text = str(item)
            key, _, value = text.partition("=")
            entries.append((key, value if "=" in text else None))
        return entries
    return []


def _user_violation(name: str, service: dict[str, object], base_dir: Path) -> str | None:
    user = service.get("user")
    if user is not None:
        if _is_non_root_user(user):
            return None
        return f"H11: usługa '{name}': user={user} wskazuje root"
    if name in _NON_ROOT_EXCEPTIONS:
        return None
    context, target = _build_context(service, base_dir)
    dockerfile = context / "Dockerfile"
    if dockerfile.is_file():
        image_user = _dockerfile_user(dockerfile, target)
        if image_user is not None and _is_non_root_user(image_user):
            return None
    return f"H11: usługa '{name}': brak użytkownika non-root (compose `user:` albo `USER` w obrazie)"


def _h11_violations(name: str, service: dict[str, object], base_dir: Path) -> list[str]:
    found: list[str] = []
    for mount in _mount_strings(service):
        if "docker.sock" in mount:
            found.append(f"H11: usługa '{name}': montuje docker.sock ({mount})")
    if _as_bool(service.get("privileged")):
        found.append(f"H11: usługa '{name}': privileged: true")
    if name == "web":
        if not _as_bool(service.get("read_only")):
            found.append("H11: usługa 'web': brak read_only: true")
        if "/tmp" not in _tmpfs_entries(service):
            found.append("H11: usługa 'web': brak /tmp w tmpfs")
    violation = _user_violation(name, service, base_dir)
    if violation is not None:
        found.append(violation)
    return found


def _h12_violations(name: str, service: dict[str, object]) -> list[str]:
    found: list[str] = []
    for key, value in _env_entries(service):
        if not _SECRET_NAME_RE.search(key):
            continue
        text = "" if value is None else str(value)
        if re.search(r"\$\{[^}]*:\?", text):
            continue
        optional = re.fullmatch(r"\$\{([A-Z][A-Z0-9_]*):-\}", text)
        if optional is not None and optional.group(1) in _OPTIONAL_SECRET_VARS:
            continue
        found.append(
            f"H12: usługa '{name}', zmienna '{key}': wymagane ${{{key}:?...}} "
            "albo jawna opcjonalność z listy w check_compose.py"
        )
    return found


def collect_violations(path: Path) -> list[str]:
    """Lista naruszeń H11/H12 w pliku compose; pusta lista = plik zgodny."""
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    services = document.get("services") or {}
    violations: list[str] = []
    for name, service in services.items():
        if not isinstance(service, dict):
            continue
        violations.extend(_h11_violations(name, service, path.parent))
        violations.extend(_h12_violations(name, service))
    return violations


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    paths = [Path(arg) for arg in args] or [Path("docker-compose.yml")]
    failed = False
    for path in paths:
        if not path.is_file():
            print(f"check_compose: brak pliku {path}", file=sys.stderr)
            failed = True
            continue
        for violation in collect_violations(path):
            print(f"{violation} ({path})", file=sys.stderr)
            failed = True
    if failed:
        return 1
    print("compose-check: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
