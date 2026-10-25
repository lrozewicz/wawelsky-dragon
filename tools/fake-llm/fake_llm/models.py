"""Katalog modeli fake-llm i endpoint `GET /v1/models` (K10 §2)."""

from typing import Any

from fastapi import APIRouter

MODEL_IDS: tuple[str, ...] = (
    "fake-chat",
    "fake-chat-think",
    "fake-chat-strict",
    "fake-embed-3072",
    "fake-embed-1024",
    "fake-rerank",
    "fake-vision",
    "fake-ocr",
)
CHAT_MODELS: frozenset[str] = frozenset(
    {"fake-chat", "fake-chat-think", "fake-chat-strict", "fake-vision", "fake-ocr"}
)
EMBED_DIMS: dict[str, int] = {"fake-embed-3072": 3072, "fake-embed-1024": 1024}
RERANK_MODELS: frozenset[str] = frozenset({"fake-rerank"})

# Separator aliasu modelu (C8): `<model_bazowy><ALIAS_SEP><scope>`. `~`, nie `@`, bo `@`
# jest zarezerwowany w `app.llm` na sufiks fabryki (rejestr odcina `@…` przed rozwiązaniem).
ALIAS_SEP = "~"


def base_model(model: str) -> str:
    """Nazwa bazowa modelu: usuwa sufiks aliasu `<ALIAS_SEP><scope>` (C8).

    Alias jest akceptowany wszędzie tam, gdzie nazwa bazowa (ta sama odpowiedź, wymiary,
    usage); kontrole znanych modeli robimy po tej nazwie.
    """
    return model.split(ALIAS_SEP, 1)[0]


router = APIRouter()


@router.get("/v1/models")
async def list_models() -> dict[str, Any]:
    """Lista modeli w formacie OpenAI, w kolejności MODEL_IDS."""
    return {
        "object": "list",
        "data": [
            {"id": model_id, "object": "model", "created": 0, "owned_by": "fake-llm"}
            for model_id in MODEL_IDS
        ],
    }
