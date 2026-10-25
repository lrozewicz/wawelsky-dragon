"""Powierzchnia integracji SharePoint `/api/integrations*` (03 §5, kontrakt E4-3a §4).

`routers` montuje `include_hub_compat_routers` pod `""` i `/sharepoint-sync-api`. Kolejność ma
znaczenie: trasy z parametrem `{id}` muszą być po trasach stałych, dlatego `runs.router`
(tu trasy `/api/integrations/runs*`) trafia PRZED `integrations.router` — inaczej
`/api/integrations/runs` zostałoby dopasowane do `/{id}`.
"""

from app.api.hub_compat.sharepoint import datasets, documents, integrations, runs

routers = (runs.router, integrations.router, datasets.router, documents.router)
