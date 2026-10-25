"""Rejestracja tras /api/v1 ragflow (C8) — stuby, wypełnienie w E1-9a/9b."""

from fastapi import FastAPI

from app.api.ragflow.routes import (
    chats,
    chunks,
    completions,
    dataset_ingestions,
    dataset_metadata,
    datasets,
    dify,
    documents,
    documents_extra,
    documents_files,
    file_legacy,
    files,
    legacy_v024,
    legacy_v1,
    openai_chat,
    openai_models,
    provider_instances,
    provider_models,
    recommendation,
    retrieval,
    searches,
    sessions,
)


def include_ragflow_routes(app: FastAPI) -> None:
    """Dołącza routery /api/v1: siedem z C8 + extras E2-1 (ingestia, metadane, dokumenty,
    czat, pliki dokumentów, OpenAI/Dify).

    ``documents_files`` przed ``documents_extra`` i ``documents``: ``/documents/images/{id}``
    i ``/thumbnails`` muszą trafić przed ``/documents/{document_id}``, a
    ``PATCH …/documents/metadatas`` przed ``PATCH …/documents/{document_id}``
    (dopasowanie tras po kolejności); ``recommendation`` po ``sessions``: /chat/recommendation
    i alias /sessions/related_questions; ``searches`` po ``recommendation`` i przed
    ``completions`` (CONTRACT E4-4a §D6): /searches/… nie koliduje z żadną wcześniejszą trasą;
    ``files`` po ``searches`` i przed ``completions`` (CONTRACT E4-5a §D5): własny router
    ``/files*`` trzyma ``/files/move`` i ``/files/link-to-datasets`` przed ``/files/{file_id}``;
    ``file_legacy`` zaraz po ``files`` (CONTRACT E4-5b §D0): legacy ``/api/v1/file/*``
    rozgałęzia po profilu do tras ``files`` i jest poza schematem OpenAPI
    (``include_in_schema=False``), więc nie zmienia schematu;
    ``openai_chat`` po ``completions``:
    /openai/{chat_id}/chat/completions i alias /chats_openai/… nie kolidują z żadną
    wcześniejszą trasą; ``dify`` i ``openai_models`` na końcu: ścieżki
    ``/dify/…`` i ``/openai/{chat_id}/models`` nie kolidują z żadną wcześniejszą trasą.
    Na końcu krotki ``legacy_v1`` (``/v1``, poza schematem OpenAPI) i ``legacy_v024``
    (``/api/v1``, trasy tylko-v0.24 dojdą w E2-2b) — oba na razie puste, więc nie
    zmieniają schematu (K11 §10d p. 18-19, CONTRACT C6).

    ``provider_instances`` i ``provider_models`` (K13 §3) na początku krotki: ``main``
    rejestruje ``routes.models`` bezpośrednio przed tym wywołaniem, więc trasy instancji
    i modeli instancji lądują zaraz po trasach ``models`` (CONTRACT E3-6b §T1).
    """
    for module in (
        provider_instances,
        provider_models,
        datasets,
        dataset_ingestions,
        dataset_metadata,
        documents_files,
        documents_extra,
        documents,
        chunks,
        retrieval,
        chats,
        sessions,
        recommendation,
        searches,
        files,
        file_legacy,
        completions,
        openai_chat,
        dify,
        openai_models,
        legacy_v1,
        legacy_v024,
    ):
        app.include_router(module.router)
