"""Testy etapu składanego korekty diakrytyków (CONTRACT WP E5-H4b §0 i §4, DEC-248/249)."""

from __future__ import annotations

from app.parsing.diacritics_stage import (
    LAYER_MIN_COVERAGE,
    WORDFREQ_DEFAULT,
    DiacriticsOptions,
    StageCorrector,
    layer_coverage,
)


class FakeLlmCorrector:
    """Atrapa korektora LLM: zapamiętuje wejścia i zwraca zadany tekst (albo wejście).

    ``result=None`` → tryb echa: zwraca fragment wejściowy bez zmian (jak odrzucona porcja).
    Dopisuje też zadany przyrost odrzuceń.
    """

    def __init__(
        self,
        result: str | None = None,
        *,
        preexisting: list[str] | None = None,
        new_rejection: str | None = None,
    ) -> None:
        self.result = result
        self.rejections: list[str] = list(preexisting or [])
        self._new_rejection = new_rejection
        self.pages: list[int] = []
        self.inputs: list[str] = []

    async def correct(self, fragment: str, *, page: int) -> str:
        self.pages.append(page)
        self.inputs.append(fragment)
        if self._new_rejection is not None:
            self.rejections.append(self._new_rejection)
        return fragment if self.result is None else self.result


async def test_layer_stage_corrects() -> None:
    corrector = StageCorrector(DiacriticsOptions())
    out, warnings = await corrector.correct("<p>Ogólem 10,8</p>", layer_text="Ogółem 10,8", page=1)
    assert (out, warnings) == ("<p>Ogółem 10,8</p>", [])


async def test_default_options_wordfreq_enabled() -> None:
    assert DiacriticsOptions().wordfreq is True
    corrector = StageCorrector(DiacriticsOptions())
    out, warnings = await corrector.correct("<p>mezczyzni 10,8</p>", layer_text="", page=1)
    assert (out, warnings) == ("<p>mężczyźni 10,8</p>", [])


async def test_no_layer_corrects_by_default() -> None:
    assert WORDFREQ_DEFAULT is True
    corrector = StageCorrector(DiacriticsOptions())
    out, warnings = await corrector.correct("<p>mezczyzni</p>", layer_text="", page=1)
    assert (out, warnings) == ("<p>mężczyźni</p>", [])


async def test_no_layer_noop_without_wordfreq() -> None:
    corrector = StageCorrector(DiacriticsOptions(wordfreq=False))
    out, warnings = await corrector.correct("<p>Ogólem 10,8</p>", layer_text="", page=1)
    assert (out, warnings) == ("<p>Ogólem 10,8</p>", [])


async def test_low_coverage_falls_through_to_wordfreq() -> None:
    corrector = StageCorrector(DiacriticsOptions(wordfreq=True))
    out, warnings = await corrector.correct(
        "<p>mezczyzni</p>", layer_text="zupełnie inny tekst", page=3
    )
    assert (out, warnings) == ("<p>mężczyźni</p>", [])


async def test_llm_stage_returns_rejection_delta() -> None:
    old = "page 1: diacritics chunk rejected (missing)"
    new = "page 2: diacritics chunk rejected (numbers)"
    llm = FakeLlmCorrector("<p>ogółem</p>", preexisting=[old], new_rejection=new)
    corrector = StageCorrector(DiacriticsOptions(llm=llm))
    out, warnings = await corrector.correct("<p>ogołem</p>", layer_text="", page=2)
    assert out == "<p>ogółem</p>"
    assert warnings == [new]
    assert llm.rejections == [old, new]
    assert llm.pages == [2]


async def test_llm_configured_skips_wordfreq_before_llm() -> None:
    llm = FakeLlmCorrector("<p>mężczyźni</p>")
    corrector = StageCorrector(DiacriticsOptions(wordfreq=True, llm=llm))
    out, warnings = await corrector.correct("<p>mezczyzni</p>", layer_text="", page=1)
    # LLM dostaje fragment niezmieniony przez wordfreq (nadal "mezczyzni").
    assert llm.inputs == ["<p>mezczyzni</p>"]
    assert (out, warnings) == ("<p>mężczyźni</p>", [])


async def test_wordfreq_fallback_when_llm_errors() -> None:
    rejection = "page 1: diacritics chunk rejected (llm_error)"
    llm = FakeLlmCorrector(new_rejection=rejection)  # echo: zwraca wejście bez zmian
    corrector = StageCorrector(DiacriticsOptions(wordfreq=True, llm=llm))
    out, warnings = await corrector.correct("<p>mezczyzni</p>", layer_text="", page=1)
    assert (out, warnings) == ("<p>mężczyźni</p>", [rejection])


async def test_no_wordfreq_fallback_on_other_rejections() -> None:
    rejection = "page 1: diacritics chunk rejected (numbers)"
    llm = FakeLlmCorrector(new_rejection=rejection)  # echo: zwraca wejście bez zmian
    corrector = StageCorrector(DiacriticsOptions(wordfreq=True, llm=llm))
    out, warnings = await corrector.correct("<p>mezczyzni</p>", layer_text="", page=1)
    assert (out, warnings) == ("<p>mezczyzni</p>", [rejection])


async def test_wordfreq_without_llm_unchanged() -> None:
    corrector = StageCorrector(DiacriticsOptions(wordfreq=True, llm=None))
    out, warnings = await corrector.correct("<p>mezczyzni</p>", layer_text="", page=1)
    assert (out, warnings) == ("<p>mężczyźni</p>", [])


async def test_layer_false_skips_layer() -> None:
    corrector = StageCorrector(DiacriticsOptions(layer=False, wordfreq=False))
    out, warnings = await corrector.correct("<p>Ogólem</p>", layer_text="Ogółem", page=1)
    assert (out, warnings) == ("<p>Ogólem</p>", [])


def test_layer_coverage_values() -> None:
    assert layer_coverage("<p>Ogólem 10,8</p>", "Ogółem 10,8") == 1.0
    assert layer_coverage("<p>ab cd</p>", "cokolwiek") == 1.0  # brak słów >= 3 liter
    assert LAYER_MIN_COVERAGE == 0.5  # noqa: PLR2004 — pin progu kontraktu (§4, DEC-248 P2)
    assert layer_coverage("<p>ogolem mezczyzni</p>", "Ogółem raport") == LAYER_MIN_COVERAGE
    assert layer_coverage("<p>mezczyzni</p>", "zupełnie inny tekst") == 0.0
    # Słowa z tagów HTML nie liczą się do pokrycia (§4): "table" jest w warstwie, ale poza treścią.
    assert layer_coverage("<table>ogolem</table>", "table") == 0.0
