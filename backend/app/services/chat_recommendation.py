"""Rekomendacje pytań pokrewnych (``chat_api.py:1202``; CONTRACT E4-4a §D7, zadanie T4).

Wydzielone z ``app.services.chats`` (limit 400 linii, wzór ``chat_validation``): prompt
i parsowanie wyniku 1:1 z upstreamem, model i parametry generacji z ``search_config``
wyszukiwarki (``resolve_llm_setting``, ``llm_service.py:44``). Bez ``search_id`` zachowanie
bez zmian — model domyślny tenanta i stałe ``_RELATED_DEFAULTS``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Final

from app.prompts import load_prompt

if TYPE_CHECKING:
    from app.core.container import Container

# Parametry generacji rekomendacji pytań (LLM_SETTING_DEFAULTS, llm_service.py:36).
_RELATED_DEFAULTS: Final[Mapping[str, float]] = {
    "temperature": 0.1,
    "top_p": 0.3,
    "frequency_penalty": 0.7,
    "presence_penalty": 0.4,
}
# Linia odpowiedzi modelu z numeracją pytania (chat_api.py:1231 dosłownie: ``^[0-9]\. ``).
_RELATED_LINE = re.compile(r"^[0-9]\. ")


def _related_questions(raw: str) -> list[str]:
    """Linie ``N. pytanie`` bez numeracji; pozostałe linie pomijane (chat_api.py:1231)."""
    return [_RELATED_LINE.sub("", line) for line in raw.split("\n") if _RELATED_LINE.match(line)]


def _related_generation_params(
    llm_setting: Mapping[str, Any] | None,
) -> tuple[float, float, dict[str, float]]:
    """Cztery parametry generacji jak upstream ``resolve_llm_setting`` (llm_service.py:44).

    Dla każdego klucza flaga ``{klucz}_enabled`` (domyślnie włączona) i obecność klucza
    w ``llm_setting`` decydują, czy bierzemy wartość zapisaną, czy stałą ``_RELATED_DEFAULTS``.
    """
    setting: Mapping[str, Any] = llm_setting if isinstance(llm_setting, Mapping) else {}
    resolved = {
        key: float(setting[key])
        for key in _RELATED_DEFAULTS
        if setting.get(f"{key}_enabled", True) and key in setting
    }
    values = {**_RELATED_DEFAULTS, **resolved}
    extra = {
        "frequency_penalty": values["frequency_penalty"],
        "presence_penalty": values["presence_penalty"],
    }
    return values["temperature"], values["top_p"], extra


async def recommend_questions(
    container: Container,
    question: str,
    *,
    model_id: str | None = None,
    llm_setting: Mapping[str, Any] | None = None,
) -> list[str]:
    """Pytania pokrewne z modelu czatu tenanta (chat_api.py:1202).

    ``model_id``/``llm_setting`` pochodzą z ``search_config`` wyszukiwarki (T4); brak
    ``model_id`` → model domyślny, brak ``llm_setting`` → stałe ``_RELATED_DEFAULTS``.
    """
    llm = container.llm
    models = container.models
    if llm is None or models is None:
        raise RuntimeError("container not started")
    model = await models.resolve(model_id if model_id else None, "chat")
    temperature, top_p, extra = _related_generation_params(llm_setting)
    result = await llm.chat(
        model,
        [
            {"role": "system", "content": load_prompt("related_question")},
            {"role": "user", "content": f"\nKeywords: {question}\nRelated search terms:\n    "},
        ],
        temperature=temperature,
        top_p=top_p,
        extra=extra,
    )
    return _related_questions(result.text)
