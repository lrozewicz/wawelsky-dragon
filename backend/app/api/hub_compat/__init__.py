"""Powierzchnia hub-compat: montaż routerów pod `""`, `/user-api` i `/sharepoint-sync-api` (C7).

Trasy SVC nie trafiają do OpenAPI UI (`include_in_schema=False`) — to nie jest API UI.
`/sharepoint-sync-api` to alias zgodny z oryginałem (`hub-compat/raglow-service/sharepoint-sync`);
montowany wyłącznie gdy `Settings.integrations_enabled`.
"""

from fastapi import FastAPI

from app.api.hub_compat import access, fallback, health, keys, sharepoint, users
from app.core.config import Settings

_PREFIXES = ("", "/user-api")
_SYNC_PREFIX = "/sharepoint-sync-api"


def include_hub_compat_routers(app: FastAPI, settings: Settings) -> None:
    """Montuje health oraz routery users/keys/access pod `""` i `/user-api` (C7).

    Fallback `{rest:path}` wyłącznie pod `/user-api` — globalny catch-all pod `""`
    przesłoniłby trasy RF (`/api/v1/*`) i WD (`/api/wd/v1/*`); pilnuje tego AG-31.
    Gdy `settings.integrations_enabled`: pod `""` i `/sharepoint-sync-api` dochodzą routery
    integracji (kolejność z `sharepoint.routers`), a pod `/sharepoint-sync-api` health i
    fallback (health pod `""` jest już w pętli prefiksów; fallbacku pod `""` nie ma — C7).
    `settings.hub_compat_routes=False` nie montuje niczego.
    """
    if not settings.hub_compat_routes:
        return
    for prefix in _PREFIXES:
        app.include_router(health.router, prefix=prefix, include_in_schema=False)
        for module in (users, keys, access):
            app.include_router(module.router, prefix=prefix, include_in_schema=False)
    app.include_router(fallback.router, prefix="/user-api", include_in_schema=False)
    if not settings.integrations_enabled:
        return
    for prefix in ("", _SYNC_PREFIX):
        for module_router in sharepoint.routers:
            app.include_router(module_router, prefix=prefix, include_in_schema=False)
    app.include_router(health.router, prefix=_SYNC_PREFIX, include_in_schema=False)
    app.include_router(fallback.router, prefix=_SYNC_PREFIX, include_in_schema=False)
