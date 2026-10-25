"""Składanie usługi integracji w procesie `api` (kontrakt E4-3a §4).

`create_app` woła `install_integrations` gdy `Settings.integrations_enabled`, tuż przed
`include_routers` — proces `api` rejestruje własny konektor SharePoint (DEC-074 p. 3).
"""

from typing import cast

from fastapi import FastAPI, Request

from app.core.config import Settings
from app.integrations.config import IntegrationsConfig
from app.integrations.sharepoint.register import register_sharepoint
from app.services.integrations import IntegrationService


def install_integrations(app: FastAPI, settings: Settings) -> None:
    """Rejestruje konektor SharePoint i wystawia `IntegrationService` w `app.state` (§4)."""
    container = app.state.container
    register_sharepoint(container)
    config = IntegrationsConfig.from_settings(settings)
    app.state.integrations = IntegrationService(container, config)


def integration_service(request: Request) -> IntegrationService:
    """Singleton usługi integracji z `app.state` (DEC-074 p. 2)."""
    return cast(IntegrationService, request.app.state.integrations)
