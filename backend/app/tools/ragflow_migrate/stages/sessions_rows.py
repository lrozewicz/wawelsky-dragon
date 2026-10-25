"""Czyste rozstrzyganie wierszy ``conversation`` na ``chat_sessions``/``chat_messages``
(kontrakt §3, WP E4-6b2 T2).

Wydzielone z :mod:`app.tools.ragflow_migrate.stages.sessions` (limit 400 linii pliku; BRIEF WP
E4-6b2 dopuszcza pomocnicze moduły w pakiecie narzędzia). Bez bazy i SQL — testy jednostkowe
w ``tests/unit/tools/test_ragflow_sessions.py``.
"""

import json
import uuid
from collections.abc import Mapping
from typing import Any

from app.core.timeutil import from_ms
from app.tools.ragflow_migrate.stages.base import Issue

#: Role dopuszczone przez schemat WD (``chat_messages.role ENUM('user','assistant','system')``).
ROLES: frozenset[str] = frozenset({"user", "assistant", "system"})

#: Rola, której wiadomości nie dostają referencji w shimie v0.24 (kontrakt §3).
NON_REFERENCE_ROLE = "user"

#: Nazwa sesji, gdy źródło jej nie podaje (schemat WD: ``name NOT NULL DEFAULT 'New session'``).
DEFAULT_NAME = "New session"

#: ``source`` sesji przenoszonej przez API RAGFlow (kontrakt §3).
DEFAULT_SOURCE = "api"

#: Przestrzeń nazw deterministycznych id wiadomości — te same id przy kolejnym biegu (§3).
_ID_NAMESPACE = uuid.NAMESPACE_URL

#: Maksymalna długość źródłowego id wiadomości (``chat_messages.id CHAR(36)``).
MAX_MESSAGE_ID = 36


def session_name(value: Any) -> str:
    """Nazwa sesji: ``name`` źródła, a gdy NULL/pusta — ``New session`` (kontrakt §3)."""
    return str(value) if value else DEFAULT_NAME


def _invalid_json_issue(session_id: str) -> Issue:
    """Ostrzeżenie o niepoprawnym ``message`` źródła (kontrakt §3)."""
    return Issue(
        severity="warning",
        code="session_json_invalid",
        message="message rozmowy nie jest poprawną listą JSON — potraktowano jak pustą",
        ids=[session_id],
    )


def _invalid_message_issue(session_id: str) -> Issue:
    """Ostrzeżenie o elemencie ``message`` bez poprawnej roli (kontrakt §3)."""
    return Issue(
        severity="warning",
        code="message_invalid",
        message="element message bez roli user/assistant/system — pominięty",
        ids=[session_id],
    )


def parse_messages(session_id: str, raw: Any) -> tuple[list[Mapping[str, Any]], list[Issue]]:
    """``message`` źródła → lista elementów o poprawnej roli i uwagi (kontrakt §3).

    NULL/""/niepoprawny/nie-lista → ``[]`` (tylko niepoprawny JSON daje ``session_json_invalid``).
    Element nie-obiekt albo rola spoza :data:`ROLES` jest pomijany (:func:`_invalid_message_issue`).
    """
    if raw is None or raw == "":
        return [], []
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return [], [_invalid_json_issue(session_id)]
    if not isinstance(parsed, list):
        return [], [_invalid_json_issue(session_id)]
    entries: list[Mapping[str, Any]] = []
    issues: list[Issue] = []
    for item in parsed:
        if isinstance(item, Mapping) and item.get("role") in ROLES:
            entries.append(item)
        else:
            issues.append(_invalid_message_issue(session_id))
    return entries, issues


def parse_references(raw: Any) -> list[dict[str, Any]]:
    """``reference`` źródła → niepuste wpisy ``dict`` w kolejności (kontrakt §3).

    NULL/""/niepoprawna/nie-lista → ``[]``; wpis ``{}`` lub nie-``dict`` jest pomijany i nie
    zużywa celu przypięcia.
    """
    if raw is None or raw == "":
        return []
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict) and bool(item)]


def _source_id(entry: Mapping[str, Any]) -> str | None:
    """Źródłowe ``id`` wiadomości, gdy mieści się w ``CHAR(36)``; inaczej ``None``."""
    value = entry.get("id")
    if isinstance(value, str) and 0 < len(value) <= MAX_MESSAGE_ID:
        return value
    return None


def message_ids(entries: list[Mapping[str, Any]], session_id: str) -> list[str]:
    """Id wiadomości wg kontraktu §3: najpierw rezerwują asystent/system, potem reszta.

    Wiadomość ``user`` dzieli id z parą asystenta (RAGFlow) — jej wtedy przypada deterministyczne
    ``uuid5`` (``wd-migrate:<session>:<seq>``), tak samo przy braku lub złym id.
    """
    reserved = {
        source_id
        for entry in entries
        if entry["role"] != NON_REFERENCE_ROLE and (source_id := _source_id(entry)) is not None
    }
    taken: set[str] = set()
    ids: list[str] = []
    for seq, entry in enumerate(entries):
        candidate = _source_id(entry)
        if (
            candidate is None
            or candidate in taken
            or (entry["role"] == NON_REFERENCE_ROLE and candidate in reserved)
        ):
            candidate = str(uuid.uuid5(_ID_NAMESPACE, f"wd-migrate:{session_id}:{seq}"))
        taken.add(candidate)
        ids.append(candidate)
    return ids


def _content(entry: Mapping[str, Any]) -> str:
    """Treść wiadomości jako ``str``; ``None`` → ``""`` (kontrakt §3)."""
    value = entry.get("content")
    return "" if value is None else str(value)


def _thumbup(entry: Mapping[str, Any]) -> bool | None:
    """``thumbup``: ``bool`` gdy klucz jest i nie-NULL, inaczej ``NULL`` (kontrakt §3)."""
    value = entry.get("thumbup")
    return bool(value) if value is not None else None


def _feedback(entry: Mapping[str, Any]) -> str | None:
    """``feedback``: ``str`` gdy klucz jest i nie-NULL, inaczej ``NULL`` (kontrakt §3)."""
    value = entry.get("feedback")
    return str(value) if value is not None else None


def _created_at(entry: Mapping[str, Any], session_create_ms: int) -> float:
    """``created_at`` w sekundach: liczba ze źródła, inaczej ``create_time`` sesji (kontrakt §3)."""
    value = entry.get("created_at")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return session_create_ms / 1000


def _reference_targets(entries: list[Mapping[str, Any]]) -> list[int]:
    """Indeksy wiadomości, do których shim v0.24 przypina kolejne referencje (kontrakt §3)."""
    return [
        index
        for index, entry in enumerate(entries)
        if index > 0 and entry["role"] != NON_REFERENCE_ROLE
    ]


def build_messages(
    session_id: str, message_json: Any, reference_json: Any, session_create_ms: int
) -> tuple[list[dict[str, Any]], list[Issue]]:
    """``message`` + ``reference`` rozmowy → wiersze ``chat_messages`` i uwagi (kontrakt §3).

    Referencje (niepuste wpisy ``dict``) trafiają w kolejności do wiadomości roli ≠ ``user``
    z ``seq > 0``; nadmiarowe → ``reference_unattached`` (ich treść nie jest zapisywana).
    """
    entries, issues = parse_messages(session_id, message_json)
    references = parse_references(reference_json)
    ids = message_ids(entries, session_id)
    create_date = from_ms(session_create_ms).replace(tzinfo=None)
    targets = _reference_targets(entries)
    attached = dict(zip(targets, references, strict=False))
    messages: list[dict[str, Any]] = []
    for seq, entry in enumerate(entries):
        reference = attached.get(seq)
        messages.append(
            {
                "id": ids[seq],
                "session_id": session_id,
                "seq": seq,
                "role": entry["role"],
                "content": _content(entry),
                "reference": (
                    json.dumps(reference, ensure_ascii=False) if reference is not None else None
                ),
                "thumbup": _thumbup(entry),
                "feedback": _feedback(entry),
                "prompt_tokens": None,
                "completion_tokens": None,
                "created_at": _created_at(entry, session_create_ms),
                "create_time": session_create_ms,
                "create_date": create_date,
                "update_time": session_create_ms,
                "update_date": create_date,
            }
        )
    if len(references) > len(targets):
        issues.append(
            Issue(
                severity="warning",
                code="reference_unattached",
                message="referencji rozmowy nie ma do czego przypiąć — treść pominięta",
                ids=[session_id],
            )
        )
    return messages, issues


def _time(value: Any, stored: int | None, now_ms: int) -> int:
    """Czas w ms: wartość źródła, inaczej istniejącego wiersza celu, inaczej bieżący (§3)."""
    if value is not None:
        return int(value)
    return stored if stored is not None else now_ms


def resolve_session(
    row: Mapping[str, Any],
    chat_owners: Mapping[str, str],
    stored_times: tuple[int, int] | None,
    now_ms: int,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[Issue]]:
    """Wiersz ``conversation`` → wiersz ``chat_sessions``, wiadomości i uwagi (kontrakt §3).

    ``None`` jako wiersz sesji = Issue ``session_chat_missing`` (rozmowa pomijana w ``skipped``).
    ``chat_owners`` mapuje ``chat_id`` na właściciela czatu w celu (``chats.tenant_id``);
    ``stored_times`` to ``(create_time, update_time)`` istniejącej sesji celu (idempotencja).
    """
    session_id = str(row["id"])
    chat_id = str(row["dialog_id"])
    if chat_id not in chat_owners:
        return (
            None,
            [],
            [
                Issue(
                    severity="warning",
                    code="session_chat_missing",
                    message="czat rozmowy nie został przeniesiony do celu — sesja pomijana",
                    ids=[session_id],
                )
            ],
        )
    create_time = _time(row["create_time"], stored_times[0] if stored_times else None, now_ms)
    update_time = _time(row["update_time"], stored_times[1] if stored_times else None, now_ms)
    messages, issues = build_messages(session_id, row["message"], row["reference"], create_time)
    session = {
        "id": session_id,
        "chat_id": chat_id,
        "name": session_name(row["name"]),
        "user_id": row["user_id"],
        "owner_id": chat_owners[chat_id],
        "source": DEFAULT_SOURCE,
        "message_count": len(messages),
        "create_time": create_time,
        "create_date": from_ms(create_time).replace(tzinfo=None),
        "update_time": update_time,
        "update_date": from_ms(update_time).replace(tzinfo=None),
    }
    return session, messages, issues
