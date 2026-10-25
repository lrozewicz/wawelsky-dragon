"""Testy OidcService na lokalnym FakeIdP po prawdziwym HTTP (brief T6, kontrakt C10)."""

import time
from collections.abc import AsyncIterator, Iterator
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import ValidationFailed
from app.db.repositories import users as users_repo
from app.db.uow import transaction
from app.services.auth_passwords import verify_password
from app.services.oidc import OidcError, OidcService, safe_redirect
from app.services.users import UserService
from tests.fakes.clock import FrozenClock
from tests.fakes.ids import SeqIdGenerator
from tests.fakes.oidc_idp import FakeIdP

pytestmark = pytest.mark.db

PASSWORD = "Secret-pass1"  # noqa: S105 — celowa atrapa hasła w teście


@pytest.fixture
def idp() -> Iterator[FakeIdP]:
    with FakeIdP() as fake:
        yield fake


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock()


@pytest.fixture
def settings(auth_settings: Settings, idp: FakeIdP) -> Settings:
    """Ustawienia wg briefu T6: FakeIdP jako issuer, role/grupy admina, publiczny URL."""
    return auth_settings.model_copy(
        update={
            "oidc_issuer": idp.issuer,
            "oidc_client_id": idp.client_id,
            "oidc_client_secret": SecretStr(idp.client_secret),
            "oidc_admin_roles": "wd-admin",
            "oidc_admin_groups": "wd-admins",
            "public_base_url": "http://localhost:8080",
        }
    )


def _svc(
    settings: Settings, sm: async_sessionmaker[AsyncSession], clock: FrozenClock
) -> OidcService:
    """Konstrukcja z briefu: OidcService(settings, clock, id_gen, http, users, sm)."""
    return OidcService(
        settings,
        clock,
        SeqIdGenerator(),
        httpx.AsyncClient(),
        UserService(sm, settings, clock, SeqIdGenerator()),
        sm,
    )


@pytest.fixture
async def svc(
    settings: Settings, sm: async_sessionmaker[AsyncSession], clock: FrozenClock
) -> AsyncIterator[OidcService]:
    service = _svc(settings, sm, clock)
    yield service
    await service.aclose()


async def _flow(svc: OidcService, idp: FakeIdP, *, sub: str, email: str | None, **kw: object):
    start = await svc.begin("/chat?x=1")
    code, state = idp.authorize(start.redirect_url, sub=sub, email=email, **kw)  # type: ignore[arg-type]
    return await svc.complete(code=code, state=state, state_cookie=start.state_cookie)


async def test_begin_builds_authorization_url(svc: OidcService, idp: FakeIdP) -> None:
    s = await svc.begin("/chat?x=1")
    assert s.redirect_url.startswith(idp.issuer + "/auth?")
    query = dict(parse_qsl(urlsplit(s.redirect_url).query))
    assert query["response_type"] == "code"
    assert query["client_id"] == idp.client_id
    assert query["redirect_uri"] == "http://localhost:8080/api/v1/auth/oauth/keycloak/callback"
    assert query["scope"] == "openid email profile"
    assert query["code_challenge_method"] == "S256"
    assert query["state"]
    assert query["nonce"]
    assert query["code_challenge"]


def test_safe_redirect_fallbacks() -> None:
    assert safe_redirect(None) == "/"
    assert safe_redirect("") == "/"
    assert safe_redirect("/a/b?c=1") == "/a/b?c=1"


@pytest.mark.parametrize(
    "value",
    [
        "https://evil.example",
        "//evil.example",
        "/\\evil.example",
        "/a\\b",
        "javascript:alert(1)",
        "/x\n",
        "evil",
    ],
)
def test_safe_redirect_rejects(value: str) -> None:
    with pytest.raises(ValidationFailed, match="Invalid redirect"):
        safe_redirect(value)


async def test_begin_rejects_external_redirect(svc: OidcService) -> None:
    with pytest.raises(ValidationFailed, match="Invalid redirect"):
        await svc.begin("https://evil.example")


async def test_full_flow_provisions_user(svc: OidcService, idp: FakeIdP) -> None:
    s = await svc.begin("/chat?x=1")
    code, state = idp.authorize(s.redirect_url, sub="sub-1", email="Ala@X.pl")
    user, redirect = await svc.complete(code=code, state=state, state_cookie=s.state_cookie)
    assert user.email == "ala@x.pl"
    assert user.auth_source == "oidc"
    assert user.oidc_sub == "sub-1"
    assert user.password_hash is None
    assert user.is_superuser is False
    assert redirect == "/chat?x=1"


async def test_admin_role_granted_bumps_token_version(svc: OidcService, idp: FakeIdP) -> None:
    first, _ = await _flow(svc, idp, sub="sub-1", email="Ala@X.pl")
    second, _ = await _flow(svc, idp, sub="sub-1", email="Ala@X.pl", roles=("wd-admin",))
    assert second.id == first.id
    assert second.is_superuser is True
    assert second.token_version == first.token_version + 1


async def test_admin_group_keeps_admin_without_bump(svc: OidcService, idp: FakeIdP) -> None:
    first, _ = await _flow(svc, idp, sub="sub-1", email="Ala@X.pl", roles=("wd-admin",))
    second, _ = await _flow(svc, idp, sub="sub-1", email="Ala@X.pl", groups=("/wd-admins",))
    assert second.id == first.id
    assert second.is_superuser is True
    assert second.token_version == first.token_version


async def test_role_revoked_when_other_admin_exists(
    svc: OidcService,
    idp: FakeIdP,
    settings: Settings,
    sm: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> None:
    # OidcService i UserService mają niezależne sekwencje id (konstrukcja z briefu);
    # zużywam pierwsze id z sekwencji UserService, by nie kolidowało z provisioningiem svc.
    user_ids = SeqIdGenerator()
    user_ids.new_id()
    users = UserService(sm, settings, clock, user_ids)
    await users.create(email="drugi-admin@x.pl", password=PASSWORD, is_superuser=True)
    await _flow(svc, idp, sub="sub-1", email="Ala@X.pl", roles=("wd-admin",))
    user, _ = await _flow(svc, idp, sub="sub-1", email="Ala@X.pl")
    assert user.is_superuser is False


async def test_revoking_last_admin_rejected(svc: OidcService, idp: FakeIdP) -> None:
    await _flow(svc, idp, sub="sub-1", email="Ala@X.pl", roles=("wd-admin",))
    with pytest.raises(OidcError) as exc:
        await _flow(svc, idp, sub="sub-1", email="Ala@X.pl")
    assert exc.value.slug == "last_admin"


async def test_links_local_account(
    svc: OidcService,
    idp: FakeIdP,
    settings: Settings,
    sm: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> None:
    users = UserService(sm, settings, clock, SeqIdGenerator())
    local = await users.create(email="bob@x.pl", password=PASSWORD)
    user, _ = await _flow(svc, idp, sub="sub-b", email="bob@x.pl")
    assert user.id == local.id
    assert user.auth_source == "both"
    assert user.oidc_sub == "sub-b"
    assert verify_password(user.password_hash or "", PASSWORD)


async def test_email_not_verified_leaves_account_unlinked(
    svc: OidcService, idp: FakeIdP, sm: async_sessionmaker[AsyncSession]
) -> None:
    with pytest.raises(OidcError) as exc:
        await _flow(svc, idp, sub="sub-1", email="Ala@X.pl", email_verified=False)
    assert exc.value.slug == "email_not_verified"
    async with transaction(sm) as session:
        assert await users_repo.get_by_email(session, "ala@x.pl") is None


async def test_email_missing(svc: OidcService, idp: FakeIdP) -> None:
    with pytest.raises(OidcError) as exc:
        await _flow(svc, idp, sub="sub-1", email=None)
    assert exc.value.slug == "email_missing"


async def test_registration_disabled(
    auth_settings: Settings, idp: FakeIdP, sm: async_sessionmaker[AsyncSession], clock: FrozenClock
) -> None:
    settings = auth_settings.model_copy(
        update={
            "oidc_issuer": idp.issuer,
            "oidc_client_id": idp.client_id,
            "oidc_client_secret": SecretStr(idp.client_secret),
            "oidc_auto_register": False,
        }
    )
    service = _svc(settings, sm, clock)
    try:
        with pytest.raises(OidcError) as exc:
            await _flow(service, idp, sub="sub-9", email="nowy@x.pl")
        assert exc.value.slug == "registration_disabled"
        async with transaction(sm) as session:
            assert await users_repo.get_by_email(session, "nowy@x.pl") is None
    finally:
        await service.aclose()


async def test_inactive_user_rejected(
    svc: OidcService,
    idp: FakeIdP,
    settings: Settings,
    sm: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> None:
    users = UserService(sm, settings, clock, SeqIdGenerator())
    row = await users.create(email="bob@x.pl", password=PASSWORD)
    await users.set_active(row.id, False)
    with pytest.raises(OidcError) as exc:
        await _flow(svc, idp, sub="sub-b", email="bob@x.pl")
    assert exc.value.slug == "user_inactive"


async def test_invalid_state_variants(svc: OidcService, idp: FakeIdP) -> None:
    s = await svc.begin("/chat?x=1")
    code, state = idp.authorize(s.redirect_url, sub="sub-1", email="Ala@X.pl")
    other = await svc.begin("/chat?x=1")
    variants: list[dict[str, object]] = [
        {"code": code, "state": state, "state_cookie": None},
        {"code": code, "state": state, "state_cookie": other.state_cookie},
        {"code": code, "state": "zly", "state_cookie": s.state_cookie},
    ]
    for kwargs in variants:
        with pytest.raises(OidcError) as exc:
            await svc.complete(**kwargs)  # type: ignore[arg-type]
        assert exc.value.slug == "invalid_state"


async def test_expired_state_cookie(svc: OidcService, idp: FakeIdP, clock: FrozenClock) -> None:
    s = await svc.begin("/chat?x=1")
    code, state = idp.authorize(s.redirect_url, sub="sub-1", email="Ala@X.pl")
    clock.advance(601_000)
    with pytest.raises(OidcError) as exc:
        await svc.complete(code=code, state=state, state_cookie=s.state_cookie)
    assert exc.value.slug == "invalid_state"


async def test_missing_code(svc: OidcService) -> None:
    s = await svc.begin("/chat?x=1")
    state = dict(parse_qsl(urlsplit(s.redirect_url).query))["state"]
    with pytest.raises(OidcError) as exc:
        await svc.complete(code=None, state=state, state_cookie=s.state_cookie)
    assert exc.value.slug == "missing_code"


async def test_unknown_code_token_failed(svc: OidcService) -> None:
    s = await svc.begin("/chat?x=1")
    state = dict(parse_qsl(urlsplit(s.redirect_url).query))["state"]
    with pytest.raises(OidcError) as exc:
        await svc.complete(code="nieznany", state=state, state_cookie=s.state_cookie)
    assert exc.value.slug == "token_failed"


@pytest.mark.parametrize(
    "kw",
    [
        {"sign_with_other_key": True},
        {"alg_none": True},
        {"id_overrides": {"iss": "http://inny"}},
        {"id_overrides": {"aud": "inny"}},
        {"id_overrides": {"nonce": "zly"}},
        {"id_overrides": {"exp": int(time.time()) - 10}},
    ],
)
async def test_invalid_id_token(svc: OidcService, idp: FakeIdP, kw: dict[str, object]) -> None:
    s = await svc.begin("/chat?x=1")
    code, state = idp.authorize(s.redirect_url, sub="sub-1", email="Ala@X.pl", **kw)  # type: ignore[arg-type]
    with pytest.raises(OidcError) as exc:
        await svc.complete(code=code, state=state, state_cookie=s.state_cookie)
    assert exc.value.slug == "invalid_token"


async def test_discovery_cached(svc: OidcService, idp: FakeIdP) -> None:
    await svc.discovery()
    await svc.discovery()
    assert idp.requests.count("/.well-known/openid-configuration") == 1


async def test_logout_url(
    auth_settings: Settings, idp: FakeIdP, sm: async_sessionmaker[AsyncSession], clock: FrozenClock
) -> None:
    settings = auth_settings.model_copy(
        update={
            "oidc_issuer": idp.issuer,
            "oidc_client_id": idp.client_id,
            "oidc_client_secret": SecretStr(idp.client_secret),
            "oidc_logout_redirect": "http://localhost:8080/",
        }
    )
    service = _svc(settings, sm, clock)
    try:
        url = await service.logout_url()
    finally:
        await service.aclose()
    end_session = idp.issuer + "/logout"
    query = urlencode(
        {"client_id": "wawelsky-dragon", "post_logout_redirect_uri": "http://localhost:8080/"}
    )
    assert url == f"{end_session}?{query}"


async def test_logout_url_none_without_redirect(
    settings: Settings, sm: async_sessionmaker[AsyncSession], clock: FrozenClock
) -> None:
    service = _svc(settings, sm, clock)  # oidc_logout_redirect domyślnie pusty
    try:
        assert await service.logout_url() is None
    finally:
        await service.aclose()


async def test_enabled_false_without_issuer(
    auth_settings: Settings, sm: async_sessionmaker[AsyncSession], clock: FrozenClock
) -> None:
    service = _svc(auth_settings, sm, clock)  # pusty oidc_issuer
    try:
        assert service.enabled is False
    finally:
        await service.aclose()
