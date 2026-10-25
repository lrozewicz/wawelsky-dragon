"""Wspólne zależności i modele powierzchni WD admina (kontrakt WP E3-6a §0 p. 1).

Re-eksport wzorca z ``app.api.wd.integrations`` — pakiety ``users``, ``access`` i ``system``
importują stąd, żeby nie sięgać do modułów integracji bezpośrednio. ``Items[T]`` to lista bez
stron w kopercie ``{"items": [...]}`` (obok ``Page[T]`` z ``integrations/schemas.py``).
"""

from pydantic import BaseModel, Field

from app.api.wd.integrations.deps import actor_dep, require_admin, wd_responses
from app.api.wd.integrations.schemas import Envelope, Page, WdErrorResponse

__all__ = [
    "Envelope",
    "Items",
    "Page",
    "WdErrorResponse",
    "actor_dep",
    "require_admin",
    "wd_responses",
]


class Items[T](BaseModel):
    """Lista bez stronicowania: ``{"items": [...]}`` (kontrakt §0 p. 1)."""

    items: list[T] = Field(description="Elementy listy")
