"""Parsowanie werdyktu modelu-sędziego i wywołanie modelu (A7 SPEC 7.2; port z bety).

Zawiera zarówno parsowanie werdyktu (`Verdict`, `parse_verdict`), jak i wywołanie
modelu-sędziego z własnym cache'em (`JudgeRunner`). Klient czatu i cache są
wstrzykiwane przez wywołującego — ten moduł nie importuje niczego z ``app.*``
ani ``openai``, żeby dało się go zaimportować i przetestować bez bazy i bez sieci.

Sędzia (Qwen w trybie myślenia, ``enable_thinking: true``) bywa, że
owija rozumowanie w blok ``<think>…</think>`` przed właściwą odpowiedzią TAK/NIE. Ten
blok trzeba wyciąć, zanim cokolwiek poszukamy — patrz kontrakt w ``parse_verdict``.

Trzy kształty myślenia, jakie trzeba obsłużyć (zaobserwowane / prawdopodobne na
podstawie szablonu czatu, który dokleja ``<think>`` + znak nowej linii do promptu):

1. domknięty (ew. zagnieżdżony) blok ``<think ...>…</think>`` — wycięty w całości;
2. niezamknięty ``<think>`` — model urwał się w środku rozumowania; wycinamy od
   tagu do końca łańcucha (werdykt schowany w nim się nie liczy);
3. **osierocony tag zamykający** bez odpowiadającego otwierającego — typowe, gdy
   szablon czatu sam dokleja `<think>` do promptu i model emituje tylko tag
   zamykający. Wycinamy od początku łańcucha do tego tagu włącznie.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from wdeval.judge_prompt import JUDGE_PROMPT_VERSION, VERDICT_KINDS, build_judge_messages

_OPEN_TAG = r"<\s*think\b[^>]*>"
_CLOSE_TAG = r"<\s*/\s*think\s*>"

# Domknięte (i sekwencyjnie wielokrotne) bloki <think ...>...</think>, dowolna
# wielkość liter, atrybuty/białe znaki w tagu dozwolone.
_THINK_CLOSED_RE = re.compile(_OPEN_TAG + r".*?" + _CLOSE_TAG, re.DOTALL | re.IGNORECASE)

# Osierocony tag zamykający (bez otwierającego) — wszystko od początku łańcucha
# do niego włącznie znika; tylko pierwsze takie wystąpienie.
_THINK_ORPHAN_CLOSE_RE = re.compile(r".*?" + _CLOSE_TAG, re.DOTALL | re.IGNORECASE)

# Niezamknięty <think> — zjada wszystko od siebie do końca łańcucha (zamierzone:
# werdykt schowany w rozumowaniu bez zamknięcia tagu nie liczy się).
_THINK_UNCLOSED_RE = re.compile(_OPEN_TAG + r".*\Z", re.DOTALL | re.IGNORECASE)

_VERDICT_RE = re.compile(r"\b(TAK|NIE)\b", re.IGNORECASE | re.UNICODE)


@dataclass(frozen=True)
class Verdict:
    kind: str  # "grounded" | "empty_ok" | "citation_ok"
    value: bool | None  # None == n/a (nie dało się rozstrzygnąć)
    raw: str  # surowa odpowiedź sędziego, bez zmian


def _strip_think(text: str) -> str:
    # Zastępujemy spacją (nie pustym stringiem), żeby słowa po obu stronach
    # wyciętego bloku nie skleiły się w jeden token bez granicy słowa.
    # Kolejność ma znaczenie: najpierw domknięte/zagnieżdżone bloki, potem
    # osierocony tag zamykający, na końcu niezamknięty otwierający.
    without_closed = _THINK_CLOSED_RE.sub(" ", text)
    without_orphan_close = _THINK_ORPHAN_CLOSE_RE.sub(" ", without_closed, count=1)
    return _THINK_UNCLOSED_RE.sub(" ", without_orphan_close)


def parse_verdict(kind: str, raw: str) -> Verdict:
    """Sparsuj surową odpowiedź sędziego na binarny werdykt.

    Po wycięciu myślenia bierzemy OSTATNIE samodzielne wystąpienie TAK/NIE w
    oczyszczonym tekście — prompt żąda jednej odpowiedzi, więc właściwy werdykt
    jest na końcu, a wszystko wcześniej to proza/rozumowanie, które prześliznęło
    się poza `<think>`. Przewidywalna reguła zamiast zgadywania intencji: np.
    "Nie da się ocenić." parsuje się na `False` (ostatnie samodzielne "Nie") —
    to celowe, jedyne `None` to brak jakiegokolwiek TAK/NIE w tekście.

    Nigdy nie rzuca na treści ``raw`` — śmieci dają ``Verdict(kind, None, raw)``.
    Rzuca ``ValueError`` wyłącznie na nieznany ``kind``.
    """
    if kind not in VERDICT_KINDS:
        raise ValueError(f"Nieznany rodzaj werdyktu: {kind!r}")

    cleaned = _strip_think(raw)
    matches = list(_VERDICT_RE.finditer(cleaned))

    value = None if not matches else matches[-1].group(1).upper() == "TAK"

    return Verdict(kind=kind, value=value, raw=raw)


# --- Wywołanie modelu-sędziego (A7 SPEC 7.2) --------------------------------
#
# Poniższe nie importuje niczego z ``app.*`` ani ``openai`` — klient czatu i
# cache są wstrzykiwane przez wywołującego (testy: atrapy). Dzięki temu ta
# ścieżka jest osiągalna bez bazy i bez sieci.
#
# ``_cache_key`` powiela format klucza cache'u z bety (ta sama sól:
# model+messages+temperature), żeby wpisy cache'a sędziego były zgodne
# między portem a betą. Duplikacja jest świadoma: import oryginału ciągnąłby
# zależności warstwy aplikacji do modułu czystego.


def _cache_key(model: str, messages: list[dict[str, str]], temperature: float) -> str:
    """Klucz cache'u sędziego: sha256 z modelu, wiadomości i temperatury."""
    payload = json.dumps(
        {"model": model, "messages": messages, "temperature": temperature}, sort_keys=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def judge_cache_model_key(model_name: str, mode: str) -> str:
    """Łańcuch do wpisania jako "model" w kluczu/wpisie cache'u sędziego.

    Obejmuje tryb myślenia i wersję promptu — sama nazwa modelu nie
    wystarcza, bo `cache_key` nie widzi ani jednego, ani drugiego. Bez tego
    zmiana promptu albo `reasoning_effort` cicho oddałaby stary werdykt.
    """
    return f"{model_name}#thinking={mode}#judge=v{JUDGE_PROMPT_VERSION}"


def is_openai_model(model_name: str) -> bool:
    """Modele bramki z prefiksem ``openai/`` (rodzina rozumujących gpt-5.x)."""
    return model_name.startswith("openai/")


def judge_extra_body(mode: str, model_name: str = "") -> dict[str, object]:
    """``extra_body`` dla wywołania czatu sędziego — włącza tryb myślenia na poziomie ``mode``.

    Poziom idzie dwiema drogami, bo dostawcy czytają go z różnych miejsc: vLLM (qwen3)
    z ``chat_template_kwargs``, a Z.ai (GLM) wyłącznie z pola ``reasoning_effort`` —
    ``chat_template_kwargs`` ignoruje (zmierzone: low i high dawały tę samą długość
    rozumowania). Bez drugiej drogi manifest deklarowałby poziom, którego nie zastosowano.
    """
    if is_openai_model(model_name):
        # gpt-5.x: bramka odrzuca chat_template_kwargs (400); zostaje samo reasoning_effort
        return {"reasoning_effort": mode}
    return {
        "chat_template_kwargs": {"enable_thinking": True, "reasoning_effort": mode},
        "reasoning_effort": mode,
    }


ChatFn = Callable[..., Awaitable[str]]
CacheGetFn = Callable[[str], Awaitable[str | None]]
CacheSetFn = Callable[[str, str, str], Awaitable[None]]


class JudgeRunner:
    """Wywołuje model-sędziego z cache'em obejmującym tryb myślenia i wersję promptu.

    Wszystko wstrzykiwane: nie importuje ``app.*`` ani ``openai``, nie buduje
    klienta ani sesji. Produkcja podaje callable czatu (``wdeval.evaluate``, T3b);
    testy — atrapy.
    """

    def __init__(
        self,
        *,
        model_name: str,
        chat: ChatFn,
        mode: str = "medium",
        cache_get: CacheGetFn | None = None,
        cache_set: CacheSetFn | None = None,
    ) -> None:
        self.model_name = model_name
        self.chat = chat
        self.mode = mode
        self.cache_get = cache_get
        self.cache_set = cache_set

    async def __call__(self, kind: str, payload: dict[str, str]) -> Verdict:
        messages = build_judge_messages(kind, payload)
        cache_model = judge_cache_model_key(self.model_name, self.mode)
        key = _cache_key(cache_model, messages, 0.0)

        if self.cache_get is not None:
            cached = await self.cache_get(key)
            if cached is not None:
                return parse_verdict(kind, cached)

        # gpt-5.x z reasoning_effort odrzuca temperature (400) — dla nich nie wysyłamy (None)
        temperature = None if is_openai_model(self.model_name) else 0
        raw = await self.chat(
            self.model_name,
            messages,
            temperature=temperature,
            extra_body=judge_extra_body(self.mode, self.model_name),
        )

        if self.cache_set is not None:
            await self.cache_set(key, cache_model, raw)

        return parse_verdict(kind, raw)
