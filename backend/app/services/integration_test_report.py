"""Mapowanie raportu konektora na płaski DTO testu połączenia (K7 część 2 §7 p. 10, 03 §5).

Wydzielone z ``app/services/integrations.py`` (limit 400 linii pliku). Moduł nie dotyka
bazy ani sieci: kontenery dostarcza wywołujący, a usługa pyta go o ``site_resolution_ok``,
żeby wołać ``list_containers`` konektora tylko po udanym rozwiązaniu witryny.
"""

from app.integrations.base import ConnectionReport, Container

GRAPH_AUTH = "graph_auth"
SITE_RESOLUTION = "site_resolution"
AUTH_FAILED = "failed"
STATUS_OK = "ok"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"
AUTH_FAILED_MESSAGE = "graph auth failed"


def _checks_by_name(report: ConnectionReport) -> dict[str, dict[str, object]]:
    """Mapa ``name`` → check raportu (pierwszy wygrywa)."""
    return {str(check.get("name")): check for check in report.checks}


def site_resolution_ok(report: ConnectionReport) -> bool:
    """Czy check ``site_resolution`` istnieje i ma status ``ok`` (wtedy wolno pytać o kontenery)."""
    check = _checks_by_name(report).get(SITE_RESOLUTION)
    return check is not None and check.get("status") == STATUS_OK


def _put(target: dict[str, object], key: str, value: object) -> None:
    """Dopisuje klucz tylko wtedy, gdy ma wartość (kontrakt: brak kluczy z ``None``)."""
    if value is not None:
        target[key] = value


def build_report(
    report: ConnectionReport,
    *,
    containers: list[Container] | None,
    local_dataset: tuple[str, str | None],
) -> dict[str, object]:
    """Buduje płaski DTO testu połączenia; porażka ``graph_auth`` kończy etapy wcześnie.

    ``local_dataset`` to ``(status, nazwa)`` sprawdzone lokalnie: ``ok`` / ``not_found`` /
    ``skipped`` — check ``dataset_exists`` z raportu konektora jest ignorowany (09 §10).
    """
    checks = _checks_by_name(report)
    auth = checks.get(GRAPH_AUTH)
    detail = "" if auth is None else str(auth.get("detail") or "")
    if auth is None or auth.get("status") != STATUS_OK:
        return {
            GRAPH_AUTH: AUTH_FAILED,
            "graph_auth_error": detail or AUTH_FAILED_MESSAGE,
            SITE_RESOLUTION: STATUS_SKIPPED,
            "dataset_exists": STATUS_SKIPPED,
        }

    result: dict[str, object] = {GRAPH_AUTH: STATUS_OK}
    site = checks.get(SITE_RESOLUTION)
    status = STATUS_SKIPPED if site is None else str(site.get("status"))
    result[SITE_RESOLUTION] = status
    if site is not None and status == STATUS_FAILED:
        # Diagnostyka porażki kroku 2 — klucz obecny, bo etap się nie udał (może być pusty).
        result["site_resolution_error"] = str(site.get("detail") or "")
    if status == STATUS_OK:
        resolved = report.resolved
        _put(result, "site_id", resolved.get("site_id"))
        _put(result, "site_display_name", resolved.get("site_display_name"))
        _put(result, "drives_visible", resolved.get("libraries_total"))
        _put(result, "drives_after_exclusion", resolved.get("libraries_included"))
        _put(result, "drive_names", [container.name for container in containers or []])
    exists, name = local_dataset
    result["dataset_exists"] = exists
    _put(result, "dataset_name", name)
    return result
