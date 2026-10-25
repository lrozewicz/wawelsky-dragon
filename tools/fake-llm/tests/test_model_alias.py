"""Testy aliasu modelu ``<model>~<scope>`` — ta sama odpowiedź jak baza (C8, E6-3f T6).

Alias jest akceptowany wszędzie tam, gdzie nazwa bazowa: chat/embeddings/rerank zwracają
tę samą treść, wymiary i ``usage``; ``GET /v1/models`` pozostaje bez zmian. Nieznana baza
(``nieznany~x``) → 404, jak dotąd. Separator ``~`` zamiast ``@`` (odstępstwo od §C8 —
``@`` jest zarezerwowany w ``app.llm`` na sufiks fabryki, patrz raport).
"""

import httpx

from fake_llm.embeddings import embed
from fake_llm.models import MODEL_IDS

HTTP_OK = 200
HTTP_NOT_FOUND = 404
DIM_1024 = 1024
EMBED_MODEL = "fake-embed-1024"
CHAT_MODEL = "fake-chat"
RERANK_MODEL = "fake-rerank"
UNKNOWN_BASE = "nieznany"
SEP = "~"
CHAT_TEXT = "Odpowiedź testowa: pytanie"


def _chat_body(model: str) -> dict[str, object]:
    return {"model": model, "messages": [{"role": "user", "content": "pytanie"}]}


async def test_embedding_alias_matches_base(client: httpx.AsyncClient) -> None:
    """Embedding z aliasem: 1024 wymiary, identyczny wektor i ``usage`` jak baza, model = alias."""
    alias = f"{EMBED_MODEL}{SEP}abc"
    payload = {"input": "umowa najmu"}
    base = await client.post("/v1/embeddings", json={"model": EMBED_MODEL, **payload})
    alias_response = await client.post("/v1/embeddings", json={"model": alias, **payload})
    assert base.status_code == HTTP_OK
    assert alias_response.status_code == HTTP_OK
    body = alias_response.json()
    assert len(body["data"][0]["embedding"]) == DIM_1024
    assert body["data"][0]["embedding"] == base.json()["data"][0]["embedding"]
    assert body["usage"] == base.json()["usage"]
    assert body["model"] == alias
    assert body["data"][0]["embedding"] == embed(EMBED_MODEL, "umowa najmu")


async def test_chat_alias_matches_base(client: httpx.AsyncClient) -> None:
    """Czat z aliasem ``fake-chat~x`` odpowiada treścią jak ``fake-chat``; ``model`` = alias."""
    alias = f"{CHAT_MODEL}{SEP}x"
    base = await client.post("/v1/chat/completions", json=_chat_body(CHAT_MODEL))
    alias_response = await client.post("/v1/chat/completions", json=_chat_body(alias))
    assert base.status_code == HTTP_OK
    assert alias_response.status_code == HTTP_OK
    body = alias_response.json()
    assert body["choices"][0]["message"]["content"] == CHAT_TEXT
    assert (
        body["choices"][0]["message"]["content"] == base.json()["choices"][0]["message"]["content"]
    )
    assert body["model"] == alias


async def test_rerank_alias_matches_base(client: httpx.AsyncClient) -> None:
    """Rerank z aliasem ``fake-rerank~z`` zwraca ten sam wynik co baza."""
    alias = f"{RERANK_MODEL}{SEP}z"
    payload = {"query": "umowa", "documents": ["umowa najmu", "prognoza pogody"]}
    base = await client.post("/v1/rerank", json={"model": RERANK_MODEL, **payload})
    alias_response = await client.post("/v1/rerank", json={"model": alias, **payload})
    assert base.status_code == HTTP_OK
    assert alias_response.status_code == HTTP_OK
    assert alias_response.json()["results"] == base.json()["results"]


async def test_unknown_base_alias_is_not_found(client: httpx.AsyncClient) -> None:
    """Alias nieznanej bazy ``nieznany~x`` → 404 z kodem ``model_not_found``."""
    response = await client.post(
        "/v1/embeddings", json={"model": f"{UNKNOWN_BASE}{SEP}x", "input": "a"}
    )
    assert response.status_code == HTTP_NOT_FOUND
    assert response.json()["error"]["code"] == "model_not_found"


async def test_unknown_base_alias_is_not_found_in_chat(client: httpx.AsyncClient) -> None:
    """Alias nieznanej bazy w czacie → 404 (baza, nie alias, decyduje o istnieniu)."""
    response = await client.post("/v1/chat/completions", json=_chat_body(f"{UNKNOWN_BASE}{SEP}x"))
    assert response.status_code == HTTP_NOT_FOUND
    assert response.json()["error"]["code"] == "model_not_found"


async def test_models_list_is_unchanged(client: httpx.AsyncClient) -> None:
    """``GET /v1/models`` nie zawiera aliasów — lista bazowa bez zmian (C8)."""
    response = await client.get("/v1/models")
    assert response.status_code == HTTP_OK
    ids = [item["id"] for item in response.json()["data"]]
    assert ids == list(MODEL_IDS)
