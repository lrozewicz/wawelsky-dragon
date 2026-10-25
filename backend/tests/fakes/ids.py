"""Fałszywka generatora identyfikatorów do testów (kontrakt C7)."""


class SeqIdGenerator:
    """Generator zwracający kolejne liczby naturalne jako 32 znaki hex (licznik od 0)."""

    def __init__(self) -> None:
        self._counter = 0

    def new_id(self) -> str:
        self._counter += 1
        return f"{self._counter:032x}"
