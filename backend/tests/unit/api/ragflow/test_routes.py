"""Testy stubów tras /api/v1 (C8) — prefiks, zero tras, kolejność dołączania."""

import importlib
from unittest.mock import MagicMock

import pytest
from starlette.routing import Route

import app.api.ragflow.routes as routes_pkg
from app.api.ragflow.routes import include_ragflow_routes
from app.core.config import Settings
from app.main import create_app

# Kolejność dołączania z C8; wszystkie routery mają trasy (E1-9a: datasets, documents, chunks,
# retrieval; E1-9b: chats, sessions, completions) — po scaleniu obu WP nie ma już stubów.
# E2-1 DS2 dokłada router ingestii/embeddingu datasetu zaraz po routerze datasetów,
# E2-1 DS3 — router metadanych datasetu, E2-1 DOC2 — ``documents_files`` przed
# ``documents_extra`` i ``documents`` (``/documents/images/{id}`` i ``/thumbnails`` muszą
# trafić przed ``…/documents/{document_id}``, a ``PATCH …/documents/metadatas`` przed
# ``PATCH …/documents/{id}``), E2-1 CHAT — router rekomendacji pytań (kanoniczna trasa
# i alias) po routerze sessions; E4-4a T2b — ``searches`` po ``recommendation`` i przed
# ``completions``; E4-5a T5b — ``files`` po ``searches`` i przed ``completions``;
# E4-5b T1 — ``file_legacy`` (legacy ``/api/v1/file/*``, poza schematem OpenAPI) zaraz po
# ``files``;
# E2-1 OC — ``openai_chat`` po ``completions``
# (``/openai/{chat_id}/chat/completions`` i alias ``/chats_openai/…``); E2-1 OD — ``dify``
# i ``openai_models`` na końcu (ścieżki /dify/… i /openai/{chat_id}/models nie kolidują
# z wcześniejszymi trasami); kolejność wg `include_ragflow_routes`.
ROUTERS = (
    "datasets",
    "dataset_ingestions",
    "dataset_metadata",
    "documents_files",
    "documents_extra",
    "documents",
    "chunks",
    "retrieval",
    "chats",
    "sessions",
    "recommendation",
    "searches",
    "files",
    "file_legacy",
    "completions",
    "openai_chat",
    "dify",
    "openai_models",
)

# Pełna kolejność ``include_ragflow_routes``: na początku puste jeszcze routery instancji
# dostawców (E3-6b T1, K13 §3) — ``main`` rejestruje ``routes.models`` bezpośrednio przed tym
# wywołaniem, więc lądują zaraz po trasach ``models``; po E2-1 OD na końcu dochodzą puste
# routery legacy (E2-2f: ``legacy_v1`` wg E2-2a i ``legacy_v024`` wg E2-2b) — bez
# prefiksu/tras wymaganych od ROUTERS, więc trzymane osobno od parametrii powyżej.
PROVIDER_ROUTERS = ("provider_instances", "provider_models")
ORDERED_ROUTERS = (*PROVIDER_ROUTERS, *ROUTERS, "legacy_v1", "legacy_v024")


@pytest.mark.parametrize("name", ROUTERS)
def test_router_has_prefix_and_routes(name: str) -> None:
    """Każdy router /api/v1: prefiks z C8 i co najmniej jedna trasa
    (brak stubów po E1-9a i E1-9b)."""
    module = importlib.import_module(f"app.api.ragflow.routes.{name}")
    assert module.router.prefix == "/api/v1"
    assert len(module.router.routes) > 0


def test_include_order_matches_c8() -> None:
    """include_ragflow_routes dołącza routery w kolejności z C8 (identyczność obiektów)."""
    recorder = MagicMock()
    include_ragflow_routes(recorder)  # type: ignore[arg-type]
    by_id = {id(getattr(routes_pkg, name).router): name for name in ORDERED_ROUTERS}
    names = [by_id[id(call.args[0])] for call in recorder.include_router.call_args_list]
    assert names == list(ORDERED_ROUTERS)


def test_create_app_wires_ragflow_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    """create_app wywołuje include_ragflow_routes (C8, bez routera K9 — to T3)."""
    calls: list[object] = []
    monkeypatch.setattr("app.main.include_ragflow_routes", calls.append)
    app = create_app(Settings(env="test"))
    assert calls == [app]


def test_create_app_adds_no_new_routes() -> None:
    """Stuby zero tras — żadna trasa (Route) nie dochodzi; wpis _IncludedRouter FastAPI
    to wewnętrzna księgowość, nie trasa (uwaga w briefie: liczba tras jak przed zmianą)."""
    app = create_app(Settings(env="test"))
    before = [route for route in app.routes if isinstance(route, Route)]
    include_ragflow_routes(app)
    after = [route for route in app.routes if isinstance(route, Route)]
    assert after == before
    assert [route.path for route in after] == [route.path for route in before]
