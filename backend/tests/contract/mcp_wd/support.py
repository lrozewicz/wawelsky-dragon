"""Stałe i typy wspólne testów MCP (K17 §1, SC-E6-2-01).

Wydzielone z ``conftest.py`` (MINOR T1): stałe i ``McpStack`` importuje zarówno
``conftest.py``, jak i pliki testów — wspólny moduł gwarantuje jeden import,
bez względu na to, pod jaką nazwą pytest ładuje ``conftest``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import httpx

# K17 §3/§4 — dokładnie trzy narzędzia upstream i pytanie scenariusza SC-E6-2-01.
EXPECTED_TOOLS = ("ragflow_list_chats", "ragflow_list_datasets", "ragflow_retrieval")
DATASET_NAME = "wd_sc_e6_2_ds_a"
DOCUMENT_NAME = "ludnosc.txt"
DOCUMENT_TEXT = "Liczba ludności Polski wynosiła 38 mln.\n"
QUESTION = "Jaka była liczba ludności Polski?"
EXPECTED_MARKER = "ludności"

# Konto B i jego dataset (SC-E6-2-03): zasoby odizolowane od datasetu A użytkownika A.
B_DATASET_NAME = "wd_sc_e6_2_ds_b"
B_DOCUMENT_NAME = "bydgoszcz.txt"
B_DOCUMENT_TEXT = "Bydgoszcz leży nad rzeką Brdą.\n"
B_QUESTION = "Nad jaką rzeką leży Bydgoszcz?"
B_MARKER = "Brdą"

# Czat użytkownika A — krok `ragflow_list_chats` złota (`mcp--10`/`--24`) wymaga niepustej listy.
CHAT_NAME = "wd_sc_e6_2_chat"

HTTP_TIMEOUT_S = 60.0
MCP_READY_TIMEOUT_S = 30.0
MCP_READY_INTERVAL_S = 0.5
PARSE_TIMEOUT_S = 600.0
PARSE_INTERVAL_S = 2.0
LOG_TAIL_LINES = 200

# Konto zakładane przez ``McpStack.register_user`` (scenariusze z drugim użytkownikiem).
USER_PASSWORD = "wd-mcp-user-1"  # noqa: S105 — stała testowa, nie sekret


def ingest_dataset(
    api_base: str,
    api_key: str,
    *,
    dataset_name: str,
    document_name: str,
    text: str,
) -> str:
    """Tworzy dataset z jednym dokumentem i czeka na ``run == DONE``; zwraca id datasetu.

    Wspólne dla datasetu A (``mcp_stack``) i datasetu B (SC-E6-2-03): ingestia przez publiczne
    API WD, embeddings z fake-llm (jak w pozostałych testach kontraktowych).
    """
    headers = {"Authorization": f"Bearer {api_key}"}
    with httpx.Client(base_url=api_base, headers=headers, timeout=HTTP_TIMEOUT_S) as client:
        created = client.post("/datasets", json={"name": dataset_name})
        created.raise_for_status()
        dataset_id = str(created.json()["data"]["id"])

        uploaded = client.post(
            f"/datasets/{dataset_id}/documents",
            files={"file": (document_name, text.encode("utf-8"), "text/plain")},
        )
        uploaded.raise_for_status()
        document_id = str(uploaded.json()["data"][0]["id"])

        parsed = client.post(
            f"/datasets/{dataset_id}/documents/parse", json={"document_ids": [document_id]}
        )
        parsed.raise_for_status()

        deadline = time.monotonic() + PARSE_TIMEOUT_S
        while True:
            listing = client.get(
                f"/datasets/{dataset_id}/documents", params={"page": 1, "page_size": 30}
            )
            listing.raise_for_status()
            docs = listing.json()["data"]["docs"]
            run = docs[0]["run"] if docs else None
            if run == "DONE":
                return dataset_id
            if run in {"FAIL", "CANCEL"}:
                raise RuntimeError(f"parsowanie dokumentu {document_id}: run={run}")
            if time.monotonic() >= deadline:
                raise RuntimeError(f"parsowanie niedokończone po {PARSE_TIMEOUT_S} s (run={run})")
            time.sleep(PARSE_INTERVAL_S)


def create_chat(api_base: str, api_key: str, name: str) -> str:
    """Zakłada czat (``POST /chats``) i zwraca jego id — dla kroków ``ragflow_list_chats``."""
    with httpx.Client(
        base_url=api_base,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=HTTP_TIMEOUT_S,
    ) as client:
        created = client.post("/chats", json={"name": name, "dataset_ids": []})
        created.raise_for_status()
        body = created.json()
        if body.get("code") != 0:
            raise RuntimeError(f"POST /chats: code={body.get('code')}: {body.get('message')}")
        return str(body["data"]["id"])


@dataclass(frozen=True)
class McpStack:
    """Działający stos MCP: serwer MCP + API WD z datasetem użytkownika A."""

    api_base: str  # root API WD (…/api/v1)
    mcp_url: str  # streamable HTTP MCP, np. http://127.0.0.1:9382/mcp
    api_key: str  # klucz API użytkownika A (konto admina z resetu K9)
    dataset_id: str
    mcp_pid: int  # pid podprocesu ``python -m app.mcp`` (SC-E6-2-07: pomiar RSS)
    log_dir: Path

    def register_user(self, nickname: str) -> str:
        """Zakłada konto (``POST /users``) i zwraca jego klucz API (``POST /system/tokens``).

        Dla scenariuszy z drugim użytkownikiem (SC-E6-2-03) i mutacji k17 (b).
        """
        email = f"{nickname}@wd.test"
        with httpx.Client(base_url=self.api_base, timeout=HTTP_TIMEOUT_S) as client:
            registered = client.post(
                "/users", json={"email": email, "nickname": nickname, "password": USER_PASSWORD}
            )
            registered.raise_for_status()
            logged_in = client.post("/auth/login", json={"email": email, "password": USER_PASSWORD})
            logged_in.raise_for_status()
            auth = logged_in.headers.get("Authorization")
            if not auth:
                raise RuntimeError(f"auth/login ({email}): brak nagłówka Authorization")
            tokens = client.post("/system/tokens", headers={"Authorization": auth})
            tokens.raise_for_status()
            token = tokens.json()["data"]["token"]
        return str(token)
