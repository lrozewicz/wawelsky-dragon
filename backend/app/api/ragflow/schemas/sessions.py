"""Modele OpenAPI sessions (C1, C3): sesja czatu, wiadomości i żądania create/rename."""

from app.api.ragflow.schemas.common import RequestModel, ResponseModel
from app.api.ragflow.schemas.completions import CompletionReference


class SessionMessage(ResponseModel):
    """Wiadomość sesji (_message): prologue bez id, user bez created_at (C5)."""

    role: str
    content: str
    id: str | None = None
    created_at: float | None = None
    thumbup: bool | None = None
    feedback: str | None = None


class Session(ResponseModel):
    """Sesja czatu (session_detail) — avatar tylko w odpowiedzi GET jednej sesji."""

    chat_id: str
    create_date: str
    create_time: int
    id: str
    messages: list[SessionMessage]
    name: str
    reference: list[CompletionReference]
    update_date: str
    update_time: int
    user_id: str | None
    avatar: str | None = None


class CreateSessionRequest(RequestModel):
    """Ciało sessions_create (C4, chat_api.py:845): name ma domyślną "New session"."""

    name: str = "New session"


class RenameSessionRequest(RequestModel):
    """Ciało sessions_rename/legacy (C4): name None → bez zmiany nazwy."""

    name: str | None = None


class MessageFeedbackRequest(RequestModel):
    """Ciało sessions_message_feedback (C4, chat_api.py:1034): thumbup wymagany, typu bool."""

    thumbup: bool
    feedback: str | None = None


REQUEST_MODELS: tuple[type[RequestModel], ...] = (
    CreateSessionRequest,
    RenameSessionRequest,
    MessageFeedbackRequest,
)
