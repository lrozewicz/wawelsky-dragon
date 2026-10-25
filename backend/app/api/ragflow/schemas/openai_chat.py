"""Modele OpenAPI tras OpenAI-compat /api/v1 (K6 §4; 02-api §8.2/§9, złoto openai_compat).

Ciało 200 jest kształtu OpenAI (bez koperty RAGFlow): ``choices`` + ``usage`` wg złota
``openai___chat__completions/openai_compat--04.json``. Ramki SSE (``chat.completion.chunk``,
``data:[DONE]``) opisane w ``responses`` trasy jako ``text/event-stream``.
"""

from pydantic import Field

from app.api.ragflow.schemas.common import ResponseModel


class CompletionUsageDetails(ResponseModel):
    """Rozbicie ``usage.completion_tokens_details`` (upstream :402-406)."""

    reasoning_tokens: int = Field(description="Tokeny wszystkich wiadomości żądania")
    accepted_prediction_tokens: int = Field(description="Tokeny treści odpowiedzi")
    rejected_prediction_tokens: int = Field(description="Zawsze 0")


class CompletionUsage(ResponseModel):
    """Liczniki odpowiedzi (upstream :398-407): tokeny promptu, treści i rozumowania."""

    prompt_tokens: int = Field(description="Tokeny treści ostatniej wiadomości użytkownika")
    completion_tokens: int = Field(description="Tokeny treści odpowiedzi")
    total_tokens: int = Field(description="Suma prompt_tokens i completion_tokens")
    completion_tokens_details: CompletionUsageDetails = Field(
        description="Rozbicie tokenów odpowiedzi"
    )


class ChatCompletionMessage(ResponseModel):
    """``choices[].message`` — odpowiedź modelu."""

    role: str = Field(description="Zawsze ``assistant``")
    content: str = Field(description="Treść odpowiedzi")


class ChatCompletionChoice(ResponseModel):
    """Element ``choices`` odpowiedzi JSON (upstream :408-417)."""

    message: ChatCompletionMessage = Field(description="Odpowiedź modelu")
    logprobs: None = Field(description="Zawsze null")
    finish_reason: str = Field(description="Zawsze ``stop``")
    index: int = Field(description="Indeks wyboru, zawsze 0")


class OpenAIChatCompletion(ResponseModel):
    """Ciało 200 ``POST /openai/{chat_id}/chat/completions`` przy ``stream=false``."""

    id: str = Field(description="Id odpowiedzi: ``chatcmpl-<chat_id>``")
    object: str = Field(description="Zawsze ``chat.completion``")
    created: int = Field(description="Znacznik czasu odpowiedzi (sekundy epoki)")
    model: str = Field(description="Model odpowiedzi: ``model`` = model czatu")
    usage: CompletionUsage = Field(description="Liczniki tokenów")
    choices: list[ChatCompletionChoice] = Field(description="Odpowiedzi modelu")
