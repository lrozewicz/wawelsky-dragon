"""Testy TokenProvider i wyjątków SharePoint (WP E4-2a) — httpx.MockTransport, bez sieci."""

import asyncio
import logging
import urllib.parse
from collections.abc import Callable

import httpx
import pytest

from app.integrations.sharepoint.auth import (
    REFRESH_MARGIN_S,
    SCOPE,
    TOKEN_URL_TEMPLATE,
    TokenProvider,
)
from app.integrations.sharepoint.errors import (
    GraphAuthError,
    GraphError,
    GraphNotFound,
    SizeLimitExceeded,
)
from tests.unit.integrations.sharepoint.conftest import FakeClock, load_fixture

TENANT = "T1"
CLIENT = "C1"
CREDENTIAL = "s3cret"
OTHER_CREDENTIAL = "other-s3cret"
TOKEN_URL = TOKEN_URL_TEMPLATE.format(tenant_id=TENANT)
EXPIRES_IN = 3599
ONE_REQUEST = 1
TWO_REQUESTS = 2
MAX_BYTES = 1024

Handler = Callable[[httpx.Request], httpx.Response]


def make_http(handler: Handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def make_provider(
    http: httpx.AsyncClient,
    clock: Callable[[], float],
    *,
    client_id: str = CLIENT,
    client_secret: str = CREDENTIAL,
) -> TokenProvider:
    return TokenProvider(
        http, tenant_id=TENANT, client_id=client_id, client_secret=client_secret, clock=clock
    )


def recording(factory: Handler) -> tuple[Handler, list[httpx.Request]]:
    """Opakowuje handler MockTransport licznikiem odebranych żądań."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return factory(request)

    return handler, seen


def token_ok() -> tuple[Handler, list[httpx.Request]]:
    return recording(lambda request: httpx.Response(200, json=load_fixture("token_ok.json")))


async def test_first_get_token_posts_form(clock: FakeClock) -> None:
    handler, seen = token_ok()
    async with make_http(handler) as http:
        provider = make_provider(http, clock)
        assert await provider.get_token() == "tok-abc"

    assert len(seen) == ONE_REQUEST
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == TOKEN_URL == "https://login.microsoftonline.com/T1/oauth2/v2.0/token"
    form = urllib.parse.parse_qs(request.content.decode())
    assert form["grant_type"] == ["client_credentials"]
    assert form["scope"] == [SCOPE]
    assert form["client_id"] == [CLIENT]
    assert form["client_secret"] == [CREDENTIAL]


async def test_login_base_url_override(clock: FakeClock) -> None:
    """`login_base_url` nadpisuje domyślny host logowania (kontrakt C2, brief T1)."""
    handler, seen = token_ok()
    async with make_http(handler) as http:
        provider = TokenProvider(
            http,
            tenant_id=TENANT,
            client_id=CLIENT,
            client_secret=CREDENTIAL,
            login_base_url="http://fake-login:8095",
            clock=clock,
        )
        assert await provider.get_token() == "tok-abc"

    assert len(seen) == ONE_REQUEST
    assert str(seen[0].url) == "http://fake-login:8095/T1/oauth2/v2.0/token"


async def test_second_get_token_uses_cache(clock: FakeClock) -> None:
    handler, seen = token_ok()
    async with make_http(handler) as http:
        provider = make_provider(http, clock)
        assert await provider.get_token() == "tok-abc"
        assert await provider.get_token() == "tok-abc"

    assert len(seen) == ONE_REQUEST


async def test_refreshes_inside_margin(clock: FakeClock) -> None:
    """Mniej niż REFRESH_MARGIN_S przed wygaśnięciem → nowe żądanie."""
    handler, seen = token_ok()
    async with make_http(handler) as http:
        provider = make_provider(http, clock)
        await provider.get_token()
        clock.advance(EXPIRES_IN - (REFRESH_MARGIN_S - 1))
        await provider.get_token()

    assert len(seen) == TWO_REQUESTS


async def test_reuses_just_outside_margin(clock: FakeClock) -> None:
    """Jeszcze więcej niż REFRESH_MARGIN_S zapasu → z cache."""
    handler, seen = token_ok()
    async with make_http(handler) as http:
        provider = make_provider(http, clock)
        await provider.get_token()
        clock.advance(EXPIRES_IN - (REFRESH_MARGIN_S + 1))
        await provider.get_token()

    assert len(seen) == ONE_REQUEST


async def test_force_refresh_ignores_cache(clock: FakeClock) -> None:
    handler, seen = token_ok()
    async with make_http(handler) as http:
        provider = make_provider(http, clock)
        await provider.get_token()
        await provider.get_token(force_refresh=True)

    assert len(seen) == TWO_REQUESTS


async def test_cache_shared_between_instances_by_key(clock: FakeClock) -> None:
    handler, seen = token_ok()
    async with make_http(handler) as http:
        first = make_provider(http, clock)
        second = make_provider(http, clock)
        assert await first.get_token() == "tok-abc"
        assert await second.get_token() == "tok-abc"
        other = make_provider(http, clock, client_id="C2")
        await other.get_token()

    assert len(seen) == TWO_REQUESTS


async def test_cache_key_separates_different_secrets(clock: FakeClock) -> None:
    """Zły sekret nie dostaje z cache tokenu pobranego poprawnym sekretem (kontrakt C3)."""

    def handler(request: httpx.Request) -> httpx.Response:
        form = urllib.parse.parse_qs(request.content.decode())
        if form["client_secret"] == [CREDENTIAL]:
            return httpx.Response(200, json=load_fixture("token_ok.json"))
        return httpx.Response(
            400, json={"error": "invalid_client", "error_description": "bad secret"}
        )

    guarded, seen = recording(handler)
    async with make_http(guarded) as http:
        good = make_provider(http, clock)
        bad = make_provider(http, clock, client_secret=OTHER_CREDENTIAL)
        assert await good.get_token() == "tok-abc"
        with pytest.raises(GraphAuthError):
            await bad.get_token()

    assert len(seen) == TWO_REQUESTS


async def test_invalidate_forces_new_request(clock: FakeClock) -> None:
    handler, seen = token_ok()
    async with make_http(handler) as http:
        provider = make_provider(http, clock)
        await provider.get_token()
        provider.invalidate()
        await provider.get_token()

    assert len(seen) == TWO_REQUESTS


async def test_401_raises_graph_auth_error_without_secret(
    clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    handler, seen = recording(
        lambda request: httpx.Response(401, json=load_fixture("token_error.json"))
    )
    caplog.set_level(logging.DEBUG)
    async with make_http(handler) as http:
        provider = make_provider(http, clock)
        with pytest.raises(GraphAuthError) as excinfo:
            await provider.get_token()

    assert str(excinfo.value) == "AADSTS7000215: Invalid client secret provided."
    assert excinfo.value.description == "AADSTS7000215: Invalid client secret provided."
    assert CREDENTIAL not in str(excinfo.value)
    assert CREDENTIAL not in repr(excinfo.value)
    assert CREDENTIAL not in caplog.text
    assert len(seen) == ONE_REQUEST


async def test_non_json_error_body_reports_status(clock: FakeClock) -> None:
    handler, _ = recording(lambda request: httpx.Response(500, text="<html>boom</html>"))
    async with make_http(handler) as http:
        provider = make_provider(http, clock)
        with pytest.raises(GraphAuthError) as excinfo:
            await provider.get_token()

    assert str(excinfo.value) == "token endpoint returned HTTP 500"


async def test_json_array_error_body_reports_status(clock: FakeClock) -> None:
    handler, _ = recording(lambda request: httpx.Response(400, json=["nope"]))
    async with make_http(handler) as http:
        provider = make_provider(http, clock)
        with pytest.raises(GraphAuthError) as excinfo:
            await provider.get_token()

    assert str(excinfo.value) == "token endpoint returned HTTP 400"


async def test_200_without_access_token_raises(clock: FakeClock) -> None:
    handler, _ = recording(lambda request: httpx.Response(200, json={"token_type": "Bearer"}))
    async with make_http(handler) as http:
        provider = make_provider(http, clock)
        with pytest.raises(GraphAuthError) as excinfo:
            await provider.get_token()

    assert str(excinfo.value) == "token endpoint returned HTTP 200"


async def test_transport_error_raises_unreachable(clock: FakeClock) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    handler, _ = recording(boom)
    async with make_http(handler) as http:
        provider = make_provider(http, clock)
        with pytest.raises(GraphAuthError) as excinfo:
            await provider.get_token()

    assert str(excinfo.value) == "token endpoint unreachable"


async def test_concurrent_calls_share_one_request(clock: FakeClock) -> None:
    handler, seen = token_ok()
    async with make_http(handler) as http:
        provider = make_provider(http, clock)
        tokens = await asyncio.gather(*[provider.get_token() for _ in range(5)])

    assert tokens == ["tok-abc"] * 5
    assert len(seen) == ONE_REQUEST


def test_graph_error_str_and_fields() -> None:
    error = GraphError(429, "tooManyRequests", "slow")
    assert str(error) == "429 tooManyRequests: slow"
    assert (error.status, error.code, error.message) == (429, "tooManyRequests", "slow")


def test_graph_not_found_is_graph_error() -> None:
    error = GraphNotFound(410, "resyncRequired", "delta token expired")
    assert isinstance(error, GraphError)
    assert error.status == httpx.codes.GONE
    assert str(error) == "410 resyncRequired: delta token expired"


def test_graph_auth_error_description() -> None:
    error = GraphAuthError("boom")
    assert error.description == "boom"
    assert str(error) == "boom"


def test_size_limit_exceeded_field() -> None:
    assert SizeLimitExceeded(MAX_BYTES).max_bytes == MAX_BYTES
