"""Wyjątki warstwy SharePoint (Microsoft Graph) — bez zależności od httpx (WP E4-2a)."""


class GraphAuthError(Exception):
    """Błąd uwierzytelnienia Graph; `description` nigdy nie zawiera sekretu ani tokenu."""

    description: str

    def __init__(self, description: str) -> None:
        super().__init__(description)
        self.description = description


class GraphError(Exception):
    """Błąd odpowiedzi Graph; `status == 0` to błąd logiczny bez statusu HTTP."""

    status: int
    code: str
    message: str

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message


class GraphNotFound(GraphError):
    """Zasób nie istnieje (HTTP 404) albo wymaga resyncu (HTTP 410)."""


class SizeLimitExceeded(Exception):
    """Pobierany plik przekroczył dopuszczalny rozmiar w bajtach."""

    max_bytes: int

    def __init__(self, max_bytes: int) -> None:
        super().__init__(f"size limit exceeded: {max_bytes} bytes")
        self.max_bytes = max_bytes
