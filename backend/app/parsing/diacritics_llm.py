"""Korekta diakrytyków przez LLM, porcjami (CONTRACT WP E5-H4b §3, wzór ``v34_llm.py``).

Klasa :class:`LlmDiacriticsCorrector` wysyła do modelu wyłącznie części edytowalne fragmentu
(te z literami — czyste liczby i znaki nigdy nie idą do modelu) w porcjach mieszczących się
w limitach :data:`CHUNK_MAX_CHARS` i :data:`CHUNK_MAX_SEGMENTS`. Każdy zwrócony segment przechodzi
bezpiecznik :func:`app.parsing.diacritics.fuse`; odrzucone porcje trafiają do :attr:`rejections`,
a zużycie tokenów do :attr:`tokens_in` / :attr:`tokens_out`. Wywołania porcji są sekwencyjne —
współbieżność zapewnia semafor wyżej w potoku.
"""

from __future__ import annotations

import json

from app.core.errors import WDError
from app.llm.gateway import LLMGateway
from app.llm.types import ChatMessage, ChatResult, ModelRef
from app.parsing.diacritics import WORD_RE, fuse, split_segments

# Limity jednej porcji (jedno żądanie do modelu).
CHUNK_MAX_CHARS: int = 1500
CHUNK_MAX_SEGMENTS: int = 40

# Minimalna liczba liter w części, by w ogóle wysłać ją do modelu (czyste liczby/znaki pomijamy).
_MIN_LETTERS: int = 3

# Górny limit tokenów odpowiedzi (jak ``max_tokens`` w ``v34_llm.py``).
_MAX_TOKENS: int = 4096

# Format odpowiedzi wymuszany na bramie (obiekt JSON ``{id: tekst}``).
_EXTRA: dict[str, object] = {"response_format": {"type": "json_object"}}

# Systemowy prompt — dosłownie stała ``SYSTEM`` z ``ocr-bench/diacritics-correction/v34_llm.py``.
SYSTEM_PROMPT: str = (
    "Jesteś korektorem tekstu z OCR polskiego rocznika statystycznego (GUS). "
    "Popraw wyłącznie polskie znaki diakrytyczne (ą ć ę ł ń ó ś ź ż) i oczywiste literówki OCR "
    "(np. 'ogólem'→'ogółem', 'Mężczyżni'→'Mężczyźni', 'šrednie'→'średnie'). "
    "NIE zmieniaj żadnych cyfr, liczb, przecinków dziesiętnych, "
    "kolejności słów, znaczników HTML/OTSL/Markdown/LaTeX "
    "(np. \\( ^a \\)), interpunkcji ani układu. "
    "Nie łącz i nie dziel wyrazów przeniesionych łącznikiem. "
    "Nie tłumacz i nie poprawiaj tekstu angielskiego. "
    "Jeśli fragment jest poprawny — zwróć go bez zmian. "
    "Wejście to obiekt JSON {id: tekst}; zwróć obiekt JSON "
    "z dokładnie tymi samymi kluczami i poprawionym tekstem."
)


class LlmDiacriticsCorrector:
    """Koryguje diakrytyki fragmentu HTML porcjami przez ``LLMGateway.chat``."""

    def __init__(self, llm: LLMGateway, model: ModelRef) -> None:
        self.llm = llm
        self.model = model
        self.rejections: list[str] = []
        self.tokens_in: int = 0
        self.tokens_out: int = 0

    async def correct(self, text: str, *, page: int) -> str:
        """Zwraca tekst z poprawionymi diakrytykami; porcje odrzucone zostają w oryginale."""
        parts, editable = split_segments(text)
        indexes = [index for index in editable if _has_enough_letters(parts[index])]
        for chunk_indexes in _chunk(indexes, parts):
            originals = [parts[index] for index in chunk_indexes]
            accepted = await self._correct_chunk(originals, page=page)
            for index, candidate in zip(chunk_indexes, accepted, strict=True):
                parts[index] = candidate
        return "".join(parts)

    async def _correct_chunk(self, originals: list[str], *, page: int) -> list[str]:
        """Jedno żądanie do modelu dla porcji; zwraca teksty po bezpieczniku (lub oryginały)."""
        messages: list[ChatMessage] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _payload(originals)},
        ]
        try:
            result = await self.llm.chat(self.model, messages, max_tokens=_MAX_TOKENS, extra=_EXTRA)
        except WDError:
            self.rejections.append(_rejection(page, "llm_error"))
            return originals
        self._accumulate(result)
        corrections = _parse(result.text)
        if corrections is None:
            # Zły JSON albo nie-obiekt: cała porcja odrzucona, oryginały zostają.
            self.rejections.append(_rejection(page, "missing"))
            return originals
        return [
            self._apply(original, corrections.get(str(position)), page=page)
            for position, original in enumerate(originals)
        ]

    def _apply(self, orig: str, value: object, *, page: int) -> str:
        """Przepuszcza jeden segment przez :func:`fuse` i notuje ewentualne odrzucenie.

        Wartość inna niż ``str`` (brak klucza albo zły typ) idzie jako ``None``
        (powód ``"missing"``).
        """
        new = value if isinstance(value, str) else None
        accepted, reason = fuse(orig, new)
        if reason is not None:
            self.rejections.append(_rejection(page, reason))
        return accepted

    def _accumulate(self, result: ChatResult) -> None:
        """Dolicza zużycie tokenów udanego wywołania."""
        self.tokens_in += result.tokens_in
        self.tokens_out += result.tokens_out


def _has_enough_letters(segment: str) -> bool:
    """Czy część ma co najmniej ``_MIN_LETTERS`` liter (czyste liczby/znaki pomijamy)."""
    return sum(len(word) for word in WORD_RE.findall(segment)) >= _MIN_LETTERS


def _payload(originals: list[str]) -> str:
    """Buduje treść żądania: obiekt JSON ``{"0": seg0, "1": seg1, ...}`` (bez ASCII-escape)."""
    return json.dumps(
        {str(position): text for position, text in enumerate(originals)}, ensure_ascii=False
    )


def _parse(raw: str) -> dict[str, object] | None:
    """Parsuje odpowiedź modelu; zwraca słownik albo ``None`` (zły JSON / nie-obiekt).

    Wartości spoza typu ``str`` (albo brakujące klucze) obsługuje metoda
    ``LlmDiacriticsCorrector._apply`` jako ``new is None`` (``fuse`` → ``"missing"``).
    """
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _chunk(indexes: list[int], parts: list[str]) -> list[list[int]]:
    """Dzieli indeksy segmentów na porcje wg :data:`CHUNK_MAX_CHARS` i :data:`CHUNK_MAX_SEGMENTS`.

    Kolejne segmenty łączone są dopóki suma znaków i liczba segmentów nie przekraczają limitów;
    pojedynczy segment dłuższy niż limit znaków idzie sam w porcji.
    """
    chunks: list[list[int]] = []
    current: list[int] = []
    chars = 0
    for index in indexes:
        length = len(parts[index])
        too_many = len(current) >= CHUNK_MAX_SEGMENTS
        too_long = current and chars + length > CHUNK_MAX_CHARS
        if too_many or too_long:
            chunks.append(current)
            current = []
            chars = 0
        current.append(index)
        chars += length
    if current:
        chunks.append(current)
    return chunks


def _rejection(page: int, reason: str) -> str:
    """Łańcuch odrzucenia porcji strony (kontrakt §3)."""
    return f"page {page}: diacritics chunk rejected ({reason})"
