"""Testy /health, /v1/models i importu aplikacji (K10 §1-§2)."""

import subprocess
import sys
from pathlib import Path

import httpx
from fastapi import FastAPI

from fake_llm.app import create_app

FAKE_LLM_DIR = Path(__file__).resolve().parents[1]
HTTP_OK = 200

EXPECTED_MODEL_IDS = [
    "fake-chat",
    "fake-chat-think",
    "fake-chat-strict",
    "fake-embed-3072",
    "fake-embed-1024",
    "fake-rerank",
    "fake-vision",
    "fake-ocr",
]


async def test_health_returns_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == HTTP_OK
    assert response.json() == {"status": "ok"}


async def test_models_list(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/models")
    assert response.status_code == HTTP_OK
    body = response.json()
    assert body["object"] == "list"
    assert [model["id"] for model in body["data"]] == EXPECTED_MODEL_IDS
    for model in body["data"]:
        assert model["object"] == "model"
        assert model["created"] == 0
        assert model["owned_by"] == "fake-llm"


async def test_models_list_ignores_authorization(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/v1/models",
        headers={"Authorization": "Bearer cokolwiek"},
    )
    assert response.status_code == HTTP_OK


def test_create_app_returns_fastapi() -> None:
    assert isinstance(create_app(), FastAPI)


def test_import_with_empty_environ() -> None:
    process = subprocess.run(
        [sys.executable, "-c", "from fake_llm.app import create_app"],
        cwd=FAKE_LLM_DIR,
        env={},
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr
