"""Testy przez prawdziwe SDK openai 3.19.2 na httpx2 (C1 [R-1], K10 §2-§3)."""

import openai
import pytest

from fake_llm.embeddings import embed
from fake_llm.models import MODEL_IDS

DIM_1024 = 1024
TOL = 1e-6
EXPECTED_INPUTS = 2
TOKENS_TWO_INPUTS = 3
MODEL_1024 = "fake-embed-1024"
UNKNOWN_MODEL = "nope"


async def test_sdk_models_list(sdk: openai.AsyncOpenAI) -> None:
    page = await sdk.models.list()
    assert [model.id for model in page.data] == list(MODEL_IDS)


async def test_sdk_embeddings_list_input(sdk: openai.AsyncOpenAI) -> None:
    result = await sdk.embeddings.create(model=MODEL_1024, input=["umowa najmu", "prognoza"])
    assert len(result.data) == EXPECTED_INPUTS
    assert len(result.data[0].embedding) == DIM_1024
    expected = embed(MODEL_1024, "umowa najmu")
    assert all(
        abs(value - reference) < TOL
        for value, reference in zip(result.data[0].embedding, expected, strict=True)
    )
    assert result.usage.prompt_tokens == TOKENS_TWO_INPUTS


async def test_sdk_embeddings_float_exact(sdk: openai.AsyncOpenAI) -> None:
    result = await sdk.embeddings.create(model=MODEL_1024, input="a", encoding_format="float")
    assert result.data[0].embedding == embed(MODEL_1024, "a")


async def test_sdk_unknown_model_not_found(sdk: openai.AsyncOpenAI) -> None:
    with pytest.raises(openai.NotFoundError):
        await sdk.embeddings.create(model=UNKNOWN_MODEL, input="a")
