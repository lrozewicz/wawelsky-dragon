"""Rejestracja konektora SharePoint w rejestrze integracji (WP E4-2b, kontrakt register.py).

Worker woła `register_sharepoint` raz, przy tworzeniu kontenera (``app/worker/main.py``);
testy przekazują własny `connector` (np. na ``httpx.MockTransport``).
"""

from app.core.container import Container
from app.integrations import registry
from app.integrations.sharepoint.connector import SharePointConnector
from app.integrations.sharepoint.loader import make_load_config


def register_sharepoint(container: Container, connector: SharePointConnector | None = None) -> None:
    """Rejestruje konektor i loader konfiguracji pod typem ``sharepoint`` (kontrakt E4-2b)."""
    production = connector or SharePointConnector(
        login_base_url=container.settings.sp_login_base_url,
        graph_base_url=container.settings.sp_graph_base_url,
    )
    registry.register("sharepoint", production, make_load_config(container))
