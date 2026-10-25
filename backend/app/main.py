"""Składanie aplikacji FastAPI: lifespan kontenera, middleware, handlery (kontrakt C12)."""

import contextlib
import functools
from collections.abc import AsyncIterator

from fastapi import FastAPI

from app.api.errors import install_error_handlers
from app.api.health import router as health_router
from app.api.hub_compat import include_hub_compat_routers
from app.api.hub_compat.sharepoint.setup import install_integrations
from app.api.openapi import build_openapi
from app.api.ragflow.auth import router as auth_router
from app.api.ragflow.routes import include_ragflow_routes
from app.api.ragflow.routes import models as models_routes
from app.api.ragflow.routes import system as system_routes
from app.api.ragflow.system import router as system_router
from app.api.ragflow.users import router as users_router
from app.api.wd.access import routers as wd_access_routers
from app.api.wd.dataset_usage import router as wd_dataset_usage_router
from app.api.wd.integrations import routers as wd_integration_routers
from app.api.wd.kb_export import router as wd_kb_export_router
from app.api.wd.kb_import import router as wd_kb_import_router
from app.api.wd.system import routers as wd_system_routers
from app.api.wd.tasks import router as wd_tasks_router
from app.api.wd.test_reset import router as test_reset_router
from app.api.wd.users import routers as wd_users_routers
from app.core.config import Settings
from app.core.container import Container
from app.core.logging import configure_logging
from app.core.middleware import install_middleware
from app.core.version import APP_VERSION


def include_routers(app: FastAPI, settings: Settings) -> None:
    """Rejestruje routery: health, trasy auth/users/system oraz stuby /api/v1 ragflow (C8, C9)."""
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(system_router)
    app.include_router(system_routes.router)
    app.include_router(system_routes.legacy_router)
    app.include_router(models_routes.router)
    include_ragflow_routes(app)
    if settings.env == "test":  # K9 §1: trasa resetu istnieje tylko w trybie test
        app.include_router(test_reset_router)
    include_hub_compat_routers(app, settings)
    for router in (*wd_users_routers, *wd_access_routers, *wd_system_routers):
        app.include_router(router)  # trasy WD admina montowane bezwarunkowo (E3-6a §1)
    # Eksport/import paczek .wdkb (E7-1f): zadania WD + punkty rejestracji tras E7-1a/E7-1b;
    # użycie datasetu przed usunięciem (K20 §4).
    for router in (
        wd_tasks_router,
        wd_kb_export_router,
        wd_kb_import_router,
        wd_dataset_usage_router,
    ):
        app.include_router(router)
    if settings.integrations_enabled:  # trasy WD integracji tylko z włączoną integracją (§1)
        for router in wd_integration_routers:
            app.include_router(router)


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or Settings()  # jedyne miejsce odczytu env w procesie api
    configure_logging(settings)
    container = container or Container(settings)

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await container.start()
        yield
        await container.aclose()

    app = FastAPI(
        title="Wawelsky Dragon",
        version=APP_VERSION,
        lifespan=lifespan,
        openapi_url="/api/wd/v1/openapi.json",
        docs_url="/api/wd/v1/docs",
    )
    app.state.container = container
    app.state.settings = settings
    install_middleware(app, settings)
    install_error_handlers(app)
    if settings.integrations_enabled:  # konektor i usługa integracji w procesie api (DEC-074 p. 3)
        install_integrations(app, settings)
    include_routers(app, settings)
    app.openapi = functools.partial(build_openapi, app)  # type: ignore[method-assign]
    return app
