"""Błędy tras WD integracji (kontrakt WP E4-3b §0 p. 9)."""

from app.core.errors import NotFound


class SourceLinkNotFound(NotFound):
    """Brak linku źródłowego dokumentu; ``slug`` niesie powód (``no_mapping``/``item_not_found``).

    Handler K3 czyta ``err.slug``, więc trasa zamienia ``LinkNotFound`` usługi na ten wyjątek,
    przekazując ``exc.reason`` jako slug (kontrakt §0 p. 9).
    """

    def __init__(self, message: str, slug: str) -> None:
        super().__init__(message)
        self.slug = slug
