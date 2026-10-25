"""Ponowienie chat-completions bez parametrów odrzuconych przez model (kontrakt §3).

Rozpoznawanie komunikatów LiteLLM ``UnsupportedParamsError``, jednokrotne
ponowienie żądania bez wskazanych kluczy oraz maskowanie sekretów w treści
błędów 400. Moduł importuje tylko stdlib i SDK ``openai``.
"""

import logging
import re
from collections.abc import Awaitable, Callable

import openai

logger = logging.getLogger("app.llm")

RETRY_PARAMS: tuple[str, ...] = ("presence_penalty", "frequency_penalty", "temperature", "top_p")

_MAX_ATTEMPTS = 2
_PHRASES = ("UnsupportedParamsError", "does not support parameters")
_PARAMS_LIST_RE = re.compile(r"parameters:\s*\[([^\]]*)\]")
_PARAM_KEY_RE = re.compile(r"['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]")
_HEADER_LINE_RE = re.compile(r"(?im)^\s*(?:authorization|x-api-key|cookie|set-cookie)\s*:[^\n]*")
_URL_USERINFO_RE = re.compile(r"://[^/\s:@]+:[^/\s@]+@")
_URL_QUERY_RE = re.compile(r"(?i)[?&](?:key|token|api_key|apikey)=[^&\s]*")
_SECRETS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"sk-[A-Za-z0-9_-]{8,}"), "sk-***"),
    (re.compile(r"Bearer\s+\S+"), "Bearer ***"),
    (re.compile(r"(?i)(api[_-]?key|token|key)=\S+"), r"\1=***"),
)


def unsupported_params(message: str) -> list[str] | None:
    """Parametry do pominięcia z komunikatu LiteLLM; ``None`` gdy to nie ten błąd.

    Lista po ``parameters:`` czytana z apostrofów/cudzysłowów; klucze spoza
    ``RETRY_PARAMS`` odrzucane. Nieczytelna/pusta lista, a także brak kluczy po
    odrzuceniu → wszystkie cztery.
    """
    if not any(phrase in message for phrase in _PHRASES):
        return None
    match = _PARAMS_LIST_RE.search(message)
    keys: list[str] = []
    if match is not None:
        for key in _PARAM_KEY_RE.findall(match.group(1)):
            if key in RETRY_PARAMS and key not in keys:
                keys.append(key)
    return keys or list(RETRY_PARAMS)


def safe_message(raw: str, limit: int = 300) -> str:
    """Czytelny komunikat błędu 400: bez nagłówków i sekretów, białe znaki zwinięte."""
    text = _HEADER_LINE_RE.sub("", raw)
    for pattern, replacement in _SECRETS:
        text = pattern.sub(replacement, text)
    text = _URL_USERINFO_RE.sub("://", text)
    text = _URL_QUERY_RE.sub("", text)
    return " ".join(text.split())[:limit]


def error_text(exc: openai.APIStatusError) -> str:
    """Tekst błędu SDK: ``body.error.message``, ``body.message``, body albo ``exc.message``."""
    body = exc.body
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str):
                return message
        direct = body.get("message")
        if isinstance(direct, str):
            return direct
    if isinstance(body, str) and body.strip():
        return body
    return exc.message


async def retry_without_unsupported[T](
    create: Callable[[], Awaitable[T]],
    *,
    model: str,
    dropped: dict[str, frozenset[str]],
) -> T:
    """Woła ``create``; raz ponawia bez parametrów, które model odrzucił (400).

    Odrzucone klucze dopisywane są do ``dropped[model]`` (suma zbiorów), więc
    kolejne wywołanie tego modelu od razu ich nie wysyła.
    """
    for attempt in range(_MAX_ATTEMPTS):
        try:
            return await create()
        except openai.BadRequestError as exc:
            params = unsupported_params(error_text(exc))
            if attempt or params is None:
                raise
            known = dropped.get(model, frozenset())
            added = sorted(set(params) - known)
            if not added:
                raise
            dropped[model] = known | set(params)
            logger.warning(
                "model rejected params; retrying without",
                extra={"model": model, "params": added},
            )
    raise AssertionError("unreachable")
