"""Walidacja ``parser_config.layout_recognize`` w ``DatasetsService`` (kontrakt E5-H6b C3).

Wydzielone z ``app/services/datasets.py`` (limit 400 linii pliku). Wartość nierozwiązywalna
jako model ``image2text`` daje wcześnie ``ValidationFailed`` (koperta 101) zamiast błędu
``PermanentError`` dopiero w pipeline ingestii.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core.errors import NotFound, ValidationFailed
from app.llm.registry import ModelRegistry

LAYOUT_PLAIN: tuple[Any, ...] = (None, "", "DeepDOC", "Plain Text")
MSG_LAYOUT_RECOGNIZE = (
    "layout_recognize '{value}' is not a known image2text model"
    " (allowed: DeepDOC, Plain Text or an image2text model name)"
)


async def validate_layout_recognize(
    models: ModelRegistry | None, parser_config: Mapping[str, Any] | None
) -> None:
    """``layout_recognize`` musi być DeepDOC/Plain Text/pusty albo istniejącym modelem (C3).

    ``None``/brak klucza w przychodzącym ``parser_config`` nic nie robi; wartość spoza zbioru
    rozwiązywalnego przez ``ModelRegistry.resolve(..., "image2text")`` → ``ValidationFailed``.
    """
    if not parser_config or "layout_recognize" not in parser_config:
        return
    value = parser_config["layout_recognize"]
    if value in LAYOUT_PLAIN:
        return
    if models is None:  # kontener bez start() — jak `_started` w ingestii
        raise RuntimeError("container not started")
    try:
        await models.resolve(value, "image2text")
    except NotFound as exc:
        raise ValidationFailed(MSG_LAYOUT_RECOGNIZE.format(value=value)) from exc
