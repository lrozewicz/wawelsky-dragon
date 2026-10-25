"""Mapa modeli RAGFlow → WD z pliku YAML (kontrakt §2, WP E4-6a)."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class MappedModel:
    """Model docelowy w WD; ``model_type`` None = typ ze źródła."""

    name: str
    model_type: str | None
    dimension: int | None


_ALLOWED_FIELDS = frozenset({"name", "model_type", "dimension"})


class ModelMap:
    """Mapa ``llm_name@factory`` → :class:`MappedModel`."""

    def __init__(self, entries: dict[str, MappedModel]) -> None:
        self._entries = dict(entries)

    @classmethod
    def load(cls, path: Path | None) -> "ModelMap":
        """Wczytuje mapę z YAML; ``None`` → pusta mapa; niezgodny format → ValueError."""
        if path is None:
            return cls({})
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        if raw is None:
            return cls({})
        if not isinstance(raw, dict):
            raise ValueError("model-map: na najwyższym poziomie oczekiwano mapy")
        unknown_top = set(raw) - {"models"}
        if unknown_top:
            raise ValueError(
                f"model-map: nieznany klucz najwyższego poziomu: {sorted(unknown_top)}"
            )
        models = raw.get("models")
        if models is None:
            return cls({})
        if not isinstance(models, dict):
            raise ValueError("model-map: 'models' musi być mapą")
        return cls({str(key): cls._entry(key, value) for key, value in models.items()})

    @staticmethod
    def _entry(key: object, value: object) -> MappedModel:
        if not isinstance(value, dict):
            raise ValueError(f"model-map: wpis {key!r} musi być mapą")
        unknown = set(value) - _ALLOWED_FIELDS
        if unknown:
            raise ValueError(f"model-map: wpis {key!r}: nieznane pole {sorted(unknown)}")
        name = value.get("name")
        if not isinstance(name, str):
            raise ValueError(f"model-map: wpis {key!r}: wymagane pole 'name' (tekst)")
        model_type = value.get("model_type")
        if model_type is not None and not isinstance(model_type, str):
            raise ValueError(f"model-map: wpis {key!r}: 'model_type' musi być tekstem")
        dimension = value.get("dimension")
        if dimension is not None and not isinstance(dimension, int):
            raise ValueError(f"model-map: wpis {key!r}: 'dimension' musi być liczbą")
        return MappedModel(name=name, model_type=model_type, dimension=dimension)

    def get(self, source_key: str) -> MappedModel | None:
        """Wpis dla klucza ``llm_name@factory``; brak → None."""
        return self._entries.get(source_key)
