"""Modele OpenAPI chats (C1, C3): szczegół/lista czatu, bulk delete i żądania CRUD."""

from typing import Any

from app.api.ragflow.normalize.chats import _ScalarFields
from app.api.ragflow.schemas.common import RequestModel, ResponseModel


class Chat(ResponseModel):
    """Szczegół czatu (chat_detail) — klucze i kolejność dosłownie ze złota v0.27.2."""

    create_date: str
    create_time: int
    dataset_ids: list[str]
    description: str
    do_refer: str
    icon: str
    id: str
    kb_names: list[str]
    language: str
    llm_id: str
    llm_setting: dict[str, Any]
    meta_data_filter: dict[str, Any]
    name: str
    prompt_config: dict[str, Any]
    prompt_type: str
    rerank_candidates_count: int
    rerank_id: str
    similarity_threshold: float
    status: str
    tenant_id: str
    tenant_llm_id: str | None
    tenant_rerank_id: str | None
    top_k: int
    top_n: int
    update_date: str
    update_time: int
    vector_similarity_weight: float


class ChatListItem(ResponseModel):
    """Wiersz listy czatów (chat_list_item) — bez pól szczegółu, z nickname/avatarem."""

    create_time: int
    dataset_ids: list[str]
    description: str
    do_refer: str
    icon: str
    id: str
    kb_names: list[str]
    language: str
    llm_id: str
    llm_setting: dict[str, Any]
    name: str
    nickname: str
    prompt_config: dict[str, Any]
    prompt_type: str
    rerank_candidates_count: int
    rerank_id: str
    similarity_threshold: float
    status: str
    tenant_avatar: str | None
    tenant_id: str
    top_k: int
    top_n: int
    update_time: int
    vector_similarity_weight: float


class ChatList(ResponseModel):
    """Data chats_list (chat_list): wiersze + total (C5)."""

    chats: list[ChatListItem]
    total: int


class BulkDeleteResult(ResponseModel):
    """Wynik usuwania masowego (C3 p. 4): errors = komunikaty usługi (list[str])."""

    success_count: int | None = None
    errors: list[str] | None = None


class CreateChatRequest(RequestModel, _ScalarFields):
    """Ciało chats_create (C4): name wymagane; pola proste dziedziczone z _ScalarFields."""

    name: str
    dataset_ids: list[str] | None = None
    llm_id: str | None = None
    rerank_id: str | None = None
    llm_setting: dict[str, Any] | None = None
    prompt_config: dict[str, Any] | None = None


class UpdateChatRequest(RequestModel, _ScalarFields):
    """Ciało chats_update/chats_replace (C4): wszystkie pola opcjonalne."""

    name: str | None = None
    dataset_ids: list[str] | None = None
    llm_id: str | None = None
    rerank_id: str | None = None
    llm_setting: dict[str, Any] | None = None
    prompt_config: dict[str, Any] | None = None


class DeleteIdsRequest(RequestModel):
    """Ciało usuwania masowego (C4): chats_delete_many i sessions_delete."""

    ids: list[str] | None = None
    delete_all: bool = False


class RelatedQuestionsRequest(RequestModel):
    """Ciało chat_recommendation i sessions_related_questions (chat_api.py:1202).

    ``search_id`` (E4-4a T4): wyszukiwarka, z której ``search_config`` bierzemy model
    i parametry generacji; brak → model domyślny tenanta.
    """

    question: str
    search_id: str | None = None


REQUEST_MODELS: tuple[type[RequestModel], ...] = (
    CreateChatRequest,
    UpdateChatRequest,
    DeleteIdsRequest,
    RelatedQuestionsRequest,
)
