"""Testy jednostkowe sondy listy modeli (K13 §4 p. 4) — transport ``httpx2.MockTransport``."""

from __future__ import annotations

from collections.abc import Callable

import httpx2
import pytest

from app.core.error_codes import RetCode
from app.core.errors import Conflict
from app.services import provider_probe

BASE_URL = "http://llm.local/v1"
KEY = "sekret-1"


def _handler(
    captured: list[httpx2.Request],
    *,
    status: int = 200,
    payload: object | None = None,
    raise_: Exception | None = None,
) -> Callable[[httpx2.Request], httpx2.Response]:
    """Handler mocka: zapisuje żądanie, zwraca odpowiedź albo rzuca wyjątek transportu."""

    def handle(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        if raise_ is not None:
            raise raise_
        if payload is None:
            return httpx2.Response(status, text="not json")
        return httpx2.Response(status, json=payload)

    return handle


def _use_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx2.Request], httpx2.Response],
) -> None:
    """Podstawia transport modułu sondy (atrybut ``_transport``)."""
    monkeypatch.setattr(provider_probe, "_transport", httpx2.MockTransport(handler))


async def test_probe_returns_sorted_ids_and_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sukces: identyfikatory ``data[].id`` posortowane, żądanie ``GET {base_url}/models``."""
    captured: list[httpx2.Request] = []
    payload = {"data": [{"id": "zeta"}, {"id": "alpha"}]}
    _use_transport(monkeypatch, _handler(captured, payload=payload))

    result = await provider_probe.probe_models(BASE_URL, KEY)

    assert result == ["alpha", "zeta"]
    assert captured[0].method == "GET"
    assert str(captured[0].url) == f"{BASE_URL}/models"
    assert captured[0].headers["authorization"] == f"Bearer {KEY}"


async def test_probe_omits_header_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Brak klucza → żądanie bez nagłówka ``Authorization`` (K13 §4 p. 4)."""
    captured: list[httpx2.Request] = []
    _use_transport(monkeypatch, _handler(captured, payload={"data": []}))

    assert await provider_probe.probe_models(BASE_URL, None) == []
    assert "authorization" not in captured[0].headers


async def test_probe_status_error_is_102(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nie-200 → 102 ``Connection failed: HTTP <status>``."""
    _use_transport(monkeypatch, _handler([], status=503, payload={"data": []}))

    with pytest.raises(Conflict) as exc:
        await provider_probe.probe_models(BASE_URL, KEY)

    assert exc.value.code == RetCode.DATA_ERROR
    assert exc.value.message == "Connection failed: HTTP 503"


async def test_probe_transport_error_names_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """Błąd transportu → 102 ``Connection failed: <klasa>`` bez treści odpowiedzi."""
    _use_transport(monkeypatch, _handler([], raise_=httpx2.ConnectError("refused")))

    with pytest.raises(Conflict) as exc:
        await provider_probe.probe_models(BASE_URL, KEY)

    assert exc.value.message == "Connection failed: ConnectError"
    assert KEY not in exc.value.message


async def test_probe_non_ascii_key_is_102(monkeypatch: pytest.MonkeyPatch) -> None:
    """Klucz spoza ASCII (kodowanie nagłówka) → 102, nie nieobsłużony wyjątek."""
    captured: list[httpx2.Request] = []
    _use_transport(monkeypatch, _handler(captured, payload={"data": []}))

    with pytest.raises(Conflict) as exc:
        await provider_probe.probe_models(BASE_URL, "zażółć-gęślą-jaźń")

    assert exc.value.message == "Connection failed: UnicodeEncodeError"


async def test_probe_invalid_json_is_102(monkeypatch: pytest.MonkeyPatch) -> None:
    """200 bez poprawnego JSON → 102 z nazwą klasy wyjątku, nigdy z treścią bramki."""
    _use_transport(monkeypatch, _handler([], payload=None))

    with pytest.raises(Conflict) as exc:
        await provider_probe.probe_models(BASE_URL, KEY)

    assert exc.value.message.startswith("Connection failed: ")
    assert KEY not in exc.value.message


async def test_probe_without_data_list_is_102(monkeypatch: pytest.MonkeyPatch) -> None:
    """200 z JSON bez listy ``data`` → 102 ``Connection failed: <klasa>``."""
    _use_transport(monkeypatch, _handler([], payload={"models": []}))

    with pytest.raises(Conflict) as exc:
        await provider_probe.probe_models(BASE_URL, KEY)

    assert exc.value.message.startswith("Connection failed: ")


def _catalog_handler(captured: list[httpx2.Request]) -> Callable[[httpx2.Request], httpx2.Response]:
    """Katalog OpenRouter: osobna lista dla każdej wartości ``output_modalities``."""
    by_modality = {
        "text": [{"id": "openai/gpt-5"}, {"id": "openai/text-embedding-3-large"}],
        "embeddings": [{"id": "openai/text-embedding-3-large"}, {"id": "baai/bge-m3"}],
        "rerank": [{"id": "voyageai/rerank-3"}],
    }

    def handle(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return httpx2.Response(
            200, json={"data": by_modality[request.url.params["output_modalities"]]}
        )

    return handle


async def test_openrouter_types_embedding_overrides_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """Model z listy ``text`` i ``embeddings`` dostaje typ embeddingu; brak nagłówka klucza."""
    captured: list[httpx2.Request] = []
    _use_transport(monkeypatch, _catalog_handler(captured))

    types = await provider_probe.fetch_openrouter_types()

    assert types == {
        "openai/gpt-5": "chat",
        "openai/text-embedding-3-large": "embedding",
        "baai/bge-m3": "embedding",
        "voyageai/rerank-3": "rerank",
    }
    assert all("authorization" not in request.headers for request in captured)


async def test_openrouter_types_failure_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Błąd katalogu nie psuje listy modeli: pusta mapa zamiast wyjątku."""
    _use_transport(monkeypatch, _handler([], raise_=httpx2.ConnectError("boom")))

    assert await provider_probe.fetch_openrouter_types() == {}
