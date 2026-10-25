"""Polityka dostępu — jedyne miejsce decyzji (07 §7, kontrakt C2). Czyste funkcje, bez I/O.

Żadna inna część kodu nie porównuje ``tenant_id == user_id`` ani nie sprawdza ``is_superuser``
(regułę wymusza grep-test ``tests/unit/test_policy_grep.py``).
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from app.core.errors import OperationNotAllowed, PermissionDenied
from app.domain.policy.principal import Principal

__all__ = [
    "Action",
    "Principal",
    "ResourceKind",
    "ResourceRef",
    "VisibilityFilter",
    "can",
    "ensure_admin_remains",
    "require",
    "visibility_filter",
]


class Action(StrEnum):
    """Akcje na zasobach (07 §7)."""

    READ = "read"
    USE = "use"
    UPDATE = "update"
    DELETE = "delete"
    MANAGE = "manage"


ResourceKind = Literal[
    "dataset", "document", "chat", "session", "search", "file", "model", "integration", "user"
]


@dataclass(frozen=True)
class ResourceRef:
    """Referencja do zasobu: rodzaj, właściciel i granty istotne dla decyzji."""

    kind: ResourceKind
    owner_id: str | None
    permission: Literal["me", "team"] | None = None
    chat_grant_emails: frozenset[str] = frozenset()  # dla chat (i session: granty czatu sesji)
    session_user_id: str | None = None  # dla session
    id: str | None = None  # K5 §7.2 (runda 2): id zasobu do komunikatu require; OSTATNIE pole


@dataclass(frozen=True)
class VisibilityFilter:
    """Filtr widoczności list do przetłumaczenia na WHERE zapytania SQL (07 §7)."""

    all: bool
    owner_ids: frozenset[str]
    include_team: bool
    granted_ids: frozenset[str] = frozenset()


def can(principal: Principal, action: Action, res: ResourceRef) -> bool:
    """Decyzja o dostępie wg tabeli 07 §7.1 (kolejność: admin → MANAGE → rodzaj zasobu)."""
    if principal.is_superuser:
        return True
    if action is Action.MANAGE:
        return False
    is_owner = res.owner_id is not None and res.owner_id == principal.user_id
    is_team = res.permission == "team"
    granted = principal.email.lower() in {e.lower() for e in res.chat_grant_emails}
    allowed: bool
    if res.kind in ("dataset", "document", "search"):
        allowed = (is_owner or is_team) if action in (Action.READ, Action.USE) else is_owner
    elif res.kind == "chat":
        allowed = (
            (is_owner or is_team or granted) if action in (Action.READ, Action.USE) else is_owner
        )
    elif res.kind == "session":
        allowed = is_owner or (
            (is_team or granted)
            and res.session_user_id is not None
            and res.session_user_id.lower() == principal.email.lower()
        )
    elif res.kind == "file":
        allowed = is_owner
    elif res.kind == "model":
        allowed = action in (Action.READ, Action.USE)
    elif res.kind == "integration":
        allowed = False
    else:  # res.kind == "user": owner_id to id opisywanego użytkownika; DELETE tylko dla admina
        allowed = is_owner and action is not Action.DELETE
    return allowed


def visibility_filter(
    principal: Principal, kind: str, granted_ids: frozenset[str] = frozenset()
) -> VisibilityFilter:
    """Filtr widoczności dla list (07 §7); nieznany rodzaj → ValueError.

    ``granted_ids`` (granty czatu) są brane pod uwagę tylko dla ``kind == "chat"`` (C6);
    dla pozostałych rodzajów są ignorowane.
    """
    if principal.is_superuser:
        return VisibilityFilter(True, frozenset(), False)
    if kind == "model":
        return VisibilityFilter(True, frozenset(), False)
    if kind == "chat":
        return VisibilityFilter(False, frozenset({principal.user_id}), True, granted_ids)
    if kind in ("dataset", "document", "search"):
        return VisibilityFilter(False, frozenset({principal.user_id}), True)
    if kind in ("session", "file", "user"):
        return VisibilityFilter(False, frozenset({principal.user_id}), False)
    if kind == "integration":
        return VisibilityFilter(False, frozenset(), False)
    raise ValueError(f"unknown resource kind: {kind}")


def require(principal: Principal, action: Action, res: ResourceRef) -> None:
    """Jak ``can``, ale odmowę zamienia na PermissionDenied (komunikat wg K5 §7.2 runda 2)."""
    if can(principal, action, res):
        return
    message = (
        f"You don't own the {res.kind} {res.id}." if res.id is not None else "No authorization."
    )
    raise PermissionDenied(message, details={"kind": res.kind, "action": action.value})


def ensure_admin_remains(
    target_is_active_admin: bool, stays_active_admin: bool, other_active_admins: int
) -> None:
    """Ostatni aktywny admin nie może zostać zdeaktywowany ani zdegradowany (07 §6.2, B10)."""
    if target_is_active_admin and not stays_active_admin and other_active_admins == 0:
        raise OperationNotAllowed("The last active administrator cannot be deactivated or demoted.")
