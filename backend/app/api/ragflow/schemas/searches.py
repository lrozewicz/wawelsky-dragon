"""Modele OpenAPI wyszukiwarek (K15 §3, CONTRACT E4-4a §D5-§D6).

Schematy są wyłącznie opisowe (K6 §1): kształty odpowiedzi odpowiadają prezenterowi
``present/searches.py``, a żądania — ``normalize/searches.py``.
"""

from typing import Any

from app.api.ragflow.schemas.common import RequestModel, ResponseModel


class SearchConfig(RequestModel):
    """Konfiguracja wyszukiwarki (K15 §3): pola z §D2 jawnie, opcjonalne w żądaniach."""

    kb_ids: list[str] | None = None
    doc_ids: list[str] | None = None
    similarity_threshold: float | None = None
    vector_similarity_weight: float | None = None
    use_kg: bool | None = None
    rerank_id: str | None = None
    top_k: int | None = None
    summary: bool | None = None
    chat_id: str | None = None
    llm_setting: dict[str, Any] | None = None
    chat_settingcross_languages: list[Any] | None = None
    highlight: bool | None = None
    keyword: bool | None = None
    web_search: bool | None = None
    related_search: bool | None = None
    query_mindmap: bool | None = None


class SearchCreateResult(ResponseModel):
    """Data ``searches_create`` (złoto searches--05): ``{"search_id": …}``."""

    search_id: str


class SearchListItem(ResponseModel):
    """Wiersz listy (złoto searches--09): bez ``search_config``, z danymi właściciela."""

    avatar: str | None
    create_time: int
    created_by: str
    description: str | None
    id: str
    name: str
    nickname: str | None
    status: str
    tenant_avatar: str | None
    tenant_id: str
    update_time: int


class SearchList(ResponseModel):
    """Data ``searches_list`` (złoto searches--09): wiersze + total."""

    search_apps: list[SearchListItem]
    total: int


class SearchApp(ResponseModel):
    """Szczegół ``searches_get`` (złoto searches--14): bez ``create_*``/``status``/``nickname``."""

    avatar: str | None
    created_by: str
    description: str | None
    id: str
    name: str
    search_config: dict[str, Any]
    tenant_id: str
    update_time: int


class SearchUpdateResult(ResponseModel):
    """Data ``searches_update`` (złoto searches--15): pełny wiersz z datami."""

    avatar: str | None
    create_date: str
    create_time: int
    created_by: str
    description: str | None
    id: str
    name: str
    search_config: dict[str, Any]
    status: str
    tenant_id: str
    update_date: str
    update_time: int


class SearchCreateRequest(RequestModel):
    """Ciało ``searches_create`` (§D5): ``name`` wymagane, reszta opcjonalna."""

    name: str
    description: str | None = None
    avatar: str | None = None
    search_config: SearchConfig | None = None


class SearchUpdateRequest(RequestModel):
    """Ciało ``searches_update`` (§D5): ``name`` i ``search_config`` wymagane."""

    name: str
    search_config: SearchConfig
    description: str | None = None
    avatar: str | None = None


class SearchCompletionRequest(RequestModel):
    """Ciało ``searches_completions`` (§D7, T3): ``question`` wymagane."""

    question: str
    kb_ids: list[str] | None = None


REQUEST_MODELS: tuple[type[RequestModel], ...] = (
    SearchCreateRequest,
    SearchUpdateRequest,
    SearchCompletionRequest,
)
