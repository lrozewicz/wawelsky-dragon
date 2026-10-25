"""Modele OpenAPI ``GET /openai/{chat_id}/models`` (K6 §4; 02-api §9, rozszerzenie WD).

Kształt OpenAI (bez koperty RAGFlow) — pole ``id`` to nazwa modelu czatu.
"""

from pydantic import Field

from app.api.ragflow.schemas.common import ResponseModel


class ModelObject(ResponseModel):
    """Element ``data`` listy modeli OpenAI."""

    id: str = Field(description="Nazwa modelu czatu (models.name)")
    object: str = Field(description="Zawsze ``model``")
    owned_by: str = Field(description="Właściciel modelu: ``wawelsky-dragon``")


class OpenAIModels(ResponseModel):
    """Ciało 200 GET /openai/{chat_id}/models (02-api §9) — bez koperty ``code``."""

    object: str = Field(description="Zawsze ``list``")
    data: list[ModelObject] = Field(description="Modele dostępne dla czatu")
