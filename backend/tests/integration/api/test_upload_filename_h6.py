"""Dowód H6 (HTTP): nazwa uploadu z segmentem `..` nie tworzy ścieżki poza `storage_root`.

Faktyczne zachowanie (potwierdzone uruchomieniem na HEAD, wzorzec: `test_documents_routes.py`):
upload nazwy `../../etc/evil.txt` **kończy się sukcesem** (`code: 0`). Nazwa dokumentu
zostaje dosłowna, a pole `location` w odpowiedzi to — zgodnie z kontraktem C2.4 —
`row.name` (a nie klucz storage, `present/documents.py`), więc **zawiera `..` jako
metadane**. Bezpieczeństwo nie opiera się na tym polu: klucz storage liczy
`app/storage/keys.py::document_key(dataset_id, document_id, suffix)` z identyfikatorów,
więc realny plik powstaje pod `files/{ds}/{doc}/original.txt`, a kolumna `documents.location`
(storage key) nie zawiera `..`. Nazwa z backslashami (`..\\..\\x.txt`) na POSIX to jedna
nazwa pliku (`suffix` = `.txt`). Asercje pilnują stanu magazynu i kolumny `location`.

Uwaga: brief zakładał, że `location` z API nie zawiera `..` — jest odwrotnie (C2.4);
test przyjmuje faktyczne zachowanie i weryfikuje klucz storage zamiast pola `location`.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.container import Container
from app.domain.policy import Principal
from app.main import create_app
from app.services.api_keys import ApiKeyService
from app.services.users import UserService
from tests.fakes.clock import FrozenClock
from tests.fakes.ids import SeqIdGenerator
from tests.integration.datasets.conftest import seed_default_models

pytestmark = pytest.mark.db

_OK = 200
PASSWORD = "Secret-pass1"  # noqa: S105 — celowa atrapa hasła w teście
OWNER_EMAIL = "owner@x.pl"
STORAGE_PREFIX = "files/"

# Nazwy z próbą wyjścia z katalogu: separator POSIX i Windows.
TRAVERSAL_NAMES = ("../../etc/evil.txt", "..\\..\\x.txt")


@pytest.fixture
def settings(auth_settings: Settings, tmp_path: Any) -> Settings:
    """Ustawienia auth + storage_root w katalogu tymczasowym (wzór test_documents_routes)."""
    return auth_settings.model_copy(update={"storage_root": str(tmp_path)})


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """Aplikacja na świeżej, zmigrowanej bazie; lifespan startuje kontener."""
    with TestClient(
        create_app(settings, Container(settings)), base_url="https://testserver"
    ) as test_client:
        yield test_client


@pytest.fixture
async def owner(sm: async_sessionmaker[AsyncSession], auth_settings: Settings) -> str:
    """Konto z jawnym kluczem API; zwraca token (plus modele domyślne w bazie)."""
    await seed_default_models(sm)
    users = UserService(sm, auth_settings, FrozenClock(), SeqIdGenerator())
    keys = ApiKeyService(sm, auth_settings, FrozenClock(), SeqIdGenerator())
    user = await users.create(email=OWNER_EMAIL, password=PASSWORD, is_superuser=False)
    principal = Principal(user.id, user.email, user.is_superuser, user.is_service, "jwt")
    return (await keys.create(principal)).token


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_dataset(client: TestClient, token: str) -> str:
    """POST /datasets z asercją code 0; zwraca id datasetu."""
    response = client.post("/api/v1/datasets", headers=_bearer(token), json={"name": "wd_h6"})
    payload = response.json()
    assert payload["code"] == 0, payload
    dataset_id: str = payload["data"]["id"]
    return dataset_id


def upload(client: TestClient, token: str, dataset_id: str, name: str) -> dict[str, Any]:
    """POST multipart z jednym plikiem; zwraca element ``data[0]`` (asercja code 0)."""
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers=_bearer(token),
        files={"file": (name, b"evil")},
    )
    assert response.status_code == _OK
    body = response.json()
    assert body["code"] == 0, body
    element: dict[str, Any] = body["data"][0]
    return element


def _assert_no_escape(storage_root: str, name: str) -> str:
    """Pilnuje, że magazyn nie wyszedł poza `storage_root`; zwraca klucz storage pliku."""
    root = Path(storage_root).resolve()
    # Nic nie wylądowało poza storage_root — ani `etc/`, ani ścieżka po normalizacji `..`.
    assert not (root.parent / "etc").exists()
    assert not (root / name).resolve().exists()

    files = [path for path in root.rglob("*") if path.is_file()]
    assert len(files) == 1
    storage_key = files[0].relative_to(root).as_posix()
    assert str(files[0].resolve()).startswith(str(root) + "/")
    assert storage_key.startswith(STORAGE_PREFIX)
    assert ".." not in storage_key.split("/")
    assert storage_key.endswith("/original.txt")
    return storage_key


async def _stored_locations(sm: async_sessionmaker[AsyncSession], dataset_id: str) -> list[str]:
    """Kolumna `documents.location` (klucz storage) dla datasetu."""
    async with sm() as session:
        result = await session.execute(
            text("SELECT location FROM documents WHERE dataset_id = :ds"), {"ds": dataset_id}
        )
        return list(result.scalars().all())


@pytest.mark.parametrize("name", TRAVERSAL_NAMES)
async def test_upload_traversal_name_stays_inside_storage_root(
    client: TestClient,
    owner: str,
    settings: Settings,
    sm: async_sessionmaker[AsyncSession],
    name: str,
) -> None:
    """Sukces; plik i storage key wyłącznie w `storage_root`, kolumna bez `..`."""
    dataset_id = create_dataset(client, owner)
    element = upload(client, owner, dataset_id, name)

    # C2.4: pole `location` w odpowiedzi to nazwa dokumentu (metadane, nie ścieżka).
    assert element["name"] == name
    assert element["location"] == name

    storage_key = _assert_no_escape(settings.storage_root, name)

    # Kolumna `documents.location` (storage key, kontrakt C2.4) jest dokładnie kluczem pliku.
    assert await _stored_locations(sm, dataset_id) == [storage_key]

    listed = client.get(
        f"/api/v1/datasets/{dataset_id}/documents",
        headers=_bearer(owner),
        params={"page": 1, "page_size": 30},
    )
    docs = listed.json()["data"]["docs"]
    assert [doc["name"] for doc in docs] == [name]
    for doc in docs:
        assert doc["location"] == doc["name"]
