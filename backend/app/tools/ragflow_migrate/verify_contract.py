"""Próbka kontraktowa API: czaty i sesje celu ze źródłem (kontrakt E4-6c §6).

Aplikację WD stawiamy in-process (``TestClient`` jako menedżer kontekstu — lifespan), na
ustawieniach biegu ze ``storage_root`` w katalogu tymczasowym. Porównujemy wyłącznie to, co
kontrakt §6 wymienia: obecność czatu, jego ``name`` i zbiór ``datasets[].id`` oraz — dla sesji
czatu — zbiór id, ``name`` i liczbę wiadomości. Token właściciela nigdy nie trafia do wyniku.
"""

import importlib
import json
import tempfile
from collections.abc import Mapping, Sequence
from typing import Any

from starlette.testclient import TestClient

from app.core.config import Settings
from app.core.container import Container
from app.tools.ragflow_migrate.source import Source
from app.tools.ragflow_migrate.verify_types import ContractMismatch, ContractSample

HTTP_OK = 200

#: Rozmiar strony GET-ów próbki — kontrakt §6 (``max_page_size`` ustawień WD to 1000).
PAGE_SIZE = 1000

CHATS_PATH = "/api/v1/chats"


def _json_list(value: object) -> list[str]:
    """Lista napisów z wartości JSON (tekst albo lista); ``None``/nie-lista → pusto."""
    if value is None or value == "":
        return []
    parsed = json.loads(value) if isinstance(value, str | bytes) else value
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _source_dialogs(src: Source) -> list[dict[str, Any]]:
    """Czaty źródła: ``id``, ``tenant_id``, ``name`` i lista ``kb_ids`` (kontrakt §6)."""
    if not src.has_table("dialog"):
        return []
    dialogs: list[dict[str, Any]] = [
        {
            "id": str(row["id"]),
            "tenant_id": str(row["tenant_id"]),
            "name": str(row["name"] or ""),
            "kb_ids": _json_list(row["kb_ids"]),
        }
        for row in src.rows("dialog")
    ]
    dialogs.sort(key=lambda dialog: str(dialog["id"]))
    return dialogs


def _knowledgebase_ids(src: Source) -> set[str]:
    """Id baz wiedzy źródła — wyznaczają przecięcie z ``dialog.kb_ids`` (kontrakt §6)."""
    if not src.has_table("knowledgebase"):
        return set()
    return {str(row["id"]) for row in src.rows("knowledgebase")}


def _conversations_by_dialog(src: Source) -> dict[str, list[dict[str, Any]]]:
    """Rozmowy źródła grupowane po ``dialog_id``; ``message_count`` z długości listy ``message``."""
    if not src.has_table("conversation"):
        return {}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in src.rows("conversation"):
        grouped.setdefault(str(row["dialog_id"]), []).append(
            {
                "id": str(row["id"]),
                "name": str(row["name"] or ""),
                "message_count": len(_json_list(row["message"])),
            }
        )
    for conversations in grouped.values():
        conversations.sort(key=lambda conversation: str(conversation["id"]))
    return grouped


def _owner_tokens(src: Source) -> dict[str, str]:
    """``tenant_id`` → token jego pierwszego klucza (kontrakt §6).

    Kolejność ``(create_time, token)`` daje wynik niezależny od kolejności wierszy w tabeli.
    """
    if not src.has_table("api_token"):
        return {}
    rows = sorted(
        src.rows("api_token"),
        key=lambda row: (int(row["create_time"] or 0), str(row["token"])),
    )
    tokens: dict[str, str] = {}
    for row in rows:
        tokens.setdefault(str(row["tenant_id"]), str(row["token"]))
    return tokens


def _bearer(token: str) -> dict[str, str]:
    """Nagłówek uwierzytelnienia kluczem przeniesionym z RAGFlow (kontrakt §6)."""
    return {"Authorization": f"Bearer {token}"}


def _list_items(http: TestClient, path: str, token: str) -> tuple[dict[str, dict[str, Any]], str]:
    """Wiersze listy API (klucz = ``id``) i komunikat koperty; błąd → ``({}, komunikat)``.

    Bez nagłówków w komunikacie — token nie może trafić do raportu (kontrakt §6).
    """
    response = http.get(path, params={"page_size": PAGE_SIZE}, headers=_bearer(token))
    body = response.json()
    if response.status_code != HTTP_OK or body.get("code") != 0:
        return {}, str(body.get("message") or f"HTTP {response.status_code}")
    return {str(item["id"]): item for item in body.get("data") or []}, ""


def _chat_mismatches(
    dialog: Mapping[str, Any], item: Mapping[str, Any], kb_ids: set[str]
) -> list[ContractMismatch]:
    """``name`` i zbiór ``datasets[].id`` czatu wobec wiersza ``dialog`` źródła (kontrakt §6)."""
    mismatches: list[ContractMismatch] = []
    name = str(item.get("name") or "")
    if name != dialog["name"]:
        mismatches.append(ContractMismatch("chat", dialog["id"], "name", dialog["name"], name))
    expected = ",".join(sorted(kb for kb in dialog["kb_ids"] if kb in kb_ids))
    actual = ",".join(sorted(str(dataset.get("id")) for dataset in item.get("datasets") or []))
    if actual != expected:
        mismatches.append(ContractMismatch("chat", dialog["id"], "datasets", expected, actual))
    return mismatches


def _session_mismatches(
    http: TestClient, token: str, dialog_id: str, conversations: Sequence[Mapping[str, Any]]
) -> tuple[list[ContractMismatch], int]:
    """Zbiór id, ``name`` i liczba wiadomości sesji czatu; zwraca też liczbę porównanych sesji."""
    items, message = _list_items(http, f"{CHATS_PATH}/{dialog_id}/sessions", token)
    expected = {str(conversation["id"]): conversation for conversation in conversations}
    mismatches: list[ContractMismatch] = []
    for conversation in conversations:
        item = items.get(str(conversation["id"]))
        if item is None:
            mismatches.append(
                ContractMismatch(
                    "session", conversation["id"], "missing", conversation["name"], message
                )
            )
            continue
        name = str(item.get("name") or "")
        if name != conversation["name"]:
            mismatches.append(
                ContractMismatch("session", conversation["id"], "name", conversation["name"], name)
            )
        count = len(item.get("messages") or [])
        if count != conversation["message_count"]:
            mismatches.append(
                ContractMismatch(
                    "session",
                    conversation["id"],
                    "message_count",
                    str(conversation["message_count"]),
                    str(count),
                )
            )
    for session_id in sorted(set(items) - set(expected)):
        mismatches.append(
            ContractMismatch(
                "session", session_id, "missing", "", str(items[session_id].get("name"))
            )
        )
    return mismatches, len(expected)


def _by_tenant(dialogs: Sequence[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    """Czaty źródła grupowane po ``tenant_id`` — klucz próbki kontraktowej (kontrakt §6)."""
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for dialog in dialogs:
        grouped.setdefault(str(dialog["tenant_id"]), []).append(dialog)
    return grouped


def _compare(
    http: TestClient,
    dialogs: Sequence[Mapping[str, Any]],
    kb_ids: set[str],
    conversations: Mapping[str, list[dict[str, Any]]],
    tokens: Mapping[str, str],
) -> ContractSample:
    """Porównanie odpowiedzi API z wierszami źródła, per właściciel czatu (kontrakt §6)."""
    mismatches: list[ContractMismatch] = []
    skipped_no_key: list[str] = []
    chats_checked = sessions_checked = 0
    for tenant_id, owned in sorted(_by_tenant(dialogs).items()):
        token = tokens.get(tenant_id)
        if token is None:
            skipped_no_key += [str(dialog["id"]) for dialog in owned]
            continue
        items, message = _list_items(http, CHATS_PATH, token)
        for dialog in owned:
            chats_checked += 1
            item = items.get(str(dialog["id"]))
            if item is None:
                mismatches.append(
                    ContractMismatch("chat", dialog["id"], "missing", dialog["name"], message)
                )
                continue
            mismatches += _chat_mismatches(dialog, item, kb_ids)
            session_mismatches, checked = _session_mismatches(
                http, token, str(dialog["id"]), conversations.get(str(dialog["id"]), [])
            )
            mismatches += session_mismatches
            sessions_checked += checked
    return ContractSample(
        chats_checked=chats_checked,
        sessions_checked=sessions_checked,
        mismatches=mismatches,
        skipped_no_key=sorted(skipped_no_key),
    )


def run_contract_sample(src: Source, settings: Settings) -> ContractSample:
    """Porównuje odpowiedzi ``/api/v1/chats`` i sesji z wierszami źródła (kontrakt §6).

    Aplikację stawiamy in-process na kopii ustawień ze ``storage_root`` w katalogu tymczasowym;
    ``app.main`` ładujemy dynamicznie, bo statyczny import łamie kontrakt import-lintera
    ``ragflow-migrate-no-api`` (§6).
    """
    dialogs = _source_dialogs(src)
    if not dialogs:
        return ContractSample(chats_checked=0, sessions_checked=0, mismatches=[], skipped_no_key=[])
    kb_ids = _knowledgebase_ids(src)
    conversations = _conversations_by_dialog(src)
    tokens = _owner_tokens(src)
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = settings.model_copy(update={"storage_root": str(tmpdir)})
        main_mod = importlib.import_module("app.main")
        app = main_mod.create_app(cfg, Container(cfg))
        with TestClient(app, base_url="https://testserver") as http:
            return _compare(http, dialogs, kb_ids, conversations, tokens)
