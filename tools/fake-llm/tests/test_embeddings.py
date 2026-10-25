"""Testy embeddingów: HTTP `POST /v1/embeddings` i własności funkcji embed (K10 §3, C4)."""

import base64
import hashlib
import math
import struct
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from fake_llm.embeddings import embed

FAKE_LLM_DIR = Path(__file__).resolve().parents[1]
HTTP_OK = 200
HTTP_BAD_REQUEST = 400
HTTP_NOT_FOUND = 404
DIM_3072 = 3072
DIM_1024 = 1024
DIM_256 = 256
SLICE = 10
TOL = 1e-6
TOKENS_UMOWA_NAJMU = 2
TOKENS_ABC = 3
MODEL_3072 = "fake-embed-3072"
MODEL_1024 = "fake-embed-1024"
UNKNOWN_MODEL = "nope"
CHAT_MODEL = "fake-chat"
TEXT_SHARED = "umowa najmu lokalu"

# kod podprocesu: skrót sha256 wektora — determinizm między procesami (wymaganie 7 z briefu)
_HASH_SUBPROCESS_CODE = (
    "import hashlib\n"
    "import struct\n"
    "from fake_llm.embeddings import embed\n"
    f"vector = embed('{MODEL_3072}', '{TEXT_SHARED}')\n"
    f"print(hashlib.sha256(struct.pack('<{DIM_3072}d', *vector)).hexdigest())\n"
)


def _norm(vector: list[float]) -> float:
    """Norma L2."""
    return math.sqrt(sum(x * x for x in vector))


def _cos(a: list[float], b: list[float]) -> float:
    """Iloczyn skalarny znormalizowanych wektorów (= cosinus)."""
    return sum(x * y for x, y in zip(a, b, strict=True))


async def test_embeddings_single_string(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/embeddings", json={"model": MODEL_3072, "input": "umowa najmu"}
    )
    assert response.status_code == HTTP_OK
    body = response.json()
    assert body["object"] == "list"
    assert len(body["data"]) == 1
    assert body["data"][0]["object"] == "embedding"
    assert body["data"][0]["index"] == 0
    assert len(body["data"][0]["embedding"]) == DIM_3072
    assert body["model"] == MODEL_3072
    assert body["usage"] == {
        "prompt_tokens": TOKENS_UMOWA_NAJMU,
        "total_tokens": TOKENS_UMOWA_NAJMU,
    }


async def test_embeddings_list_input(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/embeddings",
        json={"model": MODEL_1024, "input": ["a b", "", "c"]},
    )
    assert response.status_code == HTTP_OK
    body = response.json()
    assert len(body["data"]) == TOKENS_ABC
    for index, item in enumerate(body["data"]):
        assert item["index"] == index
        assert len(item["embedding"]) == DIM_1024
    assert body["usage"]["prompt_tokens"] == TOKENS_ABC


def test_embed_is_deterministic() -> None:
    assert embed(MODEL_3072, TEXT_SHARED) == embed(MODEL_3072, TEXT_SHARED)


def test_determinism_across_processes() -> None:
    expected = hashlib.sha256(
        struct.pack(f"<{DIM_3072}d", *embed(MODEL_3072, TEXT_SHARED))
    ).hexdigest()
    process = subprocess.run(  # noqa: S603 - stałe argumenty, bez shell
        [sys.executable, "-c", _HASH_SUBPROCESS_CODE],
        capture_output=True,
        text=True,
        check=True,
        cwd=FAKE_LLM_DIR,
    )
    assert process.stdout.strip() == expected


def test_embed_case_insensitive() -> None:
    assert embed(MODEL_3072, "Umowa NAJMU") == embed(MODEL_3072, "umowa najmu")


def test_no_tokens_equal_and_unit_norm() -> None:
    empty = embed(MODEL_3072, "")
    punctuation = embed(MODEL_3072, "!!!")
    assert empty == punctuation
    assert abs(_norm(empty) - 1.0) < TOL


def test_different_models_differ() -> None:
    assert embed(MODEL_1024, "a")[:SLICE] != embed(MODEL_3072, "a")[:SLICE]


def test_similarity_ordering() -> None:
    base = embed(MODEL_3072, TEXT_SHARED)
    related = embed(MODEL_3072, "najmu lokalu")
    unrelated = embed(MODEL_3072, "prognoza pogody")
    assert _cos(base, related) > _cos(base, unrelated)


@pytest.mark.parametrize("model", [MODEL_3072, MODEL_1024])
@pytest.mark.parametrize("text", ["umowa najmu", "Zażółć GĘŚLĄ jaźń", ""])
def test_norm_is_one(model: str, text: str) -> None:
    assert abs(_norm(embed(model, text)) - 1.0) < TOL


async def test_dimensions_truncates_and_renormalizes(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/embeddings",
        json={"model": MODEL_3072, "input": "a", "dimensions": DIM_256},
    )
    assert response.status_code == HTTP_OK
    vector = response.json()["data"][0]["embedding"]
    assert len(vector) == DIM_256
    assert abs(_norm(vector) - 1.0) < TOL
    assert vector == embed(MODEL_3072, "a", DIM_256)


@pytest.mark.parametrize("dimensions", [0, DIM_3072 + 1])
async def test_dimensions_out_of_range(client: httpx.AsyncClient, dimensions: int) -> None:
    response = await client.post(
        "/v1/embeddings",
        json={"model": MODEL_3072, "input": "a", "dimensions": dimensions},
    )
    assert response.status_code == HTTP_BAD_REQUEST
    error = response.json()["error"]
    assert error["param"] == "dimensions"
    assert error["type"] == "invalid_request_error"


async def test_unknown_model_not_found(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/embeddings",
        json={"model": UNKNOWN_MODEL, "input": "a"},
    )
    assert response.status_code == HTTP_NOT_FOUND
    assert response.json() == {
        "error": {
            "message": f"The model '{UNKNOWN_MODEL}' does not exist",
            "type": "invalid_request_error",
            "param": "model",
            "code": "model_not_found",
        }
    }


async def test_chat_model_rejected_in_embeddings(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/embeddings",
        json={"model": CHAT_MODEL, "input": "a"},
    )
    assert response.status_code == HTTP_NOT_FOUND
    assert response.json()["error"]["code"] == "model_not_found"


async def test_base64_encoding_format(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/embeddings",
        json={"model": MODEL_1024, "input": "a", "encoding_format": "base64"},
    )
    assert response.status_code == HTTP_OK
    raw = response.json()["data"][0]["embedding"]
    assert isinstance(raw, str)
    decoded = list(struct.unpack(f"<{DIM_1024}f", base64.b64decode(raw)))
    expected = embed(MODEL_1024, "a")
    assert all(
        abs(value - reference) < TOL for value, reference in zip(decoded, expected, strict=True)
    )
