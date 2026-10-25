"""Przepływ testu kształtów: trasy wyszukiwarek (T2b; K6 §5 p. 4, K15 §3).

Kształty ``SearchCreateResult``, ``SearchList``, ``SearchApp`` i ``SearchUpdateResult``
wymagają realnych odpowiedzi tras CRUD (``openapi_shapes.check``). Wyszukiwarka powstaje
bez ``kb_ids`` (tworzenie wiązania wymagałoby datasetu, a ten sam kształt pokrywa już
``shapes_datasets``).
"""

import httpx

from tests.integration.api.openapi_shapes import check


def flow(client: httpx.Client) -> set[str]:
    """Pełny CRUD wyszukiwarki; zwraca nazwy zwalidowanych komponentów (T2b)."""
    validated: set[str] = set()
    created = client.post("/api/v1/searches", json={"name": "wd_shapes_searches"})
    validated.add(check("searches_create", created))
    search_id = str(created.json()["data"]["search_id"])
    validated.add(check("searches_list", client.get("/api/v1/searches")))
    validated.add(check("searches_get", client.get(f"/api/v1/searches/{search_id}")))
    updated = client.put(
        f"/api/v1/searches/{search_id}",
        json={"name": "wd_shapes_searches", "search_config": {}},
    )
    validated.add(check("searches_update", updated))
    validated.add(check("searches_delete", client.delete(f"/api/v1/searches/{search_id}")))
    return validated
