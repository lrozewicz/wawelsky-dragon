"""Test VlmRecognizer przeciw fake-llm po sieci (K10; uruchamia verify.sh)."""

import hashlib
import os
from io import BytesIO

import pytest
from PIL import Image
from pydantic import SecretStr

from app.core.config import Settings
from app.llm.openai_gateway import OpenAIGateway
from app.llm.types import ModelRef
from app.parsing.recognizers import VlmRecognizer, complete_pages
from app.parsing.types import ConvertedDocument, PendingPage

pytestmark = [
    pytest.mark.fakellm,
    pytest.mark.skipif(
        not os.environ.get("WD_LLM_BASE_URL"),
        reason="fakellm: brak WD_LLM_BASE_URL (eksportuje verify.sh)",
    ),
]


async def test_complete_pages_vision_fakellm() -> None:
    gateway = OpenAIGateway(
        Settings(
            env="test",
            llm_base_url=os.environ["WD_LLM_BASE_URL"],
            llm_api_key=SecretStr("fake"),
            llm_max_retries=0,
        )
    )
    try:
        vlm = VlmRecognizer(gateway, ModelRef(None, "fake-vision", "image2text"))
        buffer = BytesIO()
        Image.new("RGB", (8, 8), (0, 128, 255)).save(buffer, format="PNG")
        png = buffer.getvalue()
        doc = ConvertedDocument(
            '<section data-page="1"></section>',
            1,
            [PendingPage(1, "vision", png, "image")],
            {},
            [],
            {"chars": 0, "pages_text": 0, "pages_ocr": 0, "pages_vision": 0},
        )
        result = await complete_pages(doc, ocr=None, vision=vlm)
    finally:
        await gateway.aclose()
    # odpowiedź fake-vision (K10): <p>OCR:<sha8></p> → trafia do sekcji strony
    assert (
        result.html
        == '<section data-page="1"><p>OCR:'
        + (hashlib.sha256(png).hexdigest()[:8])
        + "</p></section>"
    )
    assert result.stats["pages_vision"] == 1
    assert result.pending_pages == []
