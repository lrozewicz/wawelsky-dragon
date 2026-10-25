"""Test polityki dostępu — tabela decyzji 07 §7.1 komórka po komórce (kontrakt C2)."""

import pytest

from app.domain.policy import (
    Action,
    OperationNotAllowed,
    PermissionDenied,
    Principal,
    ResourceKind,
    ResourceRef,
    VisibilityFilter,
    can,
    ensure_admin_remains,
    require,
    visibility_filter,
)

ADMIN = Principal("a" * 32, "admin@x.pl", True, False, "jwt")
OWNER = Principal("o" * 32, "Owner@X.pl", False, False, "jwt")
OTHER = Principal("b" * 32, "other@x.pl", False, False, "api_key")

KINDS: tuple[ResourceKind, ...] = (
    "dataset",
    "document",
    "chat",
    "session",
    "search",
    "file",
    "model",
    "integration",
    "user",
)
ROLES = ("admin", "owner", "other", "team", "grant")


def _principal(role: str) -> Principal:
    """Rola z tabeli → principal."""
    if role == "admin":
        return ADMIN
    if role == "owner":
        return OWNER
    return OTHER


def _ref(kind: ResourceKind, role: str) -> ResourceRef:
    """Zasób roli: właścicielem jest OWNER; team = permission="team"; grant = e-mail OTHER-a."""
    permission = "team" if role == "team" else None
    grants = frozenset({"other@x.pl"}) if role == "grant" else frozenset()
    session_user = "other@x.pl" if kind == "session" and role == "grant" else None
    return ResourceRef(kind, OWNER.user_id, permission, grants, session_user)


# Oczekiwania wpisane RĘCZNIE wg 07 §7.1 i C2 p. 1-9 (nie wyliczane przez can()); kolumny:
# kind, action, rola (kolejność ROLES), oczekiwane. Dwie krotki na wiersz dla zwięzłości.
CAN_TABLE: list[tuple[ResourceKind, Action, str, bool]] = [
    ("dataset", Action.READ, "admin", True),
    ("dataset", Action.READ, "owner", True),
    ("dataset", Action.READ, "other", False),
    ("dataset", Action.READ, "team", True),
    ("dataset", Action.READ, "grant", False),
    ("dataset", Action.USE, "admin", True),
    ("dataset", Action.USE, "owner", True),
    ("dataset", Action.USE, "other", False),
    ("dataset", Action.USE, "team", True),
    ("dataset", Action.USE, "grant", False),
    ("dataset", Action.UPDATE, "admin", True),
    ("dataset", Action.UPDATE, "owner", True),
    ("dataset", Action.UPDATE, "other", False),
    ("dataset", Action.UPDATE, "team", False),
    ("dataset", Action.UPDATE, "grant", False),
    ("dataset", Action.DELETE, "admin", True),
    ("dataset", Action.DELETE, "owner", True),
    ("dataset", Action.DELETE, "other", False),
    ("dataset", Action.DELETE, "team", False),
    ("dataset", Action.DELETE, "grant", False),
    ("dataset", Action.MANAGE, "admin", True),
    ("dataset", Action.MANAGE, "owner", False),
    ("dataset", Action.MANAGE, "other", False),
    ("dataset", Action.MANAGE, "team", False),
    ("dataset", Action.MANAGE, "grant", False),
    ("document", Action.READ, "admin", True),
    ("document", Action.READ, "owner", True),
    ("document", Action.READ, "other", False),
    ("document", Action.READ, "team", True),
    ("document", Action.READ, "grant", False),
    ("document", Action.USE, "admin", True),
    ("document", Action.USE, "owner", True),
    ("document", Action.USE, "other", False),
    ("document", Action.USE, "team", True),
    ("document", Action.USE, "grant", False),
    ("document", Action.UPDATE, "admin", True),
    ("document", Action.UPDATE, "owner", True),
    ("document", Action.UPDATE, "other", False),
    ("document", Action.UPDATE, "team", False),
    ("document", Action.UPDATE, "grant", False),
    ("document", Action.DELETE, "admin", True),
    ("document", Action.DELETE, "owner", True),
    ("document", Action.DELETE, "other", False),
    ("document", Action.DELETE, "team", False),
    ("document", Action.DELETE, "grant", False),
    ("document", Action.MANAGE, "admin", True),
    ("document", Action.MANAGE, "owner", False),
    ("document", Action.MANAGE, "other", False),
    ("document", Action.MANAGE, "team", False),
    ("document", Action.MANAGE, "grant", False),
    ("chat", Action.READ, "admin", True),
    ("chat", Action.READ, "owner", True),
    ("chat", Action.READ, "other", False),
    ("chat", Action.READ, "team", True),
    ("chat", Action.READ, "grant", True),
    ("chat", Action.USE, "admin", True),
    ("chat", Action.USE, "owner", True),
    ("chat", Action.USE, "other", False),
    ("chat", Action.USE, "team", True),
    ("chat", Action.USE, "grant", True),
    ("chat", Action.UPDATE, "admin", True),
    ("chat", Action.UPDATE, "owner", True),
    ("chat", Action.UPDATE, "other", False),
    ("chat", Action.UPDATE, "team", False),
    ("chat", Action.UPDATE, "grant", False),
    ("chat", Action.DELETE, "admin", True),
    ("chat", Action.DELETE, "owner", True),
    ("chat", Action.DELETE, "other", False),
    ("chat", Action.DELETE, "team", False),
    ("chat", Action.DELETE, "grant", False),
    ("chat", Action.MANAGE, "admin", True),
    ("chat", Action.MANAGE, "owner", False),
    ("chat", Action.MANAGE, "other", False),
    ("chat", Action.MANAGE, "team", False),
    ("chat", Action.MANAGE, "grant", False),
    ("session", Action.READ, "admin", True),
    ("session", Action.READ, "owner", True),
    ("session", Action.READ, "other", False),
    ("session", Action.READ, "team", False),
    ("session", Action.READ, "grant", True),
    ("session", Action.USE, "admin", True),
    ("session", Action.USE, "owner", True),
    ("session", Action.USE, "other", False),
    ("session", Action.USE, "team", False),
    ("session", Action.USE, "grant", True),
    ("session", Action.UPDATE, "admin", True),
    ("session", Action.UPDATE, "owner", True),
    ("session", Action.UPDATE, "other", False),
    ("session", Action.UPDATE, "team", False),
    ("session", Action.UPDATE, "grant", True),
    ("session", Action.DELETE, "admin", True),
    ("session", Action.DELETE, "owner", True),
    ("session", Action.DELETE, "other", False),
    ("session", Action.DELETE, "team", False),
    ("session", Action.DELETE, "grant", True),
    ("session", Action.MANAGE, "admin", True),
    ("session", Action.MANAGE, "owner", False),
    ("session", Action.MANAGE, "other", False),
    ("session", Action.MANAGE, "team", False),
    ("session", Action.MANAGE, "grant", False),
    ("search", Action.READ, "admin", True),
    ("search", Action.READ, "owner", True),
    ("search", Action.READ, "other", False),
    ("search", Action.READ, "team", True),
    ("search", Action.READ, "grant", False),
    ("search", Action.USE, "admin", True),
    ("search", Action.USE, "owner", True),
    ("search", Action.USE, "other", False),
    ("search", Action.USE, "team", True),
    ("search", Action.USE, "grant", False),
    ("search", Action.UPDATE, "admin", True),
    ("search", Action.UPDATE, "owner", True),
    ("search", Action.UPDATE, "other", False),
    ("search", Action.UPDATE, "team", False),
    ("search", Action.UPDATE, "grant", False),
    ("search", Action.DELETE, "admin", True),
    ("search", Action.DELETE, "owner", True),
    ("search", Action.DELETE, "other", False),
    ("search", Action.DELETE, "team", False),
    ("search", Action.DELETE, "grant", False),
    ("search", Action.MANAGE, "admin", True),
    ("search", Action.MANAGE, "owner", False),
    ("search", Action.MANAGE, "other", False),
    ("search", Action.MANAGE, "team", False),
    ("search", Action.MANAGE, "grant", False),
    ("file", Action.READ, "admin", True),
    ("file", Action.READ, "owner", True),
    ("file", Action.READ, "other", False),
    ("file", Action.READ, "team", False),
    ("file", Action.READ, "grant", False),
    ("file", Action.USE, "admin", True),
    ("file", Action.USE, "owner", True),
    ("file", Action.USE, "other", False),
    ("file", Action.USE, "team", False),
    ("file", Action.USE, "grant", False),
    ("file", Action.UPDATE, "admin", True),
    ("file", Action.UPDATE, "owner", True),
    ("file", Action.UPDATE, "other", False),
    ("file", Action.UPDATE, "team", False),
    ("file", Action.UPDATE, "grant", False),
    ("file", Action.DELETE, "admin", True),
    ("file", Action.DELETE, "owner", True),
    ("file", Action.DELETE, "other", False),
    ("file", Action.DELETE, "team", False),
    ("file", Action.DELETE, "grant", False),
    ("file", Action.MANAGE, "admin", True),
    ("file", Action.MANAGE, "owner", False),
    ("file", Action.MANAGE, "other", False),
    ("file", Action.MANAGE, "team", False),
    ("file", Action.MANAGE, "grant", False),
    ("model", Action.READ, "admin", True),
    ("model", Action.READ, "owner", True),
    ("model", Action.READ, "other", True),
    ("model", Action.READ, "team", True),
    ("model", Action.READ, "grant", True),
    ("model", Action.USE, "admin", True),
    ("model", Action.USE, "owner", True),
    ("model", Action.USE, "other", True),
    ("model", Action.USE, "team", True),
    ("model", Action.USE, "grant", True),
    ("model", Action.UPDATE, "admin", True),
    ("model", Action.UPDATE, "owner", False),
    ("model", Action.UPDATE, "other", False),
    ("model", Action.UPDATE, "team", False),
    ("model", Action.UPDATE, "grant", False),
    ("model", Action.DELETE, "admin", True),
    ("model", Action.DELETE, "owner", False),
    ("model", Action.DELETE, "other", False),
    ("model", Action.DELETE, "team", False),
    ("model", Action.DELETE, "grant", False),
    ("model", Action.MANAGE, "admin", True),
    ("model", Action.MANAGE, "owner", False),
    ("model", Action.MANAGE, "other", False),
    ("model", Action.MANAGE, "team", False),
    ("model", Action.MANAGE, "grant", False),
    ("integration", Action.READ, "admin", True),
    ("integration", Action.READ, "owner", False),
    ("integration", Action.READ, "other", False),
    ("integration", Action.READ, "team", False),
    ("integration", Action.READ, "grant", False),
    ("integration", Action.USE, "admin", True),
    ("integration", Action.USE, "owner", False),
    ("integration", Action.USE, "other", False),
    ("integration", Action.USE, "team", False),
    ("integration", Action.USE, "grant", False),
    ("integration", Action.UPDATE, "admin", True),
    ("integration", Action.UPDATE, "owner", False),
    ("integration", Action.UPDATE, "other", False),
    ("integration", Action.UPDATE, "team", False),
    ("integration", Action.UPDATE, "grant", False),
    ("integration", Action.DELETE, "admin", True),
    ("integration", Action.DELETE, "owner", False),
    ("integration", Action.DELETE, "other", False),
    ("integration", Action.DELETE, "team", False),
    ("integration", Action.DELETE, "grant", False),
    ("integration", Action.MANAGE, "admin", True),
    ("integration", Action.MANAGE, "owner", False),
    ("integration", Action.MANAGE, "other", False),
    ("integration", Action.MANAGE, "team", False),
    ("integration", Action.MANAGE, "grant", False),
    ("user", Action.READ, "admin", True),
    ("user", Action.READ, "owner", True),
    ("user", Action.READ, "other", False),
    ("user", Action.READ, "team", False),
    ("user", Action.READ, "grant", False),
    ("user", Action.USE, "admin", True),
    ("user", Action.USE, "owner", True),
    ("user", Action.USE, "other", False),
    ("user", Action.USE, "team", False),
    ("user", Action.USE, "grant", False),
    ("user", Action.UPDATE, "admin", True),
    ("user", Action.UPDATE, "owner", True),
    ("user", Action.UPDATE, "other", False),
    ("user", Action.UPDATE, "team", False),
    ("user", Action.UPDATE, "grant", False),
    ("user", Action.DELETE, "admin", True),
    ("user", Action.DELETE, "owner", False),
    ("user", Action.DELETE, "other", False),
    ("user", Action.DELETE, "team", False),
    ("user", Action.DELETE, "grant", False),
    ("user", Action.MANAGE, "admin", True),
    ("user", Action.MANAGE, "owner", False),
    ("user", Action.MANAGE, "other", False),
    ("user", Action.MANAGE, "team", False),
    ("user", Action.MANAGE, "grant", False),
]


@pytest.mark.parametrize(("kind", "action", "role", "expected"), CAN_TABLE)
def test_can_table(kind: ResourceKind, action: Action, role: str, expected: bool) -> None:
    """Każda komórka tabeli 07 §7.1: 9 rodzajów x 5 akcji x 5 ról, oczekiwanie wpisane ręcznie."""
    assert can(_principal(role), action, _ref(kind, role)) is expected


# Przykłady z briefu niepokryte tabelą (permission="me", owner_id=None, wielkość liter, sesja).
def test_dataset_with_permission_me() -> None:
    assert can(OTHER, Action.READ, ResourceRef("dataset", OWNER.user_id, "me")) is False
    assert can(OWNER, Action.DELETE, ResourceRef("dataset", OWNER.user_id, "me")) is True


def test_chat_grant_is_case_insensitive_and_gives_no_update() -> None:
    granted = ResourceRef("chat", OWNER.user_id, "me", frozenset({"OTHER@x.pl"}))
    assert can(OTHER, Action.USE, granted) is True
    updated = ResourceRef("chat", OWNER.user_id, "me", frozenset({"other@x.pl"}))
    assert can(OTHER, Action.UPDATE, updated) is False


def test_session_grant_with_wrong_session_user_is_denied() -> None:
    ref = ResourceRef("session", OWNER.user_id, "me", frozenset({"other@x.pl"}), "someone@x.pl")
    assert can(OTHER, Action.READ, ref) is False


def test_model_without_owner_is_public_for_read_and_use_only() -> None:
    assert can(OTHER, Action.USE, ResourceRef("model", None)) is True
    assert can(OTHER, Action.UPDATE, ResourceRef("model", None)) is False


def test_resource_without_owner_belongs_to_nobody() -> None:
    assert can(OTHER, Action.READ, ResourceRef("dataset", None, "me")) is False
    assert can(OTHER, Action.READ, ResourceRef("integration", None)) is False


def test_user_self_can_update_but_not_delete() -> None:
    assert can(OWNER, Action.UPDATE, ResourceRef("user", OWNER.user_id)) is True
    assert can(OWNER, Action.DELETE, ResourceRef("user", OWNER.user_id)) is False


# visibility_filter — filtr SQL dla list (kontrakt C2).
@pytest.mark.parametrize("kind", KINDS)
def test_visibility_admin_sees_all(kind: ResourceKind) -> None:
    assert visibility_filter(ADMIN, kind) == VisibilityFilter(True, frozenset(), False)


@pytest.mark.parametrize(
    ("kind", "expected_all", "owners", "include_team"),
    [
        ("dataset", False, frozenset({OWNER.user_id}), True),
        ("document", False, frozenset({OWNER.user_id}), True),
        ("chat", False, frozenset({OWNER.user_id}), True),
        ("search", False, frozenset({OWNER.user_id}), True),
        ("session", False, frozenset({OWNER.user_id}), False),
        ("file", False, frozenset({OWNER.user_id}), False),
        ("user", False, frozenset({OWNER.user_id}), False),
        ("model", True, frozenset(), False),
        ("integration", False, frozenset(), False),
    ],
)
def test_visibility_owner(
    kind: ResourceKind, expected_all: bool, owners: frozenset[str], include_team: bool
) -> None:
    filtr = visibility_filter(OWNER, kind)
    assert filtr == VisibilityFilter(expected_all, owners, include_team)


def test_visibility_unknown_kind_raises() -> None:
    with pytest.raises(ValueError, match="unknown resource kind: bogus"):
        visibility_filter(OWNER, "bogus")


# require — komunikaty wg K5 §7.2 runda 2 (R1).
def test_require_denied_without_id() -> None:
    with pytest.raises(PermissionDenied) as exc:
        require(OTHER, Action.DELETE, ResourceRef("dataset", OWNER.user_id))
    assert exc.value.message == "No authorization."
    assert exc.value.details == {"kind": "dataset", "action": "delete"}


def test_require_denied_with_id() -> None:
    ref = ResourceRef("dataset", OWNER.user_id, id="d" * 32)
    with pytest.raises(PermissionDenied) as exc:
        require(OTHER, Action.DELETE, ref)
    assert exc.value.message == "You don't own the dataset " + "d" * 32 + "."
    assert exc.value.details == {"kind": "dataset", "action": "delete"}


def test_require_allowed_returns_none() -> None:
    assert require(OWNER, Action.DELETE, ResourceRef("dataset", OWNER.user_id)) is None


# ensure_admin_remains — ostatni aktywny admin (07 §6.2, B10).
def test_ensure_admin_remains_blocks_demoting_last_admin() -> None:
    with pytest.raises(OperationNotAllowed) as exc:
        ensure_admin_remains(True, False, 0)
    assert exc.value.message == "The last active administrator cannot be deactivated or demoted."


@pytest.mark.parametrize(
    ("target", "stays", "others"), [(True, False, 1), (True, True, 0), (False, False, 0)]
)
def test_ensure_admin_remains_allows_other_changes(target: bool, stays: bool, others: int) -> None:
    assert ensure_admin_remains(target, stays, others) is None
