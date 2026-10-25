"""Ponowienia 429/5xx/timeout/connection w bramce LLM (kontrakt C2, WP E5-H8e).

Owijamy pojedyncze wywołanie SDK (embeddingi, wizja) w pętlę, która łapie
``openai.RateLimitError`` (429), ``openai.InternalServerError`` (5xx),
``openai.APITimeoutError`` i ``openai.APIConnectionError`` i ponawia z backoffem
wykładniczym z jitterem, nie krócej niż ``Retry-After`` z odpowiedzi. Po
``MAX_ATTEMPTS`` próbach podnosimy ``LLMRateLimited`` (429) albo ``LLMUnavailable``
(5xx/timeout/connection) — oba przejściowe, zadanie kończy mechanizm workera.
"""

import asyncio
import random
from collections.abc import Awaitable, Callable

import openai

from app.llm.errors import LLMRateLimited, LLMUnavailable
from app.llm.hooks import current_hooks

MAX_ATTEMPTS = 6  # łącznie prób (1 + 5 ponowień), kontrakt C4
BACKOFF_BASE_S = 1.0  # mnożone przez 2**(n-1) i jitter; n = numer ponowienia
BACKOFF_MAX_S = 30.0  # sufit pojedynczej przerwy (także dla Retry-After)
_JITTER_MIN = 0.5
_JITTER_MAX = 1.0
_HTTP_TOO_MANY_REQUESTS = 429
_CANCEL_CHUNK_S = 1.0  # backoff śpi kawałkami ≤ 1 s, między nimi check_cancel (C2)

# Błędy przejściowe ponawiane przez pętlę (kolejność sprawdzania w klasyfikacji, C2).
_RETRYABLE = (
    openai.RateLimitError,
    openai.InternalServerError,
    openai.APITimeoutError,
    openai.APIConnectionError,
)


def _retry_after_s(exc: openai.APIStatusError) -> float | None:
    """`Retry-After` z odpowiedzi (429/5xx, sekundy); brak/nieparsowalny → ``None`` (C2)."""
    raw = exc.response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return float(raw.strip())
    except ValueError:
        return None


def _label_status(
    exc: openai.APITimeoutError | openai.APIConnectionError | openai.APIStatusError,
) -> tuple[str, int | None]:
    """Etykieta logu/błędu i status: ``timeout``/``connection``/kod HTTP (C2).

    ``APITimeoutError`` sprawdzamy PRZED ``APIConnectionError`` (dziedziczy po nim).
    """
    if isinstance(exc, openai.APITimeoutError):
        return "timeout", None
    if isinstance(exc, openai.APIConnectionError):
        return "connection", None
    status = exc.status_code  # RateLimitError / InternalServerError
    return str(status), status


async def _sleep_backoff(
    delay: float,
    sleep: Callable[[float], Awaitable[None]],
    check_cancel: Callable[[], Awaitable[None]] | None,
) -> None:
    """Śpi ``delay`` kawałkami ≤ 1 s; przed każdym kawałkiem ``check_cancel`` (C2).

    Bez ``check_cancel`` (brak hooków) — jedno ``sleep(delay)``. ``TaskCancelled``
    z ``check_cancel`` propaguje i przerywa dalsze spanie.
    """
    if check_cancel is None:
        await sleep(delay)
        return
    remaining = delay
    while remaining > 0:
        await check_cancel()
        chunk = min(_CANCEL_CHUNK_S, remaining)
        await sleep(chunk)
        remaining -= chunk


async def call_with_retry[T](
    call: Callable[[], Awaitable[T]],
    *,
    what: str,
    model_name: str,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    rng: Callable[[float, float], float] = random.uniform,
) -> T:
    """Woła ``call`` ponawiając na 429/5xx/timeout/connection; ``what`` = "Embedding"/"Vision".

    Przerwa: ``min(BACKOFF_MAX_S, BASE * 2**(n-1)) * uniform(0.5, 1.0)``, nie krótsza niż
    ``Retry-After`` (429 i 5xx); ``sleep``/``rng`` wstrzykiwalne — testy nie czekają realnie.
    Przed każdym ponowieniem wpis w logu zadania (gdy hooki są): ``"{what} provider error
    {label} — retry {n}/{MAX_ATTEMPTS - 1} in {delay:.0f}s"``. Po ``MAX_ATTEMPTS`` próbach:
    429 → ``LLMRateLimited`` (C4), 5xx/timeout/connection → ``LLMUnavailable``. Inne błędy
    (w tym 4xx ≠ 429) propagują bez ponowień.
    """
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return await call()
        except _RETRYABLE as exc:
            label, status = _label_status(exc)
            if attempt >= MAX_ATTEMPTS:
                if isinstance(exc, openai.RateLimitError):
                    raise LLMRateLimited(
                        f"{what} provider rate limit (429)"
                        f" — reduce Parallel requests of model {model_name}",
                        details={"model": model_name, "status": _HTTP_TOO_MANY_REQUESTS},
                    ) from exc
                raise LLMUnavailable(
                    f"{what} provider unavailable ({label}) — check the model gateway",
                    details={"model": model_name, "status": status},
                ) from exc
            backoff = min(BACKOFF_MAX_S, BACKOFF_BASE_S * 2 ** (attempt - 1)) * rng(
                _JITTER_MIN, _JITTER_MAX
            )
            if isinstance(exc, openai.APIStatusError):
                retry_after = _retry_after_s(exc)
                if retry_after is not None:
                    backoff = max(backoff, retry_after)
            delay = min(backoff, BACKOFF_MAX_S)
            hooks = current_hooks()
            if hooks is not None:
                await hooks.log(
                    f"{what} provider error {label}"
                    f" — retry {attempt}/{MAX_ATTEMPTS - 1} in {delay:.0f}s"
                )
                check_cancel: Callable[[], Awaitable[None]] | None = hooks.check_cancel
            else:
                check_cancel = None
            await _sleep_backoff(delay, sleep, check_cancel)
    raise AssertionError("unreachable")  # pragma: no cover — pętla zawsze zwraca albo podnosi
