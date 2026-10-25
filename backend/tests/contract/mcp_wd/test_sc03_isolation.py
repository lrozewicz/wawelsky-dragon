"""SC-E6-2-03 (K17 §5): izolacja użytkowników — klucz B nie widzi zasobów A.

Dwóch użytkowników z różnymi datasetami: A (dataset ``wd_sc_e6_2_ds_a`` ze stosu, konto admina
z resetu) i B (``wd_sc_e6_2_ds_b`` zakładany w tym teście). Klucz B nie może zobaczyć niczego A:
listy datasetów, opisu narzędzia ``ragflow_retrieval`` ani fragmentów z ``ragflow_retrieval``
bez ``dataset_ids``. Dataset B jest sprzątany po teście, żeby nie zanieczyszczać wspólnego
stosu (konto admina widzi wszystkie datasety — jego listy używa test złota).
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest

from tests.contract.mcp_wd.session_helpers import base_url_of, mcp_session, text_of
from tests.contract.mcp_wd.support import (
    B_DATASET_NAME,
    B_DOCUMENT_NAME,
    B_DOCUMENT_TEXT,
    B_MARKER,
    B_QUESTION,
    DATASET_NAME,
    EXPECTED_MARKER,
    HTTP_TIMEOUT_S,
    McpStack,
    ingest_dataset,
)

pytestmark = [pytest.mark.contract]


@pytest.fixture
def b_account(mcp_stack: McpStack) -> Iterator[tuple[str, str]]:
    """Konto B z własnym datasetem; po teście dataset B jest usuwany (izolacja stosu)."""
    b_key = mcp_stack.register_user("wdsc3b")
    b_dataset_id = ingest_dataset(
        mcp_stack.api_base,
        b_key,
        dataset_name=B_DATASET_NAME,
        document_name=B_DOCUMENT_NAME,
        text=B_DOCUMENT_TEXT,
    )
    try:
        yield b_key, b_dataset_id
    finally:
        with httpx.Client(
            base_url=mcp_stack.api_base,
            headers={"Authorization": f"Bearer {b_key}"},
            timeout=HTTP_TIMEOUT_S,
        ) as client:
            deleted = client.request("DELETE", "/datasets", json={"ids": [b_dataset_id]})
            deleted.raise_for_status()


def _retrieval_description(tools: object) -> str:
    """Opis narzędzia ``ragflow_retrieval`` z wyniku ``list_tools`` (dynamiczna lista datasetów)."""
    for tool in getattr(tools, "tools", []):
        if tool.name == "ragflow_retrieval":
            return str(tool.description)
    raise AssertionError("brak narzędzia ragflow_retrieval")


async def test_sc_e6_2_03_user_isolation(mcp_stack: McpStack, b_account: tuple[str, str]) -> None:
    """SC-E6-2-03: klucz B widzi wyłącznie zasoby B — nigdzie nie pojawia się dataset A."""
    b_key, b_dataset_id = b_account
    assert b_dataset_id != mcp_stack.dataset_id

    headers = {"Authorization": f"Bearer {b_key}"}
    async with mcp_session(base_url_of(mcp_stack.mcp_url), "streamable_http", headers) as session:
        await session.initialize()

        datasets_text = text_of(await session.call_tool("ragflow_list_datasets", {}))
        assert B_DATASET_NAME in datasets_text, datasets_text
        assert b_dataset_id in datasets_text, datasets_text
        assert DATASET_NAME not in datasets_text, datasets_text
        assert mcp_stack.dataset_id not in datasets_text, datasets_text

        description = _retrieval_description(await session.list_tools())
        assert B_DATASET_NAME in description, description
        assert DATASET_NAME not in description, description
        assert mcp_stack.dataset_id not in description, description

        retrieved = await session.call_tool("ragflow_retrieval", {"question": B_QUESTION})
        assert retrieved.isError is False
        retrieved_text = text_of(retrieved)
        assert B_MARKER in retrieved_text, retrieved_text
        assert EXPECTED_MARKER not in retrieved_text, retrieved_text
        assert mcp_stack.dataset_id not in retrieved_text, retrieved_text
