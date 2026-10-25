"""Modele pydantic tras dostępów WD (zadanie T4 — kontrakt E3-6a §3).

E-maile normalizuje trasa (``strip().lower()``), a ``chat_ids`` deduplikuje usługa —
dlatego ``AccessReplaced.count`` to liczba unikalnych czatów, nie długość listy z żądania.
"""

from pydantic import BaseModel, Field


class AssistantGrant(BaseModel):
    """Grant czatu w odpowiedzi WD (kontrakt §3)."""

    chat_id: str = Field(description="Identyfikator czatu")
    created_by: str | None = Field(description="Kto nadał grant")
    created_at: str | None = Field(description="Czas nadania grantu (ISO 8601)")


class AccessReplaceRequest(BaseModel):
    """Ciało ``PUT /access/assistants`` — cały nowy zbiór grantów (kontrakt §3)."""

    email: str = Field(min_length=1, description="E-mail użytkownika")
    chat_ids: list[str] = Field(description="Identyfikatory czatów (duplikaty są usuwane)")


class AccessReplaced(BaseModel):
    """Wynik ``PUT /access/assistants`` (kontrakt §3)."""

    email: str = Field(description="E-mail użytkownika (znormalizowany)")
    count: int = Field(description="Liczba unikalnych grantów po zastąpieniu")


class AccessGrantRequest(BaseModel):
    """Ciało ``POST``/``DELETE /access/assistants`` — pojedynczy grant (kontrakt §3)."""

    email: str = Field(min_length=1, description="E-mail użytkownika")
    chat_id: str = Field(min_length=1, description="Identyfikator czatu")


class AssistantGrantRef(BaseModel):
    """Wynik ``POST /access/assistants`` (kontrakt §3)."""

    email: str = Field(description="E-mail użytkownika (znormalizowany)")
    chat_id: str = Field(description="Identyfikator nadanego czatu")
