"""Separacja bloku ``<think>`` z początku odpowiedzi modelu (kontrakt C5).

``split_think`` działa na całej odpowiedzi, ``ThinkStreamParser`` — na
strumieniu pociętym na dowolne chunki. Moduł importuje wyłącznie stdlib.
"""

# Port z RAGFlow v0.27.2 dialog_service.py (_stream_with_think_delta); Apache-2.0; zob. NOTICE.

from typing import Literal

THINK_OPEN = "<think>"
THINK_CLOSE = "</think>"

Kind = Literal["reasoning", "text"]
Event = tuple[Kind, str]

_State = Literal["start", "reasoning", "text"]


def split_think(text: str) -> tuple[str | None, str]:
    """Rozdziela ``(reasoning, text)``.

    Gdy tekst po ``lstrip()`` zaczyna się od ``<think>`` i zawiera
    ``</think>``: reasoning to treść między tagami (``strip()``), text to
    reszta po ``</think>`` (``lstrip()``). Inaczej ``(None, text)`` bez zmian
    (także ``<think>`` w środku i niedomknięty).
    """
    stripped = text.lstrip()
    if not stripped.startswith(THINK_OPEN):
        return (None, text)
    rest = stripped[len(THINK_OPEN) :]
    close = rest.find(THINK_CLOSE)
    if close < 0:
        return (None, text)
    return (rest[:close].strip(), rest[close + len(THINK_CLOSE) :].lstrip())


class ThinkStreamParser:
    """Maszyna stanów ``start → reasoning → text``.

    ``feed``/``flush`` zwracają zdarzenia ``(rodzaj, fragment)``; puste
    fragmenty nie są emitowane i wszystkie zdarzenia ``reasoning`` poprzedzają
    pierwsze ``text``. Bufor trzymamy tylko na możliwy prefiks tagu.
    """

    def __init__(self) -> None:
        self._state: _State = "start"
        self._buf = ""
        self._text_started = False  # czy po </think> wysłano już pierwszy znak text

    def feed(self, chunk: str) -> list[Event]:
        if self._state == "text":
            return self._feed_text(chunk)
        self._buf += chunk
        if self._state == "start":
            return self._feed_start()
        return self._feed_reasoning()

    def flush(self) -> list[Event]:
        events: list[Event] = []
        if self._buf and self._state == "start":
            events.append(("text", self._buf))
        elif self._buf and self._state == "reasoning":
            events.append(("reasoning", self._buf))
        self._buf = ""
        return events

    def _feed_start(self) -> list[Event]:
        stripped = self._buf.lstrip()
        if not stripped:  # same białe znaki — może jeszcze przyjść <think>
            return []
        if stripped.startswith(THINK_OPEN):
            # białe znaki przed tagiem odrzucone
            self._buf = stripped[len(THINK_OPEN) :]
            self._state = "reasoning"
            return self._feed_reasoning()
        if THINK_OPEN.startswith(stripped):  # możliwy prefiks tagu — czekamy
            return []
        # zdecydowanie nie blok <think> — cały bufor jako text
        text = self._buf
        self._buf = ""
        self._state = "text"
        self._text_started = True
        return [("text", text)]

    def _feed_reasoning(self) -> list[Event]:
        events: list[Event] = []
        close = self._buf.find(THINK_CLOSE)
        if close < 0:
            held = self._held_suffix_len()  # najdłuższy sufiks = prefiks </think>
            head = self._buf[: len(self._buf) - held]
            self._buf = self._buf[len(self._buf) - held :]
            if head:
                events.append(("reasoning", head))
            return events
        head = self._buf[:close]
        tail = self._buf[close + len(THINK_CLOSE) :]
        self._buf = ""
        self._state = "text"
        if head:
            events.append(("reasoning", head))
        rest = tail.lstrip()  # białe znaki zaraz po </think> odrzucane
        if rest:
            self._text_started = True
            events.append(("text", rest))
        return events

    def _feed_text(self, chunk: str) -> list[Event]:
        if self._text_started:  # po pierwszym znaku text każdy chunk przechodzi 1:1
            return [("text", chunk)] if chunk else []
        stripped = chunk.lstrip()  # dopóki nie wysłano znaku text: lstrip fragmentu
        if not stripped:
            return []
        self._text_started = True
        return [("text", stripped)]

    def _held_suffix_len(self) -> int:
        for held in range(min(len(THINK_CLOSE), len(self._buf)), 0, -1):
            if self._buf.endswith(THINK_CLOSE[:held]):
                return held
        return 0
