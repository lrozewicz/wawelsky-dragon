"""Liczniki żądań, opóźnienia `fake-ocr`/embeddingów, wstrzykiwanie 429/5xx i endpointy
administracyjne `/v1/fake/*`.

Zawiera `GET /v1/fake/stats` oraz `POST /v1/fake/stats/reset` (K10, poprawka 2026-10-04),
a od poprawki 2026-10-10 (E5-H8a) stan i endpointy opóźnienia `fake-ocr`:
`GET`/`POST /v1/fake/ocr-delay`.
Poprawka 2026-10-10b (E5-H8b) dodaje: opóźnienie embeddingów `GET`/`POST /v1/fake/embed-delay`,
wstrzykiwanie 429 `GET`/`POST /v1/fake/embed-429`, licznik odrzuconych 429 oraz liczniki maks.
jednoczesnych żądań per model (C6).
Poprawka 2026-10-11 (E5-H8e) dodaje: wstrzykiwanie błędów 5xx dla tras `embeddings` i `chat`
(`GET`/`POST /v1/fake/upstream-error`) i licznik wstrzyknięć `upstream_errors`.
Poprawka E6-3f T6 (C8) dodaje: wstrzykiwanie ZAWĘŻONE do modelu — ciała `POST /v1/fake/*`
przyjmują opcjonalne pole `model` (pełna nazwa z aliasem `~<scope>`); taka reguła obowiązuje
tylko żądania tego modelu, jest trzymana osobno od stanu globalnego, a wartość zerowa ją usuwa.
`GET` zwraca klucz `scoped` (tylko gdy są reguły zawężone); `stats/reset` ich nie usuwa.
"""

import os
from collections import Counter
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from fake_llm import tool_calls
from fake_llm.errors import OpenAIError

# Żądania `POST /v1/chat/completions` na model (liczone także te zakończone 400).
CHAT_REQUESTS: Counter[str] = Counter()

# Żądania `POST /v1/embeddings` łącznie (liczone także te odrzucone przez 429), C6.
EMBED_REQUESTS: int = 0

# Liczba żądań embeddingu odrzuconych przez wstrzykiwany 429 (C6).
EMBED_REJECTED_429: int = 0

# Maks. liczba jednocześnie obsługiwanych żądań per model (czat i embeddingi), C6.
MAX_CONCURRENT: Counter[str] = Counter()

# Liczniki „w locie” per model — stan przejściowy dla wyliczenia maksimum (C6).
_INFLIGHT: Counter[str] = Counter()

# Opóźnienie startowe `fake-ocr` w milisekundach (C6); inicjowane z env przy imporcie.
OCR_DELAY_MS: int = int(os.environ.get("FAKE_OCR_DELAY_MS", "0"))

# Opóźnienie odpowiedzi `POST /v1/embeddings` w milisekundach (C6); inicjowane z env przy imporcie.
EMBED_DELAY_MS: int = int(os.environ.get("FAKE_EMBED_DELAY_MS", "0"))

# Wstrzykiwanie 429 dla embeddingów (C6): co `every`-te żądanie od chwili ustawienia (0 wyłącza);
# `retry_after_s` ≠ None dodaje nagłówek `Retry-After`.
EMBED_429_EVERY: int = 0
EMBED_429_RETRY_AFTER_S: int | None = None
# Liczba żądań embeddingu od chwili ostatniego `POST /v1/fake/embed-429` (1-based).
_EMBED_429_COUNTER: int = 0

# --- Reguły zawężone do modelu (C8): pełna nazwa modelu → wartość; osobne od stanu globalnego ---
# Opóźnienia zawężone: `model → ms`; `ms == 0` usuwa wpis (jak w endpointach).
_EMBED_DELAY_SCOPED: dict[str, int] = {}
_OCR_DELAY_SCOPED: dict[str, int] = {}
# Wstrzykiwanie 429 zawężone: `model → {"every", "retry_after_s", "counter"}`.
_EMBED_429_SCOPED: dict[str, dict[str, Any]] = {}

# Trasy objęte wstrzykiwaniem 5xx (C7, poprawka 2026-10-11): `embeddings` i `chat`.
UPSTREAM_ROUTES: tuple[str, ...] = ("embeddings", "chat")

# Wstrzykiwanie 5xx globalne per trasa (C7): `every` = co ile żądań od chwili ustawienia
# (0 wyłącza), `status` = kod błędu, `times_left` = ile wstrzyknięć pozostało (None = bez
# limitu), `counter` = licznik żądań trasy (1-based).
_UPSTREAM: dict[str, dict[str, Any]] = {
    route: {"every": 0, "status": 500, "times_left": None, "counter": 0}
    for route in UPSTREAM_ROUTES
}
# Wstrzykiwanie 5xx zawężone do modelu (C8): `model → route → stan jak wyżej`.
_UPSTREAM_SCOPED: dict[str, dict[str, dict[str, Any]]] = {}
# Liczba wstrzykniętych błędów 5xx per trasa (C7, punkt (3); liczy też wstrzyknięcia zawężone).
UPSTREAM_ERRORS: dict[str, int] = {route: 0 for route in UPSTREAM_ROUTES}

router = APIRouter()


class OcrDelayRequest(BaseModel):
    """Ciało `POST /v1/fake/ocr-delay`: nieujemne opóźnienie w milisekundach (C6).

    Opcjonalne `model` (pełna nazwa z aliasem) zawęża regułę do tego modelu (C8);
    `ms == 0` z `model` usuwa regułę zawężoną.
    """

    ms: int = Field(ge=0)
    model: str | None = None


class EmbedDelayRequest(BaseModel):
    """Ciało `POST /v1/fake/embed-delay`: nieujemne opóźnienie embeddingów w milisekundach (C6).

    Opcjonalne `model` (pełna nazwa z aliasem) zawęża regułę do tego modelu (C8).
    """

    ms: int = Field(ge=0)
    model: str | None = None


class Embed429Request(BaseModel):
    """Ciało `POST /v1/fake/embed-429`: co ile żądań wstrzykiwać 429 i opcjonalny
    `Retry-After` (C6).

    Opcjonalne `model` (pełna nazwa z aliasem) zawęża regułę do tego modelu (C8);
    `every == 0` z `model` usuwa regułę zawężoną.
    """

    every: int = Field(ge=0)
    retry_after_s: int | None = Field(default=None, ge=0)
    model: str | None = None


class UpstreamErrorRequest(BaseModel):
    """Ciało `POST /v1/fake/upstream-error` (C7): trasa, co ile żądań, kod 5xx i opcjonalny limit.

    Walidacja (422 poza wartościami): `route` ∈ {embeddings, chat}, `status` ∈ {500,502,503,504},
    `every` int ≥ 0, `times` int ≥ 1 albo null. Opcjonalne `model` (pełna nazwa z aliasem)
    zawęża regułę do żądań tego modelu (C8).
    """

    route: Literal["embeddings", "chat"]
    status: Literal[500, 502, 503, 504]
    every: int = Field(ge=0)
    times: int | None = Field(default=None, ge=1)
    model: str | None = None


def record_chat_request(model: str) -> None:
    """Zwiększa licznik żądań czatu dla modelu o jeden."""
    CHAT_REQUESTS[model] += 1


def enter_model(model: str) -> None:
    """Wchodzi żądaniem modelu: zwiększa licznik „w locie” i aktualizuje maksimum (C6)."""
    _INFLIGHT[model] += 1
    MAX_CONCURRENT[model] = max(MAX_CONCURRENT[model], _INFLIGHT[model])


def exit_model(model: str) -> None:
    """Wychodzi żądaniem modelu: zmniejsza licznik „w locie” (C6)."""
    _INFLIGHT[model] -= 1


def record_embed_request(model: str) -> None:
    """Zwiększa liczniki żądań embeddingu: łączny, globalny „co N-te” i zawężony (C6, C8)."""
    global EMBED_REQUESTS, _EMBED_429_COUNTER  # noqa: PLW0603 — stan modułowy sterowany w locie (C6)
    EMBED_REQUESTS += 1
    _EMBED_429_COUNTER += 1
    scoped = _EMBED_429_SCOPED.get(model)
    if scoped is not None:
        scoped["counter"] += 1


def should_reject_embed(model: str) -> bool:
    """Czy bieżące żądanie embeddingu (po `record_embed_request`) ma zostać odrzucone 429.

    Reguła zawężona do `model` ma pierwszeństwo przed globalną (C6, C8).
    """
    scoped = _EMBED_429_SCOPED.get(model)
    if scoped is not None:
        every = scoped["every"]
        return bool(every > 0 and scoped["counter"] % every == 0)
    if EMBED_429_EVERY <= 0:
        return False
    return _EMBED_429_COUNTER % EMBED_429_EVERY == 0


def retry_after_header(model: str) -> dict[str, str] | None:
    """Nagłówek `Retry-After` dla wstrzykiwanego 429 albo None (C6).

    Wartość z reguły zawężonej modelu, inaczej globalnej (C8).
    """
    scoped = _EMBED_429_SCOPED.get(model)
    retry_after = scoped["retry_after_s"] if scoped is not None else EMBED_429_RETRY_AFTER_S
    if retry_after is None:
        return None
    return {"Retry-After": str(retry_after)}


def record_rejected_429() -> None:
    """Zwiększa licznik żądań embeddingu odrzuconych przez 429 (C6)."""
    global EMBED_REJECTED_429  # noqa: PLW0603 — stan modułowy sterowany w locie (C6)
    EMBED_REJECTED_429 += 1


def set_upstream_error(
    route: str, every: int, status: int, times: int | None, model: str | None = None
) -> None:
    """Włącza wstrzykiwanie 5xx dla trasy i zeruje jej licznik „co N-te” (C7).

    Z `model` (pełna nazwa z aliasem) reguła jest zawężona do tego modelu; `every == 0`
    z `model` usuwa regułę zawężoną (C8).
    """
    if model is None:
        _UPSTREAM[route] = {"every": every, "status": status, "times_left": times, "counter": 0}
        return
    if every == 0:
        scoped_routes = _UPSTREAM_SCOPED.get(model)
        if scoped_routes is not None:
            scoped_routes.pop(route, None)
            if not scoped_routes:
                _UPSTREAM_SCOPED.pop(model, None)
        return
    _UPSTREAM_SCOPED.setdefault(model, {})[route] = {
        "every": every,
        "status": status,
        "times_left": times,
        "counter": 0,
    }


def _apply_upstream(state: dict[str, Any], route: str) -> OpenAIError | None:
    """Liczy żądanie trasy i zwraca błąd 5xx do wstrzyknięcia albo None (C7, wspólne dla C8)."""
    if state["every"] <= 0:
        return None
    state["counter"] += 1
    if state["counter"] % state["every"] != 0:
        return None
    times_left = state["times_left"]
    if times_left is not None and times_left <= 0:
        return None
    UPSTREAM_ERRORS[route] += 1
    if times_left is not None:
        state["times_left"] = times_left - 1
        if times_left - 1 == 0:
            state["every"] = 0
            state["counter"] = 0
    status = state["status"]
    return OpenAIError(
        status,
        {"message": f"upstream error {status}", "type": "server_error"},
    )


def upstream_error_for(route: str, model: str) -> OpenAIError | None:
    """Bieżące żądanie trasy modelu: liczy je i zwraca błąd 5xx do wstrzyknięcia albo None (C7, C8).

    Wywoływane po zliczeniu żądania trasy, a przed opóźnieniami. Reguła zawężona do `model`
    ma pierwszeństwo i wyłącza regułę globalną. Gdy wstrzyknięcie wyczerpuje `times`, reguła
    wyłącza się sama (`every` → 0). `embed-429` ma pierwszeństwo — przy jego trafieniu ta
    funkcja nie jest wołana.
    """
    scoped = _UPSTREAM_SCOPED.get(model, {}).get(route)
    if scoped is not None:
        return _apply_upstream(scoped, route)
    return _apply_upstream(_UPSTREAM[route], route)


def upstream_state() -> dict[str, Any]:
    """Stan wstrzykiwania 5xx obu tras dla `GET /v1/fake/upstream-error` (C7).

    Klucz `scoped` (model → trasa → stan) dochodzi tylko, gdy są reguły zawężone (C8).
    """
    payload: dict[str, Any] = {
        route: {
            "every": _UPSTREAM[route]["every"],
            "status": _UPSTREAM[route]["status"],
            "times_left": _UPSTREAM[route]["times_left"],
        }
        for route in UPSTREAM_ROUTES
    }
    if _UPSTREAM_SCOPED:
        payload["scoped"] = {
            model: {
                route: {
                    "every": state["every"],
                    "status": state["status"],
                    "times_left": state["times_left"],
                }
                for route, state in routes.items()
            }
            for model, routes in _UPSTREAM_SCOPED.items()
        }
    return payload


def reset() -> None:
    """Zeruje liczniki — dla testów w procesie i scenariuszy T5.

    Opóźnień, ustawień embed-429 / upstream-error ani reguł zawężonych (C8) nie rusza (C6, C7).
    """
    global EMBED_REQUESTS, EMBED_REJECTED_429  # noqa: PLW0603 — stan modułowy sterowany w locie (C6)
    CHAT_REQUESTS.clear()
    MAX_CONCURRENT.clear()
    _INFLIGHT.clear()
    EMBED_REQUESTS = 0
    EMBED_REJECTED_429 = 0
    for route in UPSTREAM_ROUTES:
        UPSTREAM_ERRORS[route] = 0
    # Licznik wywołań narzędzi i numeracja `call_fake_<n>` (K10 2026-10-11c).
    tool_calls.reset()


def reset_scoped() -> None:
    """Usuwa wszystkie reguły zawężone do modelu (C8) — helper dla testów fake-llm.

    Endpointy HTTP usuwają regułę per `model` (wartość zerowa); to zerowanie hurtowe dla
    fixture'ów, żeby reguły jednego testu nie przeciekały do kolejnych w tym samym procesie.
    """
    _EMBED_DELAY_SCOPED.clear()
    _OCR_DELAY_SCOPED.clear()
    _EMBED_429_SCOPED.clear()
    _UPSTREAM_SCOPED.clear()


def ocr_delay_ms(model: str) -> int:
    """Opóźnienie `fake-ocr` dla modelu: reguła zawężona, inaczej globalna (C6, C8)."""
    return _OCR_DELAY_SCOPED.get(model, OCR_DELAY_MS)


def embed_delay_ms(model: str) -> int:
    """Opóźnienie embeddingów dla modelu: reguła zawężona, inaczej globalna (C6, C8)."""
    return _EMBED_DELAY_SCOPED.get(model, EMBED_DELAY_MS)


def set_ocr_delay_ms(ms: int, model: str | None = None) -> None:
    """Ustawia opóźnienie `fake-ocr` w milisekundach (C6).

    Z `model` reguła jest zawężona do tego modelu; `ms == 0` usuwa regułę zawężoną (C8).
    """
    if model is None:
        global OCR_DELAY_MS  # noqa: PLW0603 — stan modułowy sterowany w locie (C6)
        OCR_DELAY_MS = ms
        return
    if ms == 0:
        _OCR_DELAY_SCOPED.pop(model, None)
    else:
        _OCR_DELAY_SCOPED[model] = ms


def set_embed_delay_ms(ms: int, model: str | None = None) -> None:
    """Ustawia opóźnienie embeddingów w milisekundach (C6).

    Z `model` reguła jest zawężona do tego modelu; `ms == 0` usuwa regułę zawężoną (C8).
    """
    if model is None:
        global EMBED_DELAY_MS  # noqa: PLW0603 — stan modułowy sterowany w locie (C6)
        EMBED_DELAY_MS = ms
        return
    if ms == 0:
        _EMBED_DELAY_SCOPED.pop(model, None)
    else:
        _EMBED_DELAY_SCOPED[model] = ms


def set_embed_429(every: int, retry_after_s: int | None, model: str | None = None) -> None:
    """Włącza wstrzykiwanie 429 dla embeddingów i zeruje licznik „co N-te” (C6).

    Z `model` reguła jest zawężona do tego modelu; `every == 0` usuwa regułę zawężoną (C8).
    """
    global EMBED_429_EVERY, EMBED_429_RETRY_AFTER_S, _EMBED_429_COUNTER  # noqa: PLW0603 — stan modułowy (C6)
    if model is None:
        EMBED_429_EVERY = every
        EMBED_429_RETRY_AFTER_S = retry_after_s
        _EMBED_429_COUNTER = 0
        return
    if every == 0:
        _EMBED_429_SCOPED.pop(model, None)
        return
    _EMBED_429_SCOPED[model] = {"every": every, "retry_after_s": retry_after_s, "counter": 0}


def _snapshot() -> dict[str, Any]:
    """Bieżący stan liczników zwracany przez `/v1/fake/stats` (C6, C7, addytywnie)."""
    return {
        "chat_completions": dict(CHAT_REQUESTS),
        "embeddings": {"requests": EMBED_REQUESTS, "rejected_429": EMBED_REJECTED_429},
        "max_concurrent": dict(MAX_CONCURRENT),
        "upstream_errors": dict(UPSTREAM_ERRORS),
        "tool_calls": tool_calls.TOOL_CALLS,
    }


@router.get("/v1/fake/stats")
async def stats() -> dict[str, Any]:
    """Liczniki żądań czatu, embeddingów i maks. współbieżności per model (C6)."""
    return _snapshot()


@router.post("/v1/fake/stats/reset")
async def stats_reset() -> dict[str, Any]:
    """Zeruje liczniki żądań i zwraca pusty stan (C6); opóźnień i embed-429 nie zeruje."""
    reset()
    return _snapshot()


@router.get("/v1/fake/ocr-delay")
async def get_ocr_delay() -> dict[str, Any]:
    """Zwraca opóźnienie `fake-ocr` (globalne); klucz `scoped` gdy są reguły zawężone (C6, C8)."""
    payload: dict[str, Any] = {"ms": OCR_DELAY_MS}
    if _OCR_DELAY_SCOPED:
        payload["scoped"] = dict(_OCR_DELAY_SCOPED)
    return payload


@router.post("/v1/fake/ocr-delay")
async def set_ocr_delay(body: OcrDelayRequest) -> dict[str, Any]:
    """Ustawia opóźnienie `fake-ocr` — globalne albo zawężone do `body.model` (C6, C8).

    `ms < 0` → 422; `ms == 0` z `model` usuwa regułę zawężoną.
    """
    set_ocr_delay_ms(body.ms, body.model)
    return await get_ocr_delay()


@router.get("/v1/fake/embed-delay")
async def get_embed_delay() -> dict[str, Any]:
    """Zwraca opóźnienie embeddingów (globalne); klucz `scoped` gdy są reguły zawężone (C6, C8)."""
    payload: dict[str, Any] = {"ms": EMBED_DELAY_MS}
    if _EMBED_DELAY_SCOPED:
        payload["scoped"] = dict(_EMBED_DELAY_SCOPED)
    return payload


@router.post("/v1/fake/embed-delay")
async def set_embed_delay(body: EmbedDelayRequest) -> dict[str, Any]:
    """Ustawia opóźnienie embeddingów — globalne albo zawężone do `body.model` (C6, C8).

    `ms < 0` → 422; `ms == 0` z `model` usuwa regułę zawężoną.
    """
    set_embed_delay_ms(body.ms, body.model)
    return await get_embed_delay()


@router.get("/v1/fake/embed-429")
async def get_embed_429() -> dict[str, int | None]:
    """Zwraca bieżący stan wstrzykiwania 429 dla embeddingów (globalny, C6)."""
    return {"every": EMBED_429_EVERY, "retry_after_s": EMBED_429_RETRY_AFTER_S}


@router.post("/v1/fake/embed-429")
async def set_embed_429_endpoint(body: Embed429Request) -> dict[str, int | None]:
    """Włącza wstrzykiwanie 429 — globalne albo zawężone do `body.model` (C6, C8).

    `every`/`retry_after_s` < 0 → 422; `every == 0` z `model` usuwa regułę zawężoną.
    Zwraca stan globalny (kształt bez zmian).
    """
    set_embed_429(body.every, body.retry_after_s, body.model)
    return {"every": EMBED_429_EVERY, "retry_after_s": EMBED_429_RETRY_AFTER_S}


@router.get("/v1/fake/upstream-error")
async def get_upstream_error() -> dict[str, Any]:
    """Zwraca stan wstrzykiwania 5xx obu tras (globalny); klucz `scoped` gdy są reguły (C7, C8)."""
    return upstream_state()


@router.post("/v1/fake/upstream-error")
async def set_upstream_error_endpoint(body: UpstreamErrorRequest) -> dict[str, Any]:
    """Włącza wstrzykiwanie 5xx dla trasy — globalne albo zawężone do `body.model` (C7, C8).

    Niepoprawne ciało → 422; `every == 0` z `model` usuwa regułę zawężoną.
    """
    set_upstream_error(body.route, body.every, body.status, body.times, body.model)
    return upstream_state()
