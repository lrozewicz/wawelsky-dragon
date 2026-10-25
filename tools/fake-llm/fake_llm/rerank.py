"""Endpoint `POST /v1/rerank` — scoring i format odpowiedzi LiteLLM/Cohere (K10 §5, C6)."""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from fake_llm.errors import model_not_found
from fake_llm.models import RERANK_MODELS, base_model
from fake_llm.tokens import tokenize

router = APIRouter()


class RerankDocument(BaseModel):
    """Dokument wejściowy reranku."""

    text: str


class RerankRequest(BaseModel):
    """Ciało żądania `POST /v1/rerank`."""

    model: str
    query: str
    documents: list[str | RerankDocument]
    top_n: int | None = Field(default=None, ge=1)


def rerank_scores(query: str, documents: list[str]) -> list[tuple[int, float]]:
    """Punktacja dokumentów: |tokeny(query) ∩ tokeny(doc)| / max(1, |tokeny(query)|).

    Sortowanie malejąco po wyniku, remisy rosnąco po indeksie.
    """
    query_tokens = set(tokenize(query))
    scored = [
        (index, len(query_tokens & set(tokenize(document))) / max(1, len(query_tokens)))
        for index, document in enumerate(documents)
    ]
    return sorted(scored, key=lambda result: (-result[1], result[0]))


@router.post("/v1/rerank")
async def rerank(request: RerankRequest) -> dict[str, Any]:
    """Rerank dokumentów względem zapytania; walidacja modelu przed wszystkim innym (C2 [R-2]).

    Alias `<model>~<scope>` akceptowany jak baza (C8).
    """
    if base_model(request.model) not in RERANK_MODELS:
        raise model_not_found(request.model)
    texts = [
        document if isinstance(document, str) else document.text for document in request.documents
    ]
    scored = rerank_scores(request.query, texts)
    if request.top_n is not None:
        scored = scored[: request.top_n]
    return {
        "id": "fake-rerank",
        "results": [{"index": index, "relevance_score": score} for index, score in scored],
        "meta": {},
    }
