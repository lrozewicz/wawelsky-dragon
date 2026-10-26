"""Lista bramki ``?supported=true``: typy i modele z katalogu OpenRouter dla bramek OpenRouter."""

from __future__ import annotations

import pytest

from app.services import instance_models, provider_probe

CATALOG = {
    "openai/gpt-5": "chat",
    "openai/text-embedding-3-large": "embedding",
    "voyageai/rerank-3": "rerank",
}


@pytest.fixture
def catalog(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Podstawia katalog OpenRouter; zwraca licznik wywołań."""
    calls: list[int] = []

    async def fake() -> dict[str, str]:
        calls.append(1)
        return dict(CATALOG)

    monkeypatch.setattr(provider_probe, "fetch_openrouter_types", fake)
    return calls


async def test_litellm_wildcard_is_expanded_with_prefixed_catalog(catalog: list[int]) -> None:
    """`openrouter/*` znika, modele z katalogu dostają prefiks i typ, znane z listy dostają typ."""
    views = await instance_models._supported_views(
        "https://litellm.example/v1", ["openrouter/*", "openrouter/openai/gpt-5", "other-model"]
    )

    by_name = {view.name: view.model_type for view in views}
    assert by_name == {
        "openrouter/openai/gpt-5": "chat",
        "openrouter/openai/text-embedding-3-large": "embedding",
        "openrouter/voyageai/rerank-3": "rerank",
        "other-model": None,
    }


async def test_plain_openrouter_host_uses_bare_ids(catalog: list[int]) -> None:
    """Bramka pod hostem OpenRouter: nazwy bez prefiksu, brakujące modele dołożone z katalogu."""
    views = await instance_models._supported_views("https://openrouter.ai/api/v1", ["openai/gpt-5"])

    assert [(view.name, view.model_type) for view in views] == [
        ("openai/gpt-5", "chat"),
        ("openai/text-embedding-3-large", "embedding"),
        ("voyageai/rerank-3", "rerank"),
    ]


async def test_other_gateway_is_left_untouched(catalog: list[int]) -> None:
    """Bramka inna niż OpenRouter: bez zapytania o katalog, typ nieznany."""
    views = await instance_models._supported_views("http://llm.local/v1", ["b", "a"])

    assert [(view.name, view.model_type) for view in views] == [("a", None), ("b", None)]
    assert catalog == []
