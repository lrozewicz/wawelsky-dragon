"""Klient HTTP API WD dla serwera MCP (port `mcp/server/server.py`, klasa ``RAGFlowConnector``)."""

# Port z RAGFlow v0.27.2 mcp/server/server.py (klasa RAGFlowConnector).
# Apache-2.0, InfiniFlow; zob. NOTICE.

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from mcp import types

# K17 §4: limit strony API WD (jak upstream RAGFlowConnector._REST_API_MAX_PAGE_SIZE).
_REST_API_MAX_PAGE_SIZE = 100
_HTTP_OK = 200
_CANNOT_PROCESS = "Cannot process this operation."


def _message_of(response: httpx.Response) -> str | None:
    """Komunikat ``message`` z koperty API WD; ``None``, gdy ciało nie jest JSON-em."""
    try:
        body = response.json()
    except ValueError:
        return None
    if isinstance(body, dict):
        message = body.get("message")
        if isinstance(message, str) and message:
            return message
    return None


def _api_error(message: str | None, default: str) -> Exception:
    """Wyjątek z komunikatem tekstowym MCP (kształt jak upstream: ``Exception([TextContent])``)."""
    return Exception([types.TextContent(type="text", text=message or default)])


class ApiConnector:
    """Klient HTTP API WD (port ``RAGFlowConnector``).

    Cała komunikacja idzie po HTTP do ``api_base`` z kluczem klienta w nagłówku
    ``Authorization: Bearer …`` podanym **per wywołanie** (żadnego klucza globalnego).
    Brak cache'u odpowiedzi między żądaniami (K17: model uprawnień jak klient REST).
    """

    def __init__(self, api_base: str) -> None:
        self.api_base = api_base.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(60.0))
        return self._client

    async def close(self) -> None:
        """Zamyka wspólny klient HTTP (wołane przy zamykaniu serwera MCP)."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get(
        self, path: str, params: dict[str, Any] | None, *, api_key: str
    ) -> httpx.Response:
        client = await self._get_client()
        return await client.get(
            url=self.api_base + path,
            params=params,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def _post(self, path: str, payload: dict[str, Any], *, api_key: str) -> httpx.Response:
        client = await self._get_client()
        return await client.post(
            url=self.api_base + path,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def _fetch_datasets_page(
        self,
        *,
        api_key: str,
        page: int,
        page_size: int,
        orderby: str,
        desc: bool,
    ) -> dict[str, Any]:
        """Jedna strona ``GET /datasets`` (koperta API WD)."""
        params: dict[str, Any] = {
            "page": page,
            "page_size": page_size,
            "orderby": orderby,
            "desc": desc,
        }
        res = await self._get("/datasets", params, api_key=api_key)
        if res.status_code != _HTTP_OK:
            raise _api_error(_message_of(res), _CANNOT_PROCESS)
        body: dict[str, Any] = res.json()
        if body.get("code") != 0:
            raise _api_error(body.get("message"), _CANNOT_PROCESS)
        return body

    async def _fetch_all_datasets(
        self, *, api_key: str, orderby: str = "create_time", desc: bool = True
    ) -> list[dict[str, Any]]:
        """Wszystkie dostępne datasety, strona po stronie (bez przekroczenia limitu API)."""
        datasets: list[dict[str, Any]] = []
        page = 1
        while True:
            body = await self._fetch_datasets_page(
                api_key=api_key,
                page=page,
                page_size=_REST_API_MAX_PAGE_SIZE,
                orderby=orderby,
                desc=desc,
            )
            page_datasets: list[dict[str, Any]] = body.get("data", [])
            if not page_datasets:
                break
            datasets.extend(page_datasets)
            total = body.get("total_datasets", body.get("total"))
            if total is not None and len(datasets) >= total:
                break
            page += 1
        return datasets

    async def list_datasets(
        self,
        *,
        api_key: str,
        page: int = 1,
        page_size: int = -1,
        orderby: str = "create_time",
        desc: bool = True,
    ) -> str:
        """Dostępne datasety jako linie JSON (do opisu narzędzia i wyniku ``list_datasets``)."""
        if page_size == -1:
            datasets = await self._fetch_all_datasets(api_key=api_key, orderby=orderby, desc=desc)
        else:
            size = min(page_size, _REST_API_MAX_PAGE_SIZE)
            body = await self._fetch_datasets_page(
                api_key=api_key, page=page, page_size=size, orderby=orderby, desc=desc
            )
            datasets = body["data"]
        return "\n".join(
            json.dumps(
                {
                    "id": data["id"],
                    "name": data.get("name"),
                    "description": data.get("description"),
                },
                ensure_ascii=False,
            )
            for data in datasets
        )

    async def list_chats(
        self,
        *,
        api_key: str,
        page: int = 1,
        page_size: int = 30,
        orderby: str = "create_time",
        desc: bool = True,
    ) -> str:
        """Dostępne asystenty jako linie JSON (do opisu narzędzia i wyniku ``list_chats``)."""
        params = {
            "page": page,
            "page_size": page_size,
            "orderby": orderby,
            "desc": json.dumps(desc),
        }
        res = await self._get("/chats", params, api_key=api_key)
        if res.status_code != _HTTP_OK:
            raise _api_error(_message_of(res), "Cannot list chats.")
        body: dict[str, Any] = res.json()
        if body.get("code") != 0:
            raise _api_error(body.get("message"), "Cannot list chats.")
        chats: Any = body.get("data", [])
        if isinstance(chats, dict):
            chats = chats.get("chats", [])
        return "\n".join(
            json.dumps(
                {
                    "id": data.get("id"),
                    "name": data.get("name"),
                    "description": data.get("description", ""),
                },
                ensure_ascii=False,
            )
            for data in chats
        )

    async def resolve_dataset_ids(self, *, api_key: str) -> list[str]:
        """Wszystkie dostępne id datasetów (fallback ``ragflow_retrieval`` bez ``dataset_ids``)."""
        datasets = await self._fetch_all_datasets(api_key=api_key)
        resolved = list(dict.fromkeys(data["id"] for data in datasets if data.get("id")))
        logging.info("resolve_dataset_ids resolved %s accessible dataset IDs", len(resolved))
        return resolved

    async def _dataset_metadata(self, dataset_id: str, *, api_key: str) -> dict[str, Any] | None:
        """Nazwa i opis datasetu (``None``, gdy API nie zwróci rekordu)."""
        res = await self._get("/datasets", {"id": dataset_id, "page_size": 1}, api_key=api_key)
        if res.status_code != _HTTP_OK:
            return None
        body: dict[str, Any] = res.json()
        if body.get("code") != 0 or not body.get("data"):
            return None
        info = body["data"][0]
        return {"name": info.get("name", "Unknown"), "description": info.get("description", "")}

    async def _documents_metadata(
        self, dataset_id: str, *, api_key: str
    ) -> dict[str, dict[str, Any]]:
        """Metadane dokumentów datasetu (id → metadane); ``{}``, gdy API zawiedzie."""
        documents: dict[str, dict[str, Any]] = {}
        page = 1
        page_size = 30
        while True:
            res = await self._get(
                f"/datasets/{dataset_id}/documents",
                {"page": page, "page_size": page_size},
                api_key=api_key,
            )
            if res.status_code != _HTTP_OK:
                return {}
            body: dict[str, Any] = res.json()
            if body.get("code") != 0:
                return {}
            page_docs: list[dict[str, Any]] = body.get("data", {}).get("docs") or []
            for doc in page_docs:
                doc_id = doc.get("id")
                if not doc_id:
                    continue
                documents[doc_id] = {
                    "document_id": doc_id,
                    "name": doc.get("name", ""),
                    "location": doc.get("location", ""),
                    "type": doc.get("type", ""),
                    "size": doc.get("size"),
                    "chunk_count": doc.get("chunk_count"),
                    "create_date": doc.get("create_date", ""),
                    "update_date": doc.get("update_date", ""),
                    "token_count": doc.get("token_count"),
                    "thumbnail": doc.get("thumbnail", ""),
                    "dataset_id": doc.get("dataset_id", dataset_id),
                    "meta_fields": doc.get("meta_fields", {}),
                }
            # Strona krótsza niż ``page_size`` (także pusta) jest ostatnia —
            # kończy zbiory wyczerpane/puste, bez zapętlenia na tej samej stronie.
            if len(page_docs) < page_size:
                break
            page += 1
        return documents

    async def _document_metadata(
        self, dataset_ids: list[str], *, api_key: str
    ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        """Metadane dokumentów i datasetów pobrane na świeżo dla tego żądania (bez cache)."""
        document_cache: dict[str, dict[str, Any]] = {}
        dataset_cache: dict[str, dict[str, Any]] = {}
        for dataset_id in dataset_ids:
            dataset_meta = await self._dataset_metadata(dataset_id, api_key=api_key)
            if dataset_meta:
                dataset_cache[dataset_id] = dataset_meta
            document_cache.update(await self._documents_metadata(dataset_id, api_key=api_key))
        return document_cache, dataset_cache

    def _map_chunk_fields(
        self,
        chunk_data: dict[str, Any],
        dataset_cache: dict[str, dict[str, Any]],
        document_cache: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """Zachowuje pola API i dokłada metadane datasetu/dokumentu (jak upstream)."""
        mapped = dict(chunk_data)
        dataset_id = chunk_data.get("dataset_id") or chunk_data.get("kb_id")
        if dataset_id and dataset_id in dataset_cache:
            mapped["dataset_name"] = dataset_cache[dataset_id]["name"]
        else:
            mapped["dataset_name"] = "Unknown"
        mapped["document_name"] = chunk_data.get("document_keyword", "")
        document_id = chunk_data.get("document_id")
        if document_id and document_id in document_cache:
            mapped["document_metadata"] = document_cache[document_id]
        return mapped

    async def retrieval(  # noqa: PLR0913 — sygnatura narzędzia ragflow_retrieval z upstream (K17 §4)
        self,
        *,
        api_key: str,
        dataset_ids: list[str],
        document_ids: list[str] | None = None,
        question: str = "",
        page: int = 1,
        page_size: int = 30,
        similarity_threshold: float = 0.2,
        vector_similarity_weight: float = 0.3,
        top_k: int = 1024,
        rerank_id: str | None = None,
        keyword: bool = False,
        force_refresh: bool = False,
    ) -> list[types.TextContent]:
        """``POST /retrieval`` i zbudowanie odpowiedzi MCP (K17 §4).

        ``force_refresh`` przyjmowane dla zgodności schematu narzędzia; metadane i tak
        są pobierane na świeżo przy każdym żądaniu (brak cache między żądaniami).
        """
        if document_ids is None:
            document_ids = []
        if not dataset_ids:
            dataset_ids = await self.resolve_dataset_ids(api_key=api_key)
            if not dataset_ids:
                raise _api_error("No accessible datasets found.", _CANNOT_PROCESS)

        payload: dict[str, Any] = {
            "page": page,
            "page_size": page_size,
            "similarity_threshold": similarity_threshold,
            "vector_similarity_weight": vector_similarity_weight,
            "top_k": top_k,
            "rerank_id": rerank_id,
            "keyword": keyword,
            "question": question,
            "dataset_ids": dataset_ids,
            "document_ids": document_ids,
        }
        res = await self._post("/retrieval", payload, api_key=api_key)
        if res.status_code != _HTTP_OK:
            raise _api_error(_CANNOT_PROCESS, _CANNOT_PROCESS)
        body: dict[str, Any] = res.json()
        if body.get("code") != 0:
            raise _api_error(body.get("message"), _CANNOT_PROCESS)

        data = body["data"]
        document_cache, dataset_cache = await self._document_metadata(dataset_ids, api_key=api_key)
        chunks = [
            self._map_chunk_fields(chunk, dataset_cache, document_cache)
            for chunk in data.get("chunks", [])
        ]
        total = data.get("total", len(chunks))
        response = {
            "chunks": chunks,
            "pagination": {
                "page": data.get("page", page),
                "page_size": data.get("page_size", page_size),
                "total_chunks": total,
                "total_pages": (total + page_size - 1) // page_size,
            },
            "query_info": {
                "question": question,
                "similarity_threshold": similarity_threshold,
                "vector_weight": vector_similarity_weight,
                "keyword_search": keyword,
                "dataset_count": len(dataset_ids),
            },
        }
        return [types.TextContent(type="text", text=json.dumps(response, ensure_ascii=False))]
