"""Porównanie strukturalne kroków MCP ze złotem v0.27.2 (K17 §5).

Reguły (wzór: ``tests/contract/ragflow/compare.py``, dostosowany do kształtu złota MCP —
``{request, outcome, result}`` bez ``status``/``content-type``):

- **struktura**: zbiory kluczy dict, długości list i typy JSON muszą się zgadzać;
- **maskowanie tokenów**: liść złota będący tokenem (``<ID:…>``, ``<FLOAT>``, ``<DATETIME>``,
  ``<IGNORE>``) — wartość realna musi być tokenem (`normalize.py` recordera nadaje ten sam
  kształt), bez porównywania numeru;
- **reguły dokładne** (`EXACT_PATHS`): pola niezależne od korpusu (nazwa/protocolVersion
  serwera, nazwy narzędzi i ich ``inputSchema``, ``error_type``/``http_status``) — równość co
  do wartości; teksty błędów narzędzi (``result.content.*.text`` będące napisem) — dosłownie;
- **maskowane poddrzewa** (`IGNORE_PATHS`): ``serverInfo.version`` (wersja pakietu ``mcp``),
  ``capabilities.experimental`` (odchyłka K17 §2: nie odbijamy nagłówków) oraz
  ``positions`` chunka (zależą od parsera dokumentu, nie od warstwy MCP);
- **opisy narzędzi**: porównywane po podstawieniu listy zasobów konta — prefiks do pierwszego
  ``{`` musi być identyczny, a doklejona lista zasobów mieć zgodną liczbę wpisów i zbiory kluczy
  (nazwy id-ów zasobów są korpusowe).

Zwraca listę napisów-problemów; pusta lista = zgodność.
"""

from __future__ import annotations

import json
from typing import Any

_MISSING = object()

# Poddrzewa pomijane (dokładne dopasowanie ścieżki segment po segmencie; ``*`` = dowolny segment).
IGNORE_PATHS: tuple[str, ...] = (
    "result.serverInfo.version",
    "result.capabilities.experimental",
    "result.content.*.text.chunks.*.positions",
)

# Ścieżki porównywane dosłownie (wartość po wartości).
EXACT_PATHS: tuple[str, ...] = (
    "request.transport",
    "request.op",
    "request.tool",
    "request.auth",
    "outcome",
    "result.protocolVersion",
    "result.serverInfo.name",
    "result.capabilities.tools.listChanged",
    "result.tools.*.name",
    "result.tools.*.inputSchema",
    "result.content.*.type",
    "result.isError",
    "result.error_type",
    "result.http_status",
)

_DESCRIPTION_PATHS = ("result.tools.*.description",)
_TEXT_PATHS = ("result.content.*.text",)
_MESSAGE_PATH = "result.message"
# Fragment komunikatu wspólny dla braku i złego klucza (K17 §3, złoto --15/--16/--29/--30).
UNAUTHORIZED = "Unauthorized"


def _json_type(value: object) -> str:
    """Typ JSON wartości: null, bool, number, string, array, object."""
    if value is None:
        return "null"
    if isinstance(value, bool):  # przed int — bool jest podklasą int
        return "bool"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _match(path: str, pattern: str) -> bool:
    """Dopasowanie ścieżki segment po segmencie; ``*`` w regule pasuje do jednego segmentu."""
    segments = path.split(".")
    pattern_segments = pattern.split(".")
    if len(segments) != len(pattern_segments):
        return False
    for segment, expected in zip(segments, pattern_segments, strict=True):
        if expected not in ("*", segment):
            return False
    return True


def _matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    return any(_match(path, pattern) for pattern in patterns)


def _is_token(value: object) -> bool:
    """Liść-złoto w formie tokenu normalizacji (``<…>``)."""
    return (
        isinstance(value, str)
        and value.startswith("<")
        and value.endswith(">")
        and len(value) > len("<>")
    )


def _resource_lines(description: str) -> list[str]:
    """Linie JSON doklejone do opisu narzędzia (lista zasobów konta); [] gdy brak."""
    _, brace, suffix = description.partition("{")
    if not brace:
        return []
    return [line for line in ("{" + suffix).splitlines() if line.strip()]


def _compare_description(path: str, golden: str, actual: object, problems: list[str]) -> None:
    """Prefiks opisu identyczny + zgodna struktura doklejonej listy zasobów konta."""
    if not isinstance(actual, str):
        problems.append(f"{path}: opis nie jest napisem ({_json_type(actual)})")
        return
    golden_prefix = golden.partition("{")[0]
    actual_prefix = actual.partition("{")[0]
    if golden_prefix != actual_prefix:
        problems.append(
            f"{path}: prefiks opisu różny\n  golden={golden_prefix!r}\n  actual={actual_prefix!r}"
        )
        return
    golden_lines = _resource_lines(golden)
    actual_lines = _resource_lines(actual)
    if len(golden_lines) != len(actual_lines):
        problems.append(f"{path}: liczba zasobów konta {len(golden_lines)} != {len(actual_lines)}")
        return
    for index, (g_line, a_line) in enumerate(zip(golden_lines, actual_lines, strict=True)):
        g_item = json.loads(g_line)
        a_item = json.loads(a_line)
        if isinstance(g_item, dict) and isinstance(a_item, dict) and set(g_item) != set(a_item):
            problems.append(
                f"{path}.resources.{index}: klucze {sorted(g_item)} != {sorted(a_item)}"
            )


def _child(path: str, key: object) -> str:
    """Ścieżka dziecka bez wiodącej kropki na poziomie korzenia."""
    return f"{key}" if not path else f"{path}.{key}"


# Reguły zależne od ścieżki rozgałęziają się na kilku poziomach — jak ``compare.py`` (K11 §5 p. 4).
def compare_payload(  # noqa: PLR0911, PLR0912
    golden: object, actual: object, path: str, problems: list[str]
) -> None:
    """Porównuje węzeł złota z wynikiem; dokłada napisy-problemy (pusta lista = zgodność)."""
    if _matches_any(path, IGNORE_PATHS):
        return
    if _matches_any(path, _DESCRIPTION_PATHS):
        _compare_description(path, str(golden), actual, problems)
        return
    if _match(path, _MESSAGE_PATH):
        if UNAUTHORIZED in str(golden) and UNAUTHORIZED not in str(actual):
            problems.append(f"{path}: brak {UNAUTHORIZED!r} w {actual!r}")
        return
    if _matches_any(path, EXACT_PATHS):
        if golden != actual:
            problems.append(f"{path}: oczekiwano {golden!r}, jest {actual!r}")
        return
    # Teksty błędów narzędzi (napis w ``text``) porównywane dosłownie; obiekty JSON — strukturalnie.
    if _matches_any(path, _TEXT_PATHS) and isinstance(golden, str):
        if golden != actual:
            problems.append(f"{path}: oczekiwano {golden!r}, jest {actual!r}")
        return

    if _json_type(golden) != _json_type(actual):
        problems.append(f"{path}: typ {_json_type(golden)} != {_json_type(actual)}")
        return
    if isinstance(golden, dict):
        assert isinstance(actual, dict)
        for key in sorted(golden.keys() - actual.keys()):
            problems.append(f"{_child(path, key)}: brak klucza (golden)")
        for key in sorted(actual.keys() - golden.keys()):
            problems.append(f"{_child(path, key)}: nadmiarowy klucz (actual)")
        for key in sorted(golden.keys() & actual.keys()):
            compare_payload(golden[key], actual[key], _child(path, key), problems)
    elif isinstance(golden, list):
        assert isinstance(actual, list)
        if len(golden) != len(actual):
            problems.append(f"{path}: długość {len(golden)} != {len(actual)}")
            return
        for index, (g_item, a_item) in enumerate(zip(golden, actual, strict=True)):
            compare_payload(g_item, a_item, _child(path, index), problems)
    elif _is_token(golden) and not _is_token(actual):
        problems.append(f"{path}: oczekiwano tokenu (np. {golden!r}), jest {actual!r}")
    # pozostałe liście: zgodność typu wystarcza (wartości korpusowe — nazwy, treści, liczniki)


def compare_step(golden: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    """Pełne porównanie kroku MCP (``request``/``outcome``/``result``); zwraca problemy."""
    problems: list[str] = []
    compare_payload(golden, actual, "", problems)
    return problems
