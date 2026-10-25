"""Testy polityki grantów czatu (brief T3, kontrakt C6) — czyste funkcje, bez I/O i DB."""

from app.domain.policy import Action, Principal, ResourceRef, can, visibility_filter

# E-mail principala w innej wielkości liter niż w grancie (grant = READ+USE, case-insensitive).
GRANTEE = Principal("b" * 32, "A@X.PL", False, False, "api_key")
OWNER = Principal("a" * 32, "owner@x.pl", False, False, "jwt")
CHAT_ID = "c" * 32


def _granted() -> ResourceRef:
    """Czat właściciela z grantem dla GRANTEE (e-mail w bazie niższymi literami)."""
    return ResourceRef("chat", OWNER.user_id, id=CHAT_ID, chat_grant_emails=frozenset({"a@x.pl"}))


def test_grant_allows_read_and_use() -> None:
    """Grant daje READ i USE czatu (K7 §1.11, C6)."""
    assert can(GRANTEE, Action.READ, _granted()) is True
    assert can(GRANTEE, Action.USE, _granted()) is True


def test_grant_denies_update_and_delete() -> None:
    """Grant nie daje UPDATE ani DELETE czatu (C6 — te akcje tylko dla właściciela)."""
    assert can(GRANTEE, Action.UPDATE, _granted()) is False
    assert can(GRANTEE, Action.DELETE, _granted()) is False


def test_without_grant_denied() -> None:
    """Bez grantu cudzy czat nie daje ani READ, ani USE (C6)."""
    ref = ResourceRef("chat", OWNER.user_id, id=CHAT_ID)
    assert can(GRANTEE, Action.READ, ref) is False
    assert can(GRANTEE, Action.USE, ref) is False


def test_visibility_filter_carries_grants_for_chat() -> None:
    """visibility_filter("chat", granted_ids) niesie granty obok id właściciela (C6)."""
    filtr = visibility_filter(GRANTEE, "chat", frozenset({"c1"}))
    assert filtr.granted_ids == frozenset({"c1"})
    assert filtr.owner_ids == frozenset({GRANTEE.user_id})
    assert filtr.all is False


def test_visibility_filter_ignores_grants_for_other_kinds() -> None:
    """Dla rodzajów innych niż chat granted_ids są ignorowane (C6)."""
    assert visibility_filter(GRANTEE, "dataset", frozenset({"c1"})).granted_ids == frozenset()
