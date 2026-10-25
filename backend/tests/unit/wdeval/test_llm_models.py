"""Testy wdeval.llm_models — loader models.live.json i rodziny modeli (kontrakt C12)."""

import json
from pathlib import Path
from typing import Any

import pytest

from wdeval.dataset import DatasetError
from wdeval.llm_models import (
    FAKE_MODELS,
    FAMILIES_PATH,
    LIVE_MODELS_PATH,
    LiveModels,
    load_live_models,
    model_family,
)

LIVE_DIMENSION = 3072  # wymiar openai/text-embedding-3-large wpisany w pliku domyślnym (E1-10b)


def _write_models(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "models.live.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_repo_models_live_ma_wartosci_bramki() -> None:
    """Plik domyślny wskazuje modele bramki (czat/embedding) i sędziego z E1-10c."""
    assert LIVE_MODELS_PATH.exists()
    models = load_live_models()
    assert models.is_complete() is True
    assert models.chat == "openai/gpt-4.1-mini"
    assert models.embedding == "openai/text-embedding-3-large"
    assert models.dimension == LIVE_DIMENSION
    assert models.judge == "glm-5.3-flash"
    assert models.image2text == ""


def test_fake_models_complete() -> None:
    assert (
        LiveModels(
            chat="fake-chat",
            embedding="fake-embed-1024",
            dimension=1024,
            image2text="",
            judge="fake-chat",
            judge_mode="medium",
        )
        == FAKE_MODELS
    )
    assert FAKE_MODELS.is_complete() is True


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(DatasetError, match="brak pliku"):
        load_live_models(tmp_path / "brak.json")


def test_complete_models(tmp_path: Path) -> None:
    path = _write_models(
        tmp_path,
        {
            "chat": "gpt-5",
            "embedding": {"name": "embed-3", "dimension": 3072},
            "image2text": "vlm-model",
            "judge": {"name": "judge-x", "mode": "off"},
        },
    )
    models = load_live_models(path)
    assert models == LiveModels(
        chat="gpt-5",
        embedding="embed-3",
        dimension=3072,
        image2text="vlm-model",
        judge="judge-x",
        judge_mode="off",
    )
    assert models.is_complete() is True


def test_missing_judge_key(tmp_path: Path) -> None:
    path = _write_models(
        tmp_path,
        {"chat": "c", "embedding": {"name": "e", "dimension": 8}, "image2text": ""},
    )
    with pytest.raises(DatasetError, match="judge"):
        load_live_models(path)


def test_bad_dimension_type(tmp_path: Path) -> None:
    path = _write_models(
        tmp_path,
        {
            "chat": "c",
            "embedding": {"name": "e", "dimension": "1024"},
            "image2text": "",
            "judge": {"name": "j", "mode": "medium"},
        },
    )
    with pytest.raises(DatasetError, match=r"embedding\.dimension"):
        load_live_models(path)


def test_dimension_bool_rejected(tmp_path: Path) -> None:
    path = _write_models(
        tmp_path,
        {
            "chat": "c",
            "embedding": {"name": "e", "dimension": True},
            "image2text": "",
            "judge": {"name": "j", "mode": "medium"},
        },
    )
    with pytest.raises(DatasetError, match=r"embedding\.dimension"):
        load_live_models(path)


def test_embedding_not_object(tmp_path: Path) -> None:
    path = _write_models(
        tmp_path,
        {
            "chat": "c",
            "embedding": "embed",
            "image2text": "",
            "judge": {"name": "j", "mode": "m"},
        },
    )
    with pytest.raises(DatasetError, match="embedding: oczekiwano obiekt"):
        load_live_models(path)


def test_embedding_scalar_number(tmp_path: Path) -> None:
    """Skalar (liczba) w embedding → DatasetError z nazwą klucza, nie TypeError."""
    path = _write_models(
        tmp_path,
        {"chat": "", "embedding": 5, "image2text": "", "judge": {"name": "", "mode": "medium"}},
    )
    with pytest.raises(DatasetError, match="embedding"):
        load_live_models(path)


def test_judge_scalar_string(tmp_path: Path) -> None:
    """Skalar (tekst) w judge → DatasetError z nazwą klucza, nie TypeError."""
    path = _write_models(
        tmp_path,
        {"chat": "", "embedding": {"name": "e", "dimension": 8}, "image2text": "", "judge": "x"},
    )
    with pytest.raises(DatasetError, match="judge"):
        load_live_models(path)


def test_root_not_object(tmp_path: Path) -> None:
    """Korzeń JSON nie-obiekt (lista) → DatasetError, nie AttributeError/TypeError."""
    path = tmp_path / "models.live.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(DatasetError, match=r"models\.live\.json: oczekiwano obiektu"):
        load_live_models(path)


def test_chat_not_string(tmp_path: Path) -> None:
    path = _write_models(
        tmp_path,
        {
            "chat": 5,
            "embedding": {"name": "e", "dimension": 8},
            "image2text": "",
            "judge": {"name": "j", "mode": "m"},
        },
    )
    with pytest.raises(DatasetError, match="chat: oczekiwano str"):
        load_live_models(path)


def test_missing_embedding_name(tmp_path: Path) -> None:
    path = _write_models(
        tmp_path,
        {
            "chat": "c",
            "embedding": {"dimension": 8},
            "image2text": "",
            "judge": {"name": "j", "mode": "m"},
        },
    )
    with pytest.raises(DatasetError, match=r"embedding\.name: brak pola"):
        load_live_models(path)


def test_incomplete_when_dimension_zero(tmp_path: Path) -> None:
    path = _write_models(
        tmp_path,
        {
            "chat": "c",
            "embedding": {"name": "e", "dimension": 0},
            "image2text": "",
            "judge": {"name": "j", "mode": "medium"},
        },
    )
    assert load_live_models(path).is_complete() is False


def test_model_family_from_repo_families() -> None:
    assert FAMILIES_PATH.exists()
    assert model_family("glm-5.3-flash", fake=False) == "zhipu-glm"
    assert model_family("qwen3.8-27b-nvfp4", fake=False) == "qwen3"


def test_model_family_unknown_name() -> None:
    assert model_family("nieznany-model", fake=False) == "unknown"


def test_model_family_fake_short_circuit() -> None:
    assert model_family("cokolwiek", fake=True) == "fake"
