"""Testy `call_with_retry` — 429/5xx/timeout/connection (E5-H8b C4, E5-H8e C2)."""

import re
from collections.abc import Awaitable, Callable
from contextvars import Token

import httpx2
import openai
import pytest

from app.llm.hooks import TaskLlmHooks, install_hooks, reset_hooks
from app.worker.errors import TaskCancelled

_REQ = httpx2.Request("POST", "http://fake/v1/embeddings")
TWO_SLEEPS = 2
THREE_ATTEMPTS = 3


def _rate_limit(retry_after: str | None = None) -> openai.RateLimitError:
    """`openai.RateLimitError` (429) z opcjonalnym nagłówkiem `Retry-After`."""
    headers = {} if retry_after is None else {"Retry-After": retry_after}
    response = httpx2.Response(429, request=_REQ, headers=headers, json={})
    return openai.RateLimitError("rate limited", response=response, body=None)


def _server_error(status: int = 502, retry_after: str | None = None) -> openai.InternalServerError:
    """`openai.InternalServerError` (5xx) z opcjonalnym nagłówkiem `Retry-After`."""
    headers = {} if retry_after is None else {"Retry-After": retry_after}
    response = httpx2.Response(status, request=_REQ, headers=headers, json={})
    return openai.InternalServerError(f"upstream error {status}", response=response, body=None)


async def _noop_cancel() -> None:
    return None


class _Hooks:
    """Hooki zadania z przechwyconym logiem i policzonymi anulowaniami (do testów)."""

    def __init__(self) -> None:
        self.logs: list[str] = []

    async def log(self, msg: str) -> None:
        self.logs.append(msg)


def _install(
    hooks: _Hooks, cancel: Callable[[], Awaitable[None]] | None = None
) -> Token[TaskLlmHooks | None]:
    """Instaluje hooki z logiem i `check_cancel`; zwraca token do resetu."""
    return install_hooks(
        TaskLlmHooks(log=hooks.log, check_cancel=cancel if cancel is not None else _noop_cancel)
    )


async def test_two_rate_limits_then_success_uses_three_attempts() -> None:
    """2 razy 429, potem OK → 3 próby i 2 wstrzyknięte przerwy (`sleep` wstrzyknięty)."""
    from app.llm.rate_limit import call_with_retry  # noqa: PLC0415

    calls = {"n": 0}
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async def call() -> str:
        calls["n"] += 1
        if calls["n"] < THREE_ATTEMPTS:
            raise _rate_limit()
        return "ok"

    result = await call_with_retry(
        call, what="Embedding", model_name="fake-embed-1024", sleep=sleep
    )
    assert result == "ok"
    assert calls["n"] == THREE_ATTEMPTS
    assert len(sleeps) == TWO_SLEEPS


async def test_retry_after_header_lower_bounds_sleep() -> None:
    """`Retry-After: 7` → przerwa ≥ 7 s (max z backoffem)."""
    from app.llm.rate_limit import call_with_retry  # noqa: PLC0415

    sleeps: list[float] = []
    calls = {"n": 0}

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async def call() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise _rate_limit("7")
        return "ok"

    await call_with_retry(
        call,
        what="Embedding",
        model_name="fake-embed-1024",
        sleep=sleep,
        rng=lambda _low, _high: 0.5,
    )
    assert sleeps and sleeps[0] >= 7  # noqa: PLR2004


async def test_unparseable_retry_after_is_ignored() -> None:
    """Nieczytelny `Retry-After` ignorowany — przerwa to sam backoff (kontrakt C4)."""
    from app.llm.rate_limit import call_with_retry  # noqa: PLC0415

    sleeps: list[float] = []
    calls = {"n": 0}

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async def call() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise _rate_limit("soon")
        return "ok"

    await call_with_retry(
        call,
        what="Embedding",
        model_name="fake-embed-1024",
        sleep=sleep,
        rng=lambda _low, _high: 0.5,
    )
    assert sleeps and sleeps[0] < 7  # noqa: PLR2004 — BASE(1.0) * jitter, bez Retry-After


def test_max_attempts_is_six_per_contract_c4() -> None:
    """`MAX_ATTEMPTS` = 6 = 1 próba + 5 ponowień (kontrakt C4) — jedyna asercja wobec stałej."""
    from app.llm.rate_limit import MAX_ATTEMPTS  # noqa: PLC0415

    assert MAX_ATTEMPTS == 6  # noqa: PLR2004


async def test_exhausted_attempts_raises_rate_limited_with_contract_message() -> None:
    """Po 6 próbach (C4) `LLMRateLimited` z komunikatem z C4 (bez sekretów)."""
    from app.llm.errors import LLMRateLimited  # noqa: PLC0415
    from app.llm.rate_limit import call_with_retry  # noqa: PLC0415

    calls = {"n": 0}
    expected = (
        "Embedding provider rate limit (429) — reduce Parallel requests of model fake-embed-1024"
    )

    async def sleep(_seconds: float) -> None:
        return None

    async def call() -> str:
        calls["n"] += 1
        raise _rate_limit()

    with pytest.raises(LLMRateLimited, match=re.escape(expected)):
        await call_with_retry(call, what="Embedding", model_name="fake-embed-1024", sleep=sleep)
    assert calls["n"] == 6  # noqa: PLR2004 — literał z kontraktu C4, nie importowana stała


async def test_non_rate_limit_error_is_not_retried() -> None:
    """Inny błąd niż 429/5xx/timeout/connection propaguje bez ponowień (400)."""
    from app.llm.rate_limit import call_with_retry  # noqa: PLC0415

    calls = {"n": 0}

    async def call() -> str:
        calls["n"] += 1
        raise openai.BadRequestError(
            "bad", response=httpx2.Response(400, request=_REQ, json={}), body=None
        )

    with pytest.raises(openai.BadRequestError):
        await call_with_retry(call, what="Embedding", model_name="fake-embed-1024")
    assert calls["n"] == 1


async def test_not_found_is_not_retried() -> None:
    """404 (np. model_not_found) nie jest ponawiane — jedna próba."""
    from app.llm.rate_limit import call_with_retry  # noqa: PLC0415

    calls = {"n": 0}

    async def call() -> str:
        calls["n"] += 1
        raise openai.NotFoundError(
            "no model", response=httpx2.Response(404, request=_REQ, json={}), body=None
        )

    with pytest.raises(openai.NotFoundError):
        await call_with_retry(call, what="Embedding", model_name="fake-embed-1024")
    assert calls["n"] == 1


async def test_502_once_then_success_logs_retry_with_label() -> None:
    """502 raz → sukces; log zadania `Embedding provider error 502 — retry 1/5 in 1s` (C2)."""
    from app.llm.rate_limit import call_with_retry  # noqa: PLC0415

    hooks = _Hooks()
    token = _install(hooks)
    calls = {"n": 0}
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async def call() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise _server_error(502)
        return "ok"

    try:
        result = await call_with_retry(
            call,
            what="Embedding",
            model_name="fake-embed-1024",
            sleep=sleep,
            rng=lambda _low, _high: 1.0,
        )
    finally:
        reset_hooks(token)
    assert result == "ok"
    assert calls["n"] == 2  # noqa: PLR2004
    assert hooks.logs == ["Embedding provider error 502 — retry 1/5 in 1s"]
    assert sleeps == [1.0]


async def test_exhausted_5xx_raises_unavailable_with_contract_message() -> None:
    """6x 502 (C4) → `LLMUnavailable` z komunikatem i `details` z C2 (bez stack trace)."""
    from app.llm.errors import LLMUnavailable  # noqa: PLC0415
    from app.llm.rate_limit import call_with_retry  # noqa: PLC0415

    calls = {"n": 0}
    expected = "Embedding provider unavailable (502) — check the model gateway"

    async def sleep(_seconds: float) -> None:
        return None

    async def call() -> str:
        calls["n"] += 1
        raise _server_error(502)

    with pytest.raises(LLMUnavailable) as exc_info:
        await call_with_retry(call, what="Embedding", model_name="fake-embed-1024", sleep=sleep)
    assert exc_info.value.message == expected
    assert exc_info.value.details == {"model": "fake-embed-1024", "status": 502}
    assert calls["n"] == 6  # noqa: PLR2004 — literał z kontraktu C4, nie importowana stała


async def test_exhausted_429_logs_retry_one_of_five_through_five_of_five() -> None:
    """6 prób i 5 ponowień: log dokładnie `retry 1/5` … `retry 5/5` z C4 (literały)."""
    from app.llm.errors import LLMRateLimited  # noqa: PLC0415
    from app.llm.rate_limit import call_with_retry  # noqa: PLC0415

    hooks = _Hooks()
    token = _install(hooks)
    calls = {"n": 0}

    async def sleep(_seconds: float) -> None:
        return None

    async def call() -> str:
        calls["n"] += 1
        raise _rate_limit()

    try:
        with pytest.raises(LLMRateLimited):
            await call_with_retry(
                call,
                what="Embedding",
                model_name="fake-embed-1024",
                sleep=sleep,
                rng=lambda _low, _high: 1.0,
            )
    finally:
        reset_hooks(token)
    assert calls["n"] == 6  # noqa: PLR2004 — 1 próba + 5 ponowień (C4)
    assert hooks.logs == [
        "Embedding provider error 429 — retry 1/5 in 1s",
        "Embedding provider error 429 — retry 2/5 in 2s",
        "Embedding provider error 429 — retry 3/5 in 4s",
        "Embedding provider error 429 — retry 4/5 in 8s",
        "Embedding provider error 429 — retry 5/5 in 16s",
    ]


async def test_timeout_label_is_timeout_not_connection() -> None:
    """`APITimeoutError` → etykieta `timeout` (a NIE `connection`, choć dziedziczy po nim)."""
    from app.llm.errors import LLMUnavailable  # noqa: PLC0415
    from app.llm.rate_limit import call_with_retry  # noqa: PLC0415

    async def sleep(_seconds: float) -> None:
        return None

    async def call() -> str:
        raise openai.APITimeoutError(request=_REQ)

    with pytest.raises(LLMUnavailable) as exc_info:
        await call_with_retry(call, what="Embedding", model_name="fake-embed-1024", sleep=sleep)
    assert exc_info.value.message == (
        "Embedding provider unavailable (timeout) — check the model gateway"
    )
    assert exc_info.value.details == {"model": "fake-embed-1024", "status": None}
    assert "connection" not in exc_info.value.message


async def test_connection_error_label() -> None:
    """`APIConnectionError` → etykieta `connection`, status `None` (C2)."""
    from app.llm.errors import LLMUnavailable  # noqa: PLC0415
    from app.llm.rate_limit import call_with_retry  # noqa: PLC0415

    async def sleep(_seconds: float) -> None:
        return None

    async def call() -> str:
        raise openai.APIConnectionError(request=_REQ)

    with pytest.raises(LLMUnavailable) as exc_info:
        await call_with_retry(call, what="Vision", model_name="fake-vision", sleep=sleep)
    assert exc_info.value.message == (
        "Vision provider unavailable (connection) — check the model gateway"
    )
    assert exc_info.value.details == {"model": "fake-vision", "status": None}


async def test_retry_after_header_lower_bounds_sleep_for_503() -> None:
    """`Retry-After: 7` przy 503 → przerwa ≥ 7 s (C2, 5xx respektuje nagłówek)."""
    from app.llm.rate_limit import call_with_retry  # noqa: PLC0415

    sleeps: list[float] = []
    calls = {"n": 0}

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async def call() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise _server_error(503, retry_after="7")
        return "ok"

    result = await call_with_retry(
        call,
        what="Embedding",
        model_name="fake-embed-1024",
        sleep=sleep,
        rng=lambda _low, _high: 0.5,
    )
    assert result == "ok"
    assert sleeps and sleeps[0] >= 7  # noqa: PLR2004


async def test_429_retry_logs_entry_with_429_label() -> None:
    """429 raz → sukces; log zadania z etykietą `429` (ta sama pętla, C2)."""
    from app.llm.rate_limit import call_with_retry  # noqa: PLC0415

    hooks = _Hooks()
    token = _install(hooks)
    calls = {"n": 0}

    async def sleep(_seconds: float) -> None:
        return None

    async def call() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise _rate_limit()
        return "ok"

    try:
        result = await call_with_retry(
            call,
            what="Embedding",
            model_name="fake-embed-1024",
            sleep=sleep,
            rng=lambda _low, _high: 1.0,
        )
    finally:
        reset_hooks(token)
    assert result == "ok"
    assert hooks.logs == ["Embedding provider error 429 — retry 1/5 in 1s"]


async def test_no_hooks_retries_without_log() -> None:
    """Brak hooków (None) → ponowienie działa, nic nie loguje (API czatu itd.)."""
    from app.llm.rate_limit import call_with_retry  # noqa: PLC0415

    calls = {"n": 0}

    async def sleep(_seconds: float) -> None:
        return None

    async def call() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise _server_error(503)
        return "ok"

    result = await call_with_retry(
        call, what="Embedding", model_name="fake-embed-1024", sleep=sleep
    )
    assert result == "ok"
    assert calls["n"] == 2  # noqa: PLR2004


async def test_cancel_during_backoff_stops_within_one_chunk() -> None:
    """Stop w backoffie 30 s: `check_cancel` rzuca po 1. kawałku, bez dalszych `sleep`."""
    from app.llm.rate_limit import call_with_retry  # noqa: PLC0415

    chunks: list[float] = []
    cancels = {"n": 0}

    async def sleep(seconds: float) -> None:
        chunks.append(seconds)

    async def check_cancel() -> None:
        cancels["n"] += 1
        if cancels["n"] >= 2:  # noqa: PLR2004 — po pierwszym kawałku przerwa zadanie
            raise TaskCancelled("stop")

    hooks = _Hooks()
    token = _install(hooks, cancel=check_cancel)

    async def call() -> str:
        raise _server_error(502)

    try:
        with pytest.raises(TaskCancelled):
            await call_with_retry(
                call,
                what="Embedding",
                model_name="fake-embed-1024",
                sleep=sleep,
                rng=lambda _low, _high: 30.0,  # backoff 30 s → 30 kawałków po ≤ 1 s
            )
    finally:
        reset_hooks(token)
    assert len(chunks) == 1  # < 2 kawałki, bez dalszego sleep
    assert chunks[0] <= 1.0  # kawałek ≤ 1 s
