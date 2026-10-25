"""Fabryka aplikacji FastAPI fake-llm (C2). Import bez efektów ubocznych — bez sieci i bez env."""

from fastapi import FastAPI

from fake_llm import chat, embeddings, models, rerank, stats
from fake_llm.errors import OpenAIError, openai_error_handler


def create_app() -> FastAPI:
    app = FastAPI(title="fake-llm")
    app.add_exception_handler(OpenAIError, openai_error_handler)
    app.include_router(models.router)
    app.include_router(embeddings.router)
    app.include_router(chat.router)
    app.include_router(rerank.router)
    app.include_router(stats.router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
