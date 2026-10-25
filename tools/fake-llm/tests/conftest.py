"""Wspólne fixture: klient httpx i SDK openai 3.x na transporcie ASGI (C1 [R-1])."""

import httpx
import httpx2
import openai
import pytest

from fake_llm.app import create_app


@pytest.fixture
async def client():
    """httpx.AsyncClient na aplikacji w procesie, bez sieci."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()),
        base_url="http://fake-llm",
    ) as async_client:
        yield async_client


@pytest.fixture
async def sdk():
    """Prawdziwe SDK openai 3.x — wymaga httpx2 (nie httpx) jako http_client (C1 [R-1])."""
    http_client = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=create_app()))
    async_openai = openai.AsyncOpenAI(
        base_url="http://fake-llm/v1",
        api_key="x",
        max_retries=0,
        http_client=http_client,
    )
    yield async_openai
    await async_openai.close()
    await http_client.aclose()
