"""split_think — rozdział strumienia par (is_reasoning, text) na zdarzenia czatu (CONTRACT C2)."""

# Port z RAGFlow v0.27.2 dialog_service.py (_stream_with_think_delta); Apache-2.0; zob. NOTICE.

from collections.abc import AsyncIterator, Callable

from app.domain.chat.events import AnswerDelta, ThinkDelta, ThinkEnd, ThinkStart


async def split_think(
    stream: AsyncIterator[tuple[bool, str]],
    *,
    count_tokens: Callable[[str], int],
    min_tokens: int = 16,
) -> AsyncIterator[ThinkStart | ThinkDelta | ThinkEnd | AnswerDelta]:
    """Rozdział myślenia od odpowiedzi z buforowaniem delt (K4 §1.3, R0 p. 7).

    Pusty ``text`` pomijany. ``is_reasoning=True``: przy wejściu w myślenie najpierw
    flush bufora jako ``AnswerDelta`` (reasoning w trakcie odpowiedzi, R0 p. 7), potem
    ``ThinkStart`` i ``ThinkDelta`` dla każdej pary. ``is_reasoning=False``: zamknięcie
    bloku ``ThinkEnd`` i buforowanie — emisja, gdy ``count_tokens(bufor) >= min_tokens``.
    Koniec strumienia: ``ThinkEnd`` gdy wciąż w myśleniu, potem flush niepustego bufora.
    """
    in_think = False
    buffer = ""
    async for is_reasoning, text in stream:
        if not text:
            continue
        if is_reasoning:
            if not in_think:
                if buffer:
                    yield AnswerDelta(buffer)
                    buffer = ""
                yield ThinkStart()
                in_think = True
            yield ThinkDelta(text)
        else:
            if in_think:
                yield ThinkEnd()
                in_think = False
            buffer += text
            if count_tokens(buffer) >= min_tokens:
                yield AnswerDelta(buffer)
                buffer = ""
    if in_think:
        yield ThinkEnd()
    if buffer:
        yield AnswerDelta(buffer)
