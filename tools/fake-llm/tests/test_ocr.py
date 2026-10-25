"""Testy modelu `fake-ocr` (K10 poprawka 2026-10-04b) — prompt OTSL, fixture `ocr.json`."""

import base64
import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from fake_llm import answers

HTTP_OK = 200
OCR_MODEL = "fake-ocr"
OTSL_PROMPT = "Tables should be expressed in OTSL format, and formulas in LATEX."
WRONG_PROMPT = "Przepisz treść strony z obrazu do kodu HTML."
MISMATCH = "PROMPT-MISMATCH"
KNOWN_BYTES = b"znany obraz OCR"
KNOWN_SHA8 = hashlib.sha256(KNOWN_BYTES).hexdigest()[:8]
UNKNOWN_BYTES = b"abc"
UNKNOWN_SHA8 = hashlib.sha256(UNKNOWN_BYTES).hexdigest()[:8]
OTSL_VALUE = "TABL. 1\n\n<fcel>SPEC<fcel>2022<fcel>2023<nl>"


def _data_url(bytes_: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(bytes_).decode("ascii")


def _image_part(url: str) -> dict[str, Any]:
    return {"type": "image_url", "image_url": {"url": url}}


def _text_part(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def _body(model: str, content: str | list[dict[str, Any]]) -> dict[str, Any]:
    return {"model": model, "messages": [{"role": "user", "content": content}]}


@pytest.fixture
def ocr_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Podmienia `fixtures/ocr.json` na plik tymczasowy ze znanym obrazem i czyści cache."""
    path = tmp_path / "ocr.json"
    path.write_text(json.dumps({KNOWN_SHA8: OTSL_VALUE}), encoding="utf-8")
    monkeypatch.setattr(answers, "_OCR_FIXTURES_PATH", path)
    answers._ocr_fixtures.cache_clear()
    yield
    monkeypatch.undo()
    answers._ocr_fixtures.cache_clear()


async def test_models_list_contains_fake_ocr(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/models")
    assert response.status_code == HTTP_OK
    assert OCR_MODEL in [model["id"] for model in response.json()["data"]]


async def test_known_image_returns_fixture(client: httpx.AsyncClient, ocr_fixture: None) -> None:
    content = [_text_part(OTSL_PROMPT), _image_part(_data_url(KNOWN_BYTES))]
    response = await client.post("/v1/chat/completions", json=_body(OCR_MODEL, content))
    assert response.status_code == HTTP_OK
    assert response.json()["choices"][0]["message"]["content"] == OTSL_VALUE


async def test_wrong_prompt_returns_mismatch(client: httpx.AsyncClient, ocr_fixture: None) -> None:
    content = [_text_part(WRONG_PROMPT), _image_part(_data_url(KNOWN_BYTES))]
    response = await client.post("/v1/chat/completions", json=_body(OCR_MODEL, content))
    assert response.status_code == HTTP_OK
    assert response.json()["choices"][0]["message"]["content"] == MISMATCH


async def test_unknown_image_returns_ocr_sha(client: httpx.AsyncClient, ocr_fixture: None) -> None:
    content = [_text_part(OTSL_PROMPT), _image_part(_data_url(UNKNOWN_BYTES))]
    response = await client.post("/v1/chat/completions", json=_body(OCR_MODEL, content))
    assert response.status_code == HTTP_OK
    assert response.json()["choices"][0]["message"]["content"] == f"OCR:{UNKNOWN_SHA8}"


async def test_image_before_text_same_result(client: httpx.AsyncClient, ocr_fixture: None) -> None:
    content = [_image_part(_data_url(KNOWN_BYTES)), _text_part(OTSL_PROMPT)]
    response = await client.post("/v1/chat/completions", json=_body(OCR_MODEL, content))
    assert response.status_code == HTTP_OK
    assert response.json()["choices"][0]["message"]["content"] == OTSL_VALUE


async def test_non_data_url_falls_back_to_test_answer(
    client: httpx.AsyncClient, ocr_fixture: None
) -> None:
    content = [_text_part(OTSL_PROMPT), _image_part("https://example.com/obraz.png")]
    response = await client.post("/v1/chat/completions", json=_body(OCR_MODEL, content))
    assert response.status_code == HTTP_OK
    assert response.json()["choices"][0]["message"]["content"] == (
        "Odpowiedź testowa: Tables should be expressed in OTSL format, and formulas in LATEX."
    )


async def test_plain_text_uses_base_answer(client: httpx.AsyncClient, ocr_fixture: None) -> None:
    response = await client.post("/v1/chat/completions", json=_body(OCR_MODEL, "pytanie"))
    assert response.status_code == HTTP_OK
    assert response.json()["choices"][0]["message"]["content"] == "Odpowiedź testowa: pytanie"


def test_ocr_fixtures_missing_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(answers, "_OCR_FIXTURES_PATH", Path("/nie/ma/ocr.json"))
    answers._ocr_fixtures.cache_clear()
    assert answers._ocr_fixtures() == {}
    monkeypatch.undo()
    answers._ocr_fixtures.cache_clear()
