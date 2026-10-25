"""Konfiguracja sędziego wdeval na osobnym endpoincie (``WD_JUDGE_*``; kontrakt C1/C2).

Gdy w środowisku są WSZYSTKIE trzy zmienne ``WD_JUDGE_BASE_URL``, ``WD_JUDGE_API_KEY``
i ``WD_JUDGE_MODEL``, sędzia woła bezpośrednio ten endpoint (OpenAI-zgodne
``chat/completions``; docelowo OpenRouter) zamiast bramki WD — dzięki temu ocenia ten
sam model co beta, niezależnie od modeli wystawionych przez bramkę.

Moduł jest importowalny bez sieci: ``openai`` wchodzi dopiero w ``make_env_chat``, i to
wyłącznie wtedy, gdy wywołujący nie wstrzyknął klienta.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from wdeval.judge import ChatFn

JUDGE_ENV_REQUIRED: tuple[str, ...] = ("WD_JUDGE_BASE_URL", "WD_JUDGE_API_KEY", "WD_JUDGE_MODEL")
JUDGE_ENV_PROVIDER = "WD_JUDGE_PROVIDER"


class JudgeConfigError(ValueError):
    """Częściowa konfiguracja sędziego ``WD_JUDGE_*`` (1-2 z 3 wymaganych zmiennych).

    Komunikat zawiera wyłącznie NAZWY brakujących zmiennych — ani klucza, ani adresu
    endpointu (``run.py`` przepuszcza ten błąd do CLI, więc trafiłby na stderr).
    """


@dataclass(frozen=True)
class JudgeEndpoint:
    """Adres, klucz i model sędziego z env; ``base_url``/``api_key`` poza ``repr``."""

    base_url: str = field(repr=False)
    api_key: str = field(repr=False)
    model: str
    provider: str | None  # None, gdy WD_JUDGE_PROVIDER puste albo nieustawione


def judge_endpoint_from_env(env: Mapping[str, str]) -> JudgeEndpoint | None:
    """Endpoint sędziego z env: trzy ustawione zmienne → ``JudgeEndpoint``, zero → ``None``.

    Pusta wartość znaczy „nieustawiona" (tak samo jak brak klucza w mapie).
    Konfiguracja częściowa to błąd startu biegu, a nie ciche zejście na bramkę:
    bieg oceniłby wtedy odpowiedzi innym sędzią, niż deklaruje manifest.
    """
    values = {name: env.get(name, "") for name in JUDGE_ENV_REQUIRED}
    if not any(values.values()):
        return None
    missing = [name for name in JUDGE_ENV_REQUIRED if not values[name]]
    if missing:
        raise JudgeConfigError(
            f"częściowa konfiguracja sędziego WD_JUDGE_*; brakuje: {', '.join(missing)}"
        )
    return JudgeEndpoint(
        base_url=values["WD_JUDGE_BASE_URL"],
        api_key=values["WD_JUDGE_API_KEY"],
        model=values["WD_JUDGE_MODEL"],
        provider=env.get(JUDGE_ENV_PROVIDER) or None,
    )


def judge_env_extra_body(mode: str, provider: str | None) -> dict[str, object]:
    """``extra_body`` żądania do endpointu sędziego (OpenRouter).

    Poziom myślenia idzie ujednoliconym polem ``reasoning.effort`` — nie
    ``chat_template_kwargs`` (vLLM) ani ``reasoning_effort`` (bramka WD), bo te pola
    ten endpoint ignoruje albo odrzuca. Gdy wskazany dostawca, ``provider.order``
    ogranicza wybór do niego, a ``allow_fallbacks=False`` zabrania cichego zejścia na
    innego dostawcę (ten sam model u innego dostawcy odpowiada inaczej).
    """
    body: dict[str, object] = {"reasoning": {"effort": mode}}
    if provider:
        body["provider"] = {"order": [provider], "allow_fallbacks": False}
    return body


def make_env_chat(endpoint: JudgeEndpoint, mode: str, client: Any | None = None) -> ChatFn:
    """``ChatFn`` sędziego wołający ``endpoint`` (kontrakt C1).

    ``model_name`` przekazywany przez ``JudgeRunner`` (nazwa w kluczu cache'u i
    manifeście) != ``endpoint.model`` (nazwa na drucie) — na żądanie idzie wyłącznie
    ta druga. ``extra_body`` z ``JudgeRunner`` jest IGNOROWANY: zawiera pola bramki
    (``chat_template_kwargs``/``reasoning_effort``), których ten endpoint nie przyjmuje.
    """

    async def chat(
        model_name: str,
        messages: list[dict[str, str]],
        *,
        temperature: float | None,
        extra_body: Any,
    ) -> str:
        api = client
        if api is None:
            from openai import AsyncOpenAI  # noqa: PLC0415 — import dopiero w produkcji

            api = AsyncOpenAI(base_url=endpoint.base_url, api_key=endpoint.api_key)
        request: dict[str, Any] = {
            "model": endpoint.model,
            "messages": messages,
            "extra_body": judge_env_extra_body(mode, endpoint.provider),
        }
        if temperature is not None:
            request["temperature"] = temperature
        response = await api.chat.completions.create(**request)
        return response.choices[0].message.content or ""

    return chat
