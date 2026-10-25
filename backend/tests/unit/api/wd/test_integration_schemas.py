"""Modele i straż dostępu tras WD integracji (brief T2, kontrakt E4-3b §0 p. 2/3/9/10, §2).

Testy bez bazy: ``Integration`` walidujemy ze słownika ``integration_dto`` rozszerzonego o ``type``
(1:1 kluczy z DTO SVC), a ``require_admin`` wołamy wprost z ręcznie zbudowanym ``Principal``.
"""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api.hub_compat.sharepoint.dto import integration_dto
from app.api.wd.integrations.deps import actor_dep, require_admin, wd_responses
from app.api.wd.integrations.errors import SourceLinkNotFound
from app.api.wd.integrations.schemas import (
    Integration,
    IntegrationCreateRequest,
    IntegrationUpdateRequest,
    WdErrorResponse,
)
from app.core.errors import PermissionDenied
from app.db.repositories.integrations import IntegrationRow, SharePointRow
from app.domain.policy import Principal
from app.services.integration_input import (
    DEFAULT_EXCLUDED_LIBRARY_NAMES,
    DEFAULT_IGNORED_EXTENSIONS,
    DEFAULT_MAX_FILE_SIZE_BYTES,
    DEFAULT_SCAN_INTERVAL_SECONDS,
)
from app.services.integration_ops import Actor, IntegrationView

_MOMENT_MS = 1790157600123
_CLIENT_IP = "10.0.0.7"
_DEFAULT_SCAN_INTERVAL_S = 300
_FORBIDDEN = 403
_NOT_FOUND = 404

# 19 kluczy ``integration_dto`` + ``type`` = 20 kluczy modelu ``Integration`` (kontrakt §0 p. 1).
INTEGRATION_KEYS = frozenset(
    {
        "id",
        "type",
        "name",
        "dataset_id",
        "tenant_id",
        "client_id",
        "client_secret_masked",
        "site_url",
        "site_id",
        "excluded_library_names",
        "max_file_size_bytes",
        "ignored_extensions",
        "scan_interval_seconds",
        "delete_propagation",
        "is_active",
        "is_running",
        "last_sync_at",
        "last_sync_status",
        "created_at",
        "updated_at",
    }
)


def _view() -> IntegrationView:
    """Widok integracji zbudowany z wierszy dataclass, jak w ``test_sharepoint_dto``."""
    row = IntegrationRow(
        id=7,
        type="sharepoint",
        name="Docs",
        dataset_id="ds-1",
        owner_id="owner-1",
        config={},
        secret_enc="enc",  # noqa: S106 — atrapa szyfrogramu, nie sekret
        secret_last4="abcd",  # noqa: S106 — maska sekretu, nie sekret
        max_file_size_bytes=1024,
        ignored_extensions=["exe"],
        scan_interval_seconds=300,
        delete_propagation=False,
        is_active=True,
        is_running=False,
        lock_acquired_at=None,
        lock_owner=None,
        cancel_requested=False,
        last_sync_at=None,
        last_sync_status=None,
        created_at=_MOMENT_MS,
        updated_at=_MOMENT_MS,
    )
    sharepoint = SharePointRow(
        integration_id=7,
        tenant_id="tenant-1",
        client_id="client-1",
        site_url="https://contoso.sharepoint.com/sites/eng",
        site_id="site-1",
        site_display_name="Eng",
        excluded_library_names=["Site Assets"],
    )
    return IntegrationView(row=row, sharepoint=sharepoint)


def _create_body(**over: object) -> dict[str, object]:
    """Minimalne poprawne ciało ``POST /integrations`` (kontrakt §2)."""
    body: dict[str, object] = {
        "type": "sharepoint",
        "name": "SP test",
        "dataset_id": "ds-1",
        "tenant_id": "tenant-1",
        "client_id": "client-1",
        "client_secret": "s3cr3t-abcd",
        "site_url": "https://contoso.sharepoint.com/sites/eng",
    }
    body.update(over)
    return body


def _principal(*, superuser: bool) -> Principal:
    """Principal testowy (bez bazy) — superuser albo zwykły użytkownik."""
    return Principal(
        user_id="u1",
        email="user@example.com",
        is_superuser=superuser,
        is_service=False,
        auth_kind="jwt",
    )


def test_integration_covers_dto_keys_exactly() -> None:
    """DTO + ``type`` → dokładnie 20 kluczy modelu, bez pól spoza kontraktu (kontrakt §0 p. 1)."""
    dto = integration_dto(_view())
    dto["type"] = "sharepoint"
    model = Integration.model_validate(dto)
    assert set(model.model_dump()) == INTEGRATION_KEYS
    assert len(model.model_dump()) == len(INTEGRATION_KEYS)
    assert set(dto) == INTEGRATION_KEYS


def test_create_request_defaults() -> None:
    """Minimalne ciało przechodzi, a brakujące pola biorą domyślne z ``integration_input``."""
    request = IntegrationCreateRequest.model_validate(_create_body())
    assert request.scan_interval_seconds == DEFAULT_SCAN_INTERVAL_SECONDS
    assert request.scan_interval_seconds == _DEFAULT_SCAN_INTERVAL_S
    assert request.delete_propagation is True
    assert request.is_active is True
    assert request.max_file_size_bytes == DEFAULT_MAX_FILE_SIZE_BYTES
    assert request.excluded_library_names == DEFAULT_EXCLUDED_LIBRARY_NAMES
    assert request.ignored_extensions == DEFAULT_IGNORED_EXTENSIONS
    # Domyślne listy to kopie — mutacja modelu nie zmienia stałej modułu.
    request.excluded_library_names.append("X")
    assert request.excluded_library_names[:-1] == DEFAULT_EXCLUDED_LIBRARY_NAMES


@pytest.mark.parametrize(
    "over",
    [
        {"type": "other"},
        {"name": ""},
        {"scan_interval_seconds": 10},
        {"delete_propagation": "yes"},
    ],
)
def test_create_request_rejects_invalid_values(over: dict[str, object]) -> None:
    """``type`` poza ``sharepoint``, pusta nazwa, za krótki interwał, nie-bool → ValidationError."""
    with pytest.raises(ValidationError):
        IntegrationCreateRequest.model_validate(_create_body(**over))


def test_update_request_is_all_optional() -> None:
    """Puste ciało PATCH jest poprawne — każde pole ``None`` znaczy „bez zmiany” (kontrakt §2)."""
    request = IntegrationUpdateRequest()
    assert all(value is None for value in request.model_dump().values())


async def test_require_admin_rejects_member() -> None:
    """Zwykły principal → ``PermissionDenied`` (slug ``permission_denied``, 403)."""
    with pytest.raises(PermissionDenied) as exc:
        await require_admin(_principal(superuser=False))
    assert exc.value.slug == "permission_denied"
    assert exc.value.http_status == _FORBIDDEN


async def test_require_admin_allows_superuser() -> None:
    """Superuser przechodzi i straż zwraca ten sam principal (kontrakt §0 p. 2)."""
    principal = _principal(superuser=True)
    assert await require_admin(principal) is principal


def test_actor_dep_builds_audit_actor() -> None:
    """Aktor audytu: etykieta z e-maila, id principala i IP klienta (kontrakt §0 p. 3)."""
    request = SimpleNamespace(client=SimpleNamespace(host=_CLIENT_IP))
    actor = actor_dep(request, _principal(superuser=True))  # type: ignore[arg-type]
    assert actor == Actor(label="user@example.com", id="u1", ip=_CLIENT_IP)


def test_wd_responses_use_wd_error_model() -> None:
    """Opisy błędów tras WD wskazują ``WdErrorResponse`` i mają polski opis (kontrakt §0 p. 10)."""
    responses = wd_responses(400, 403)
    assert set(responses) == {400, 403}
    assert responses[400]["model"] is WdErrorResponse
    assert responses[400]["description"]
    assert responses[403]["description"]


def test_source_link_not_found_carries_slug() -> None:
    """``SourceLinkNotFound`` niesie powód usługi jako ``slug`` koperty WD (kontrakt §0 p. 9)."""
    error = SourceLinkNotFound("Brak mapowania", "no_mapping")
    assert error.message == "Brak mapowania"
    assert error.slug == "no_mapping"
    assert error.http_status == _NOT_FOUND
