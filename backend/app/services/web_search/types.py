"""Typy wyszukiwania w sieci (CONTRACT E6-3f §C4, K18 §5).

`WebResult` — jeden wynik (tytuł, URL, fragment); `WebSearchProvider` — protokół dostawcy
(`name`, `search`); `WebSearchUnavailable` — błąd sieci/timeoutu/HTTP/JSON niesie nazwę
dostawcy i czytelną przyczynę, którą runtime przekazuje modelowi jako wynik narzędzia
(nie przerywa agenta). `str(e)` = ``"<provider>: <reason>"``.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class WebResult:
    """Pojedynczy wynik wyszukiwania (K18 §5)."""

    title: str
    url: str
    snippet: str


class WebSearchUnavailable(Exception):
    """Porażka dostawcy wyszukiwania: nazwa dostawcy + czytelna przyczyna (§C4)."""

    def __init__(self, provider: str, reason: str) -> None:
        self.provider = provider
        self.reason = reason
        super().__init__(f"{provider}: {reason}")


@runtime_checkable
class WebSearchProvider(Protocol):
    """Kontrakt dostawcy wyszukiwania (K18 §5)."""

    name: str

    async def search(self, query: str, *, top_n: int, timeout_s: float = 10.0) -> list[WebResult]:
        """Wyniki dla `query`, najwyżej `top_n`, w limicie `timeout_s` sekund (§C4)."""
        ...
