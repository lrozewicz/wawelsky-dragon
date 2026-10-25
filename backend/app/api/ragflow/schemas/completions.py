"""Modele OpenAPI completions (C1, C3 p. 5; K4 §1.2/§1.7): CompletionData i żądanie."""

from typing import Any

from pydantic import Field

from app.api.ragflow.schemas.common import DocAgg, RequestModel, ResponseModel


class ReferenceChunk(ResponseModel):
    """ChunkRef (K4 §1.2, chunk_ref) — klucze i kolejność dosłownie; row_id zawsze None."""

    id: str
    content: str
    document_id: str
    document_name: str
    dataset_id: str
    image_id: str
    positions: list[list[int]]
    url: str | None
    similarity: float
    vector_similarity: float
    term_similarity: float
    row_id: None
    doc_type: str
    document_metadata: dict[str, Any] | None


class CompletionReference(ResponseModel):
    """Referencja R (K4 §1.2): ramki delt mają tylko ``chunks``; JSON — pełne R."""

    chunks: list[ReferenceChunk]
    doc_aggs: list[DocAgg] | None = None
    total: int | None = None


class CompletionData(ResponseModel):
    """data JSON (K4 §1.7) i data ramek SSE (K4 §1.2) — poza ramką błędu i terminatorem."""

    answer: str
    reference: CompletionReference
    audio_binary: None
    id: str
    session_id: str
    prompt: str | None = None
    created_at: float | None = None
    chat_id: str | None = None
    thinking: str | None = None
    final: bool | None = None
    start_to_think: bool | None = None
    end_to_think: bool | None = None


class CompletionRequest(RequestModel):
    """Jeden model obu tras completions (C4): pola natywne, RESTful i generowania."""

    question: str | None = None
    session_id: str | None = None
    conversation_id: str | None = Field(default=None, description="alias session_id")
    messages: list[dict[str, Any]] | None = None
    chat_id: str | None = None
    stream: bool = True
    legacy: bool = False
    quote: bool = True
    reasoning: bool = False
    llm_id: str | None = None
    doc_ids: str | list[str] | None = None
    metadata_condition: dict[str, Any] | None = None
    pass_all_history_messages: bool = False
    pass_all_history: bool = Field(default=False, description="alias pass_all_history_messages")
    store_history_messages: bool = True
    store_history: bool = Field(default=True, description="alias store_history_messages")
    temperature: float | None = None
    temperatureEnabled: bool | None = None
    temperature_enabled: bool | None = None
    top_p: float | None = None
    topPEnabled: bool | None = None
    top_p_enabled: bool | None = None
    frequency_penalty: float | None = None
    frequencyPenaltyEnabled: bool | None = None
    frequency_penalty_enabled: bool | None = None
    presence_penalty: float | None = None
    presencePenaltyEnabled: bool | None = None
    presence_penalty_enabled: bool | None = None
    max_tokens: int | None = None
    maxTokensEnabled: bool | None = None
    max_tokens_enabled: bool | None = None


class AskRequest(RequestModel):
    """Ciało ``POST /api/v1/sessions/ask`` v0.24 (C4, upstream ``ask_about``) — tylko OpenAPI."""

    question: str = Field(description="Pytanie użytkownika")
    dataset_ids: list[str] = Field(description="Id datasetów, nad którymi pytamy")


class OpenAIChatCompletionRequest(RequestModel):
    """Ciało POST /openai/{chat_id}/chat/completions (02-api §9; upstream :243-268).

    ``model`` = ``"model"`` znaczy „model czatu”; inna nazwa musi istnieć w rejestrze
    (inaczej ``code 101``, złoto ``openai_dify--10.json``). ``stream`` obsługiwany jak
    na trasach natywnych (K4 §1).
    """

    model: str = Field(description="Model: „model” = model czatu")
    messages: list[dict[str, Any]] = Field(description="Wiadomości OpenAI (ostatnia od user)")
    stream: bool = Field(default=False, description="False → JSON, True → SSE")
    extra_body: dict[str, Any] | None = Field(
        default=None, description="reference, reference_metadata, metadata_condition"
    )


REQUEST_MODELS: tuple[type[RequestModel], ...] = (
    AskRequest,
    CompletionRequest,
    OpenAIChatCompletionRequest,
)
