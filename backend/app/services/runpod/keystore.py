"""Klucz API RunPod w ``wd_settings`` (zaszyfrowany kluczem instancji, AAD ``runpod-api-key``)."""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING

from app.core.crypto import decrypt, encrypt
from app.core.errors import Conflict
from app.db.repositories import wd_settings
from app.db.uow import transaction
from app.services.runpod.client import HttpClient, RunpodClient

if TYPE_CHECKING:
    from app.core.container import Container

SETTING_NAME = "runpod_api_key"
_AAD = b"runpod-api-key"
MSG_NO_KEY = "RunPod API key is not configured (Settings → RunPod)"


async def load_key(container: Container) -> str | None:
    """Odszyfrowany klucz API RunPod albo ``None``, gdy go nie zapisano."""
    assert container.sessionmaker is not None  # noqa: S101
    async with transaction(container.sessionmaker) as session:
        stored = await wd_settings.get_value(session, SETTING_NAME)
    if stored is None:
        return None
    blob = base64.b64decode(stored)
    return decrypt(container.settings.crypto_key.get_secret_value(), blob, _AAD).decode()


async def save_key(container: Container, api_key: str) -> None:
    """Szyfruje i zapisuje klucz (nadpisuje poprzedni)."""
    assert container.sessionmaker is not None  # noqa: S101
    blob = encrypt(container.settings.crypto_key.get_secret_value(), api_key.encode(), _AAD)
    async with transaction(container.sessionmaker) as session:
        await wd_settings.set_value(
            session, SETTING_NAME, base64.b64encode(blob).decode(), now_ms=container.clock.now_ms()
        )


async def delete_key(container: Container) -> None:
    """Usuwa zapisany klucz."""
    assert container.sessionmaker is not None  # noqa: S101
    async with transaction(container.sessionmaker) as session:
        await wd_settings.delete_value(session, SETTING_NAME)


async def client_for(container: Container, *, http: HttpClient | None = None) -> RunpodClient:
    """Klient RunPod z zapisanym kluczem; brak klucza → ``Conflict`` (409)."""
    key = await load_key(container)
    if key is None:
        raise Conflict(MSG_NO_KEY)
    # ``container.runpod_http``: klient wstrzykiwany w testach (``httpx.MockTransport``).
    return RunpodClient(key, client=http or getattr(container, "runpod_http", None))
