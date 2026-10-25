"""Etap składany korekty diakrytyków (CONTRACT WP E5-H4b §0 i §4, DEC-248, DEC-249).

Spina etapy korekty fragmentu z wizji w kolejności: warstwa PDF → LLM, a wordfreq tylko jako
fallback. Warstwa działa tylko wtedy, gdy przeszła bramkę routera (``PendingPage.text_layer``
niepuste) i pokrywa fragment w stopniu >= :data:`LAYER_MIN_COVERAGE`; inaczej uruchamiane są
dalsze etapy wg :class:`DiacriticsOptions`. Gdy skonfigurowano LLM, działa on sam (wordfreq
przed LLM psuje wynik — eval (d)); wordfreq uruchamia się wyłącznie na wyniku LLM, gdy porcja
została odrzucona z powodu błędu bramki (``llm_error``). Etap LLM jest domyślnie wyłączony;
etap wordfreq włącza :data:`WORDFREQ_DEFAULT` (słownik lokalny, 0 USD).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.parsing.diacritics import WORD_RE, correct_with_layer, fold, split_segments
from app.parsing.diacritics_dict import correct_with_wordfreq
from app.parsing.diacritics_llm import LlmDiacriticsCorrector

# Minimalny udział słów fragmentu pokrytych warstwą, przy którym korekta na warstwie się kończy.
LAYER_MIN_COVERAGE: float = 0.5
# Domyślne włączenie etapu wordfreq; wartość ustala eval (d) (DEC-249 p. 6).
# Włączony po eval (d) — kryterium DEC-249 p. 6 spełnione (+28,1 p.p.,
# 0 fałszywych poprawek, 0 zmian liczb).
# Działanie: wordfreq poprawia, gdy LLM wyłączony lub zawiódł; przed LLM nie działa
# (eval (d): 98,55% vs 99,52% samego LLM).
WORDFREQ_DEFAULT: bool = True

# Powód odrzucenia porcji LLM, po którym uruchamiany jest fallback wordfreq (§0).
_LLM_ERROR_SUFFIX: str = "(llm_error)"

# Do pokrycia liczą się wyłącznie słowa o co najmniej tylu literach (§4).
_MIN_COVERAGE_WORD_LEN: int = 3

# Wynik korekty fragmentu: (poprawiony fragment, ostrzeżenia etapów).
Correction = tuple[str, list[str]]


@dataclass(frozen=True)
class DiacriticsOptions:
    """Włączniki etapów korekty jednej strony (bez klucza ``diacritics`` = tylko warstwa)."""

    layer: bool = True
    wordfreq: bool = WORDFREQ_DEFAULT
    llm: LlmDiacriticsCorrector | None = None


class DiacriticsCorrector(Protocol):
    """Port korektora fragmentu: (poprawiony fragment, ostrzeżenia)."""

    async def correct(self, fragment: str, *, layer_text: str, page: int) -> Correction: ...


class StageCorrector:
    """Koryguje fragment wizji kolejnymi etapami wg :class:`DiacriticsOptions` (§0)."""

    def __init__(self, options: DiacriticsOptions) -> None:
        self.options = options

    async def correct(self, fragment: str, *, layer_text: str, page: int) -> Correction:
        """Zwraca (poprawiony fragment, ostrzeżenia) po przejściu włączonych etapów.

        Warstwa: gdy włączona i niepusta — korekta na warstwie, a przy pokryciu fragmentu
        >= :data:`LAYER_MIN_COVERAGE` koniec (etapy dalsze pomijane). W przeciwnym razie
        (brak warstwy, ``layer=False`` albo niskie pokrycie) działa LLM, a przy jego braku
        wordfreq. Gdy LLM jest skonfigurowany, wordfreq NIE poprzedza go; uruchamiany jest
        tylko na wyniku LLM, gdy przyrost odrzuceń zawiera porcję odrzuconą przez błąd bramki
        (``llm_error``).
        """
        out = fragment
        if self.options.layer and layer_text.strip():
            out = correct_with_layer(fragment, layer_text)
            if layer_coverage(fragment, layer_text) >= LAYER_MIN_COVERAGE:
                return out, []
        if self.options.llm is None:
            if self.options.wordfreq:
                out = correct_with_wordfreq(out)
            return out, []
        before = len(self.options.llm.rejections)
        out = await self.options.llm.correct(out, page=page)
        # `rejections` jest współdzielone między stronami — bierzemy tylko przyrost z wywołania.
        warnings = self.options.llm.rejections[before:]
        if self.options.wordfreq and any(w.endswith(_LLM_ERROR_SUFFIX) for w in warnings):
            out = correct_with_wordfreq(out)
        return out, warnings


def layer_coverage(fragment: str, layer_text: str) -> float:
    """Udział słów fragmentu (poza tagami, >= 3 litery) obecnych w warstwie (wg ``fold``).

    Brak słów o co najmniej 3 literach daje pokrycie ``1.0`` (nie ma czego korygować).
    """
    words = _content_words(fragment)
    if not words:
        return 1.0
    layer_folds = {fold(word) for word in WORD_RE.findall(layer_text)}
    covered = sum(1 for word in words if fold(word) in layer_folds)
    return covered / len(words)


def _content_words(fragment: str) -> list[str]:
    """Słowa treści fragmentu (poza tagami HTML) o długości >= ``_MIN_COVERAGE_WORD_LEN``."""
    parts, editable = split_segments(fragment)
    return [
        word
        for index in editable
        for word in WORD_RE.findall(parts[index])
        if len(word) >= _MIN_COVERAGE_WORD_LEN
    ]
