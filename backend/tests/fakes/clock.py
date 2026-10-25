"""Fałszywka zegara do testów (kontrakt C7)."""


class FrozenClock:
    """Zegar o zamrożonym czasie, przesuwanym ręcznie przez advance()."""

    def __init__(self, ms: int = 1790157600000) -> None:
        self._ms = ms

    def now_ms(self) -> int:
        return self._ms

    def advance(self, ms: int) -> None:
        self._ms += ms
