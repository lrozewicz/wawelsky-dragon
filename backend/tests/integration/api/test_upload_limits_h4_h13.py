"""Testy integracyjne H4 (limit 100 plików) i H13 (SSRF „nie dotyczy"; DEC-213).

Reużywa fixture'y i pomocników z ``test_datasets_security.py`` (ten sam wzorzec uploadu).
Wymaga stosu testowego (MariaDB + fake-llm):

    eval "$(tools/dev/up.sh test env)"; tools/dev/up.sh test up mariadb-test fake-llm
    cd backend && uv run pytest tests/integration/api/test_upload_limits_h4_h13.py -q

Wyrocznia mutacji: ``tools/dev/mutation-check.sh backend/tests/mutations/e5-2a-h4.patch``
z testem ``tests/integration/api/test_upload_limits_h4_h13.py::test_over_limit_101_files_rejected``.
"""

import re
import urllib.request

import httpx
import httpx2
import pytest
from fastapi.testclient import TestClient

from app.core.error_codes import RetCode
from tests.integration.api import test_datasets_security as _base

# Fixture'y bazowe z ``test_datasets_security.py`` rejestrujemy w tym module pod nazwami base_*
# (przypisanie funkcji z markerem @pytest.fixture działa jak reeksport), a lokalne ``client``/
# ``alice`` je przekazują. Nazwy nie kolidują z parametrami testów (ruff F811), a łańcuch
# zależności (settings → auth_settings; alice → users_svc/keys_svc/models_seeded) się rozwiązuje.
base_client = _base.client
base_alice = _base.alice
users_svc = _base.users_svc
keys_svc = _base.keys_svc
models_seeded = _base.models_seeded
settings = _base.settings
_bearer = _base._bearer
create_dataset = _base.create_dataset

pytestmark = pytest.mark.db

FILES_IN_LIMIT = 100
HTTP_OK = 200
METADATA_URL = "http://169.254.169.254/latest/meta-data/"


def _many_files(count: int) -> list[tuple[str, tuple[str, bytes]]]:
    """Lista części multipart ``file`` o nazwach ``a{i}.txt`` (żądanie wieloplikowe)."""
    return [("file", (f"a{i}.txt", b"x")) for i in range(count)]


@pytest.fixture
def client(request: pytest.FixtureRequest) -> TestClient:
    """TestClient z ``test_datasets_security`` (ta sama aplikacja, ten sam wzorzec uploadu)."""
    return request.getfixturevalue("base_client")


@pytest.fixture
def alice(request: pytest.FixtureRequest) -> tuple[str, str]:
    """Właścicielka datasetu (token, user_id) z ``test_datasets_security``."""
    return request.getfixturevalue("base_alice")


def _documents_total(client: TestClient, token: str, dataset_id: str) -> int:
    listing = client.get(f"/api/v1/datasets/{dataset_id}/documents", headers=_bearer(token))
    assert listing.status_code == HTTP_OK
    return int(listing.json()["data"]["total"])


def test_over_limit_101_files_rejected(client: TestClient, alice: tuple[str, str]) -> None:
    """101 plików → odpowiedź błędu (kod 101), a lista dokumentów datasetu pusta (H4)."""
    token, _user_id = alice
    created = create_dataset(client, token, {"name": "h4-over"})
    response = client.post(
        f"/api/v1/datasets/{created['id']}/documents",
        headers=_bearer(token),
        files=_many_files(FILES_IN_LIMIT + 1),
    )
    assert response.status_code == HTTP_OK
    payload = response.json()
    assert payload["code"] == RetCode.ARGUMENT_ERROR, payload
    assert "Too many files: 101 (max 100 per request)" in payload["message"]
    assert _documents_total(client, token, created["id"]) == 0


def test_at_limit_100_files_accepted(client: TestClient, alice: tuple[str, str]) -> None:
    """Dokładnie 100 plików → sukces (kod 0) i 100 dokumentów w liście (H4)."""
    token, _user_id = alice
    created = create_dataset(client, token, {"name": "h4-at"})
    response = client.post(
        f"/api/v1/datasets/{created['id']}/documents",
        headers=_bearer(token),
        files=_many_files(FILES_IN_LIMIT),
    )
    assert response.status_code == HTTP_OK
    assert response.json()["code"] == 0, response.json()
    assert _documents_total(client, token, created["id"]) == FILES_IN_LIMIT


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Blokuje wyjście na sieć; zwraca listę wywołań (pusta = nikt nie próbował).

    ``socket.socket.connect`` pomijamy świadomie: baza łączy się po TCP. Nie dotykamy też
    ``httpx2.Client.send`` ani ``httpx.Client.send`` — ``TestClient`` (starlette) dziedziczy
    po ``httpx2.Client`` i sam by się zablokował. Blokujemy realne klienty wyjściowe aplikacji
    (``httpx``/``httpx2`` w wariancie async) oraz ``urllib``.
    """
    calls: list[str] = []

    def boom(*args: object, **kwargs: object) -> None:
        calls.append("network")
        raise AssertionError("network used")

    monkeypatch.setattr(httpx.AsyncClient, "send", boom)
    monkeypatch.setattr(httpx2.AsyncClient, "send", boom)
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    return calls


def test_metadata_url_is_ignored_without_network(
    no_network: list[str], client: TestClient, alice: tuple[str, str]
) -> None:
    """H13: ``?type=web&url=169.254.169.254`` → zwykły upload, zero połączeń wychodzących."""
    token, _user_id = alice
    created = create_dataset(client, token, {"name": "h13"})
    response = client.post(
        f"/api/v1/datasets/{created['id']}/documents",
        params={"type": "web", "url": METADATA_URL},
        headers=_bearer(token),
        files=[("file", ("a.txt", b"hello"))],
    )
    assert response.status_code == HTTP_OK
    assert response.json()["code"] == 0, response.json()
    assert _documents_total(client, token, created["id"]) == 1
    assert no_network == []


def test_no_crawl_or_web_route_registered(client: TestClient) -> None:
    """H13: brak trasy pobierania URL (``crawl`` ani segmentu ``/web``) w tabeli tras."""
    web_segment = re.compile(r"(^|/)web(/|$)")
    offenders = [
        path
        for route in client.app.routes
        if web_segment.search(path := getattr(route, "path", "")) or "crawl" in path
    ]
    assert offenders == []
