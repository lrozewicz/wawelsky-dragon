"""Konfiguracja modeli LLM biegu eval: loader models.live.json i rodziny modeli (C12).

Wartości ``models.live.json`` wpisuje E1-10b; puste pola = modele nieuzupełnione.
Moduł czysty: tylko format i wczytywanie, bez sieci.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wdeval.dataset import DatasetError

LIVE_MODELS_PATH: Path = Path(__file__).parent / "data" / "models.live.json"
FAMILIES_PATH: Path = Path(__file__).parent / "data" / "beta" / "models.json"


@dataclass(frozen=True)
class LiveModels:
    """Modele live dla biegu; puste pola = brak konfiguracji."""

    chat: str
    embedding: str
    dimension: int
    image2text: str  # "" = brak modelu wizji (ramię vision niedostępne)
    judge: str
    judge_mode: str

    def is_complete(self) -> bool:
        """Czy biegi live mają komplet: chat, embedding, judge niepuste i dimension > 0."""
        return bool(self.chat) and bool(self.embedding) and bool(self.judge) and self.dimension > 0


FAKE_MODELS: LiveModels = LiveModels(
    chat="fake-chat",
    embedding="fake-embed-1024",
    dimension=1024,
    image2text="",
    judge="fake-chat",
    judge_mode="medium",
)


def _str_at(container: dict[str, Any], key: str, path: str, problems: list[str]) -> str:
    if key not in container:
        problems.append(f"{path}: brak pola")
        return ""
    value = container[key]
    if not isinstance(value, str):
        problems.append(f"{path}: oczekiwano str")
        return ""
    return value


def _int_at(container: dict[str, Any], key: str, path: str, problems: list[str]) -> int:
    if key not in container:
        problems.append(f"{path}: brak pola")
        return 0
    value = container[key]
    if not isinstance(value, int) or isinstance(value, bool):
        problems.append(f"{path}: oczekiwano int")
        return 0
    return value


def _dict_at(
    container: dict[str, Any], key: str, path: str, problems: list[str]
) -> dict[str, Any] | None:
    value = container.get(key)
    if not isinstance(value, dict):
        problems.append(f"{path}: oczekiwano obiekt")
        return None
    return value


def _parse_live_models(data: dict[str, Any]) -> LiveModels:
    """Waliduje kształt models.live.json; problemy zbiera i rzuca jednym DatasetError."""
    problems: list[str] = []
    chat = _str_at(data, "chat", "chat", problems)
    image2text = _str_at(data, "image2text", "image2text", problems)

    embedding = _dict_at(data, "embedding", "embedding", problems)
    if embedding is None:
        embedding_name, dimension = "", 0
    else:
        embedding_name = _str_at(embedding, "name", "embedding.name", problems)
        dimension = _int_at(embedding, "dimension", "embedding.dimension", problems)

    judge = _dict_at(data, "judge", "judge", problems)
    if judge is None:
        judge_name, judge_mode = "", ""
    else:
        judge_name = _str_at(judge, "name", "judge.name", problems)
        judge_mode = _str_at(judge, "mode", "judge.mode", problems)

    if problems:
        raise DatasetError("; ".join(problems))
    return LiveModels(
        chat=chat,
        embedding=embedding_name,
        dimension=dimension,
        image2text=image2text,
        judge=judge_name,
        judge_mode=judge_mode,
    )


def load_live_models(path: Path = LIVE_MODELS_PATH) -> LiveModels:
    """Wczytuje modele live; brak pliku albo zły kształt → DatasetError z nazwą klucza."""
    if not path.exists():
        raise DatasetError(f"brak pliku: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise DatasetError("models.live.json: oczekiwano obiektu")
    return _parse_live_models(data)


def model_family(name: str, *, fake: bool, path: Path = FAMILIES_PATH) -> str:
    """Rodzina modelu do manifestu; fake → "fake", nieznana nazwa → "unknown"."""
    if fake:
        return "fake"
    with path.open("r", encoding="utf-8") as fh:
        families: dict[str, str] = json.load(fh)["families"]
    return families.get(name, "unknown")
