"""Przepływ testu kształtów: auth/users/system/chats/sessions/completions (T3; C4.2)."""

import time
import uuid
from typing import Any

import httpx

from tests.integration.api.openapi_shapes import check, check_raw, check_sse

# Limit oczekiwania na parsowanie wawel.txt (brief T3 p. 3a).
_PARSE_TIMEOUT_S = 300.0
_QUESTION = "smok wawelski"
# Nazwa-placeholder modelu OpenAI-compat: „model” znaczy „model czatu” (golden openai_compat).
PLACEHOLDER = "model"
# Tekst pliku zasiewu: ≥ 300 bajtów o smoku wawelskim (brief T3 p. 3a).
_WAWEL_TXT = (
    "Smok wawelski mieszkał w jaskini pod wzgórzem wawelskim nad Wisłą. "
    "Każdego dnia porywał bydło, a wieśniacy bali się zbliżać do jaskini. "
    "Rycerz Dratewka napełnił skórę siarką i podał smokowi na śniadanie. "
    "Smok wypił wodę z Wisły, aż pękł, a Wawel stał się siedzibą królów Polski. "
)


def flow(client: httpx.Client, admin: tuple[str, str]) -> set[str]:
    """Wywołuje operacje T3 i zwraca nazwy zwalidowanych komponentów (brief T3 p. 3)."""
    validated: set[str] = set()
    ds = _prepare_dataset(client)
    cid = _chats_shapes(client, ds, validated)
    sid = _sessions_shapes(client, cid, validated)
    _recommendation_shapes(client, validated)
    _completions_shapes(client, cid, sid, validated)
    _delete_shapes(client, cid, sid, validated)
    _system_shapes(client, validated)
    _users_shapes(client, validated)
    _auth_shapes(client, admin, validated)
    # sprzątanie bez check: czat i dataset
    client.delete(f"/api/v1/chats/{cid}")
    client.request("DELETE", "/api/v1/datasets", json={"ids": [ds]})
    return validated


def _chats_shapes(client: httpx.Client, ds: str, validated: set[str]) -> str:
    """Grupa b (czaty): create → list → get → update → replace; zwraca id czatu."""
    resp = client.post("/api/v1/chats", json={"name": "wd_shapes_chat", "dataset_ids": [ds]})
    validated.add(check("chats_create", resp))
    cid = str(resp.json()["data"]["id"])
    validated.add(check("chats_list", client.get("/api/v1/chats")))
    validated.add(check("chats_get", client.get(f"/api/v1/chats/{cid}")))
    update = client.patch(f"/api/v1/chats/{cid}", json={"description": "opis"})
    validated.add(check("chats_update", update))
    replace = client.put(
        f"/api/v1/chats/{cid}", json={"name": "wd_shapes_chat", "dataset_ids": [ds]}
    )
    validated.add(check("chats_replace", replace))
    return cid


def _sessions_shapes(client: httpx.Client, cid: str, validated: set[str]) -> str:
    """Grupa c (sesje): create → list → get → rename → rename_legacy; zwraca id sesji."""
    resp = client.post(f"/api/v1/chats/{cid}/sessions", json={"name": "s1"})
    validated.add(check("sessions_create", resp))
    sid = str(resp.json()["data"]["id"])
    validated.add(check("sessions_list", client.get(f"/api/v1/chats/{cid}/sessions")))
    validated.add(check("sessions_get", client.get(f"/api/v1/chats/{cid}/sessions/{sid}")))
    rename = client.patch(f"/api/v1/chats/{cid}/sessions/{sid}", json={"name": "s2"})
    validated.add(check("sessions_rename", rename))
    legacy = client.put(f"/api/v1/chats/{cid}/sessions/{sid}", json={"name": "s3"})
    validated.add(check("sessions_rename_legacy", legacy))
    # E2-1 CHAT: operacje na wiadomości; brak pary o tym id → bez zmian, koperta sesji.
    missing = uuid.uuid4().hex
    validated.add(
        check(
            "sessions_message_feedback",
            client.put(
                f"/api/v1/chats/{cid}/sessions/{sid}/messages/{missing}/feedback",
                json={"thumbup": True},
            ),
        )
    )
    validated.add(
        check(
            "sessions_message_delete",
            client.request("DELETE", f"/api/v1/chats/{cid}/sessions/{sid}/messages/{missing}"),
        )
    )
    return sid


def _recommendation_shapes(client: httpx.Client, validated: set[str]) -> None:
    """Grupa f (E2-1 CHAT): rekomendacja pytań — kanoniczna i alias deprecated."""
    body = {"question": _QUESTION}
    validated.add(
        check("chat_recommendation", client.post("/api/v1/chat/recommendation", json=body))
    )
    validated.add(
        check(
            "sessions_related_questions",
            client.post("/api/v1/sessions/related_questions", json=body),
        )
    )


def _completions_shapes(client: httpx.Client, cid: str, sid: str, validated: set[str]) -> None:
    """Grupa d: JSON i SSE na obu trasach completions."""
    native = {"question": _QUESTION, "stream": False, "session_id": sid}
    validated.add(
        check("chats_completions", client.post(f"/api/v1/chats/{cid}/completions", json=native))
    )
    native["stream"] = True
    validated.add(
        check_sse("chats_completions", client.post(f"/api/v1/chats/{cid}/completions", json=native))
    )
    restful: dict[str, Any] = {
        "chat_id": cid,
        "session_id": sid,
        "messages": [{"role": "user", "content": _QUESTION}],
    }
    validated.add(
        check(
            "chat_completions",
            client.post("/api/v1/chat/completions", json=restful | {"stream": False}),
        )
    )
    validated.add(
        check_sse(
            "chat_completions",
            client.post("/api/v1/chat/completions", json=restful | {"stream": True}),
        )
    )
    # OpenAI-compat (E2-1 OD/OC): completions w kształcie OpenAI (bez koperty code) — JSON
    # ``chat.completion`` na trasie kanonicznej i na aliasie ``/chats_openai/…`` (E2-1 OC),
    # oraz lista modeli czatu. Wszystkie trzy odpowiedzi są surowe: ``check_raw``.
    openai: dict[str, Any] = {"model": PLACEHOLDER, "messages": restful["messages"]}
    validated.add(
        check_raw(
            "openai_chat_completions",
            client.post(f"/api/v1/openai/{cid}/chat/completions", json=openai | {"stream": False}),
        )
    )
    validated.add(
        check_raw(
            "chats_openai_chat_completions",
            client.post(
                f"/api/v1/chats_openai/{cid}/chat/completions", json=openai | {"stream": False}
            ),
        )
    )
    validated.add(check_raw("openai_models_list", client.get(f"/api/v1/openai/{cid}/models")))


def _delete_shapes(client: httpx.Client, cid: str, sid: str, validated: set[str]) -> None:
    """Grupa e: sessions_delete, chats_delete i chats_delete_many na dodatkowych czatach."""
    validated.add(
        check(
            "sessions_delete",
            client.request("DELETE", f"/api/v1/chats/{cid}/sessions", json={"ids": [sid]}),
        )
    )
    first = str(_data(client.post("/api/v1/chats", json={"name": "wd_shapes_chat_d1"}))["id"])
    second = str(_data(client.post("/api/v1/chats", json={"name": "wd_shapes_chat_d2"}))["id"])
    validated.add(check("chats_delete", client.delete(f"/api/v1/chats/{first}")))
    validated.add(
        check(
            "chats_delete_many", client.request("DELETE", "/api/v1/chats", json={"ids": [second]})
        )
    )


def _system_shapes(client: httpx.Client, validated: set[str]) -> None:
    """Grupa f: config, klucze API, stan systemu i katalog modeli (nie klucza klienta)."""
    validated.add(check("system_config", client.get("/api/v1/system/config")))
    validated.add(check("system_tokens_list", client.get("/api/v1/system/tokens")))
    resp = client.post("/api/v1/system/tokens", params={"name": "shapes"})
    validated.add(check("system_tokens_create", resp))
    token = str(resp.json()["data"]["token"])
    validated.add(check("system_tokens_delete", client.delete(f"/api/v1/system/tokens/{token}")))
    # Reszta tras system z E2-1 (scenariusz system): /system/ping to text/html (bez JSON).
    validated.add(check("system_version", client.get("/api/v1/system/version")))
    validated.add(check("system_language", client.get("/api/v1/language")))
    validated.add(check_raw("system_healthz", client.get("/api/v1/system/healthz")))
    validated.add(check("system_status", client.get("/api/v1/system/status")))
    validated.add(check("system_stats", client.get("/api/v1/system/stats")))
    validated.add(check("models_list", client.get("/api/v1/models")))
    validated.add(check("models_default", client.get("/api/v1/models/default")))
    validated.add(check("providers_list", client.get("/api/v1/providers")))
    validated.add(check("provider_get", client.get("/api/v1/providers/OpenAI-API-Compatible")))
    validated.add(
        check(
            "provider_instances_list",
            client.get("/api/v1/providers/OpenAI-API-Compatible/instances"),
        )
    )


def _users_shapes(client: httpx.Client, validated: set[str]) -> None:
    """Grupa g: profil bieżący i domyślne modele (update ciałem z get)."""
    resp = client.get("/api/v1/users/me")
    validated.add(check("users_me_get", resp))
    nickname = str(resp.json()["data"]["nickname"])
    update = client.patch("/api/v1/users/me", json={"nickname": nickname})
    validated.add(check("users_me_update", update))
    resp = client.get("/api/v1/users/me/models")
    validated.add(check("users_me_models_get", resp))
    validated.add(
        check(
            "users_me_models_update",
            client.patch("/api/v1/users/me/models", json=resp.json()["data"]),
        )
    )


def _auth_shapes(client: httpx.Client, admin: tuple[str, str], validated: set[str]) -> None:
    """Grupa h: kanały, login, refresh (cookie ręcznie), logout, rejestracja."""
    validated.add(check("auth_login_channels", client.get("/api/v1/auth/login/channels")))
    email, password = admin
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    validated.add(check("auth_login", resp))
    # Cookie wysyłamy ręcznie — niezależnie od flagi Secure (env=test jej nie ma, C1).
    refresh_cookie = _cookie_value(resp, "wd_refresh")
    resp = client.post("/api/v1/auth/refresh", headers={"Cookie": f"wd_refresh={refresh_cookie}"})
    validated.add(check("auth_refresh", resp))
    access = str(resp.json()["data"]["access_token"])
    logout = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {access}"})
    validated.add(check("auth_logout", logout))
    registered = client.post(
        "/api/v1/users",
        json={"nickname": "shapes", "email": "shapes@wd.test", "password": password},
    )
    if registered.json()["code"] == 0:
        validated.add(check("users_register", registered))
    # code 103 (rejestracja wyłączona w trybie test) → bez check; komponent
    # RagflowOk_SessionUser_ i tak pokrywa auth_login (brief T3 p. 3h).


def _data(resp: httpx.Response) -> Any:
    """data koperty sukcesu; asercja code 0 (zasiew — operacje T2 bez check)."""
    body = resp.json()
    assert body["code"] == 0, resp.text
    return body["data"]


def _prepare_dataset(client: httpx.Client) -> str:
    """Zasiew bez check (operacje T2): dataset, upload wawel.txt, parse, czekanie na DONE."""
    ds = str(_data(client.post("/api/v1/datasets", json={"name": "wd_shapes_chat_ds"}))["id"])
    upload = client.post(
        f"/api/v1/datasets/{ds}/documents", files={"file": ("wawel.txt", _WAWEL_TXT.encode())}
    )
    doc_id = str(_data(upload)[0]["id"])
    parse = client.post(f"/api/v1/datasets/{ds}/documents/parse", json={"document_ids": [doc_id]})
    _data(parse)
    deadline = time.monotonic() + _PARSE_TIMEOUT_S
    while time.monotonic() < deadline:
        docs = _data(client.get(f"/api/v1/datasets/{ds}/documents"))["docs"]
        if docs and docs[0]["run"] == "DONE":
            return ds
        time.sleep(1.0)
    raise AssertionError(f"parsowanie wawel.txt nie skończyło się w {_PARSE_TIMEOUT_S} s")


def _cookie_value(resp: httpx.Response, name: str) -> str:
    """Wartość ciasteczka name z nagłówków Set-Cookie (bez atrybutów)."""
    prefix = name + "="
    for value in resp.headers.get_list("set-cookie"):
        if value.startswith(prefix):
            return value.split(";", 1)[0].removeprefix(prefix)
    raise AssertionError(f"brak ciasteczka {name} w odpowiedzi: {resp.text}")
