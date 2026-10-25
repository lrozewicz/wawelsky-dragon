"""Grep-test H13 (SSRF): żadne nowe miejsce w ``app/`` nie zyskuje klienta HTTP bez przeglądu.

Reguła: zbiór plików, które importują klientów sieciowych, musi być DOKŁADNIE równy stałej
``ALLOWED``. Nowy plik z klientem HTTP ⇒ czerwony test (świadoma zmiana + przegląd H13).

Skanowane importy: ``httpx``/``httpx2`` (repo używa ``httpx2``), ``urllib.request``,
``requests``, ``aiohttp``, ``socket``. ``urllib.parse`` (parsowanie URL, np. ``quote``
w trasach uploadu) NIE jest klientem sieciowym i celowo nie jest dopasowywany — brief
wymienia ``urllib.request``, nie całe ``urllib``.

Wyrocznia: ``uv run pytest tests/unit/test_outbound_http_grep.py -q``.
"""

import re
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2] / "app"

# DOKŁADNIE zbiór z ``git grep -nE "^\s*(import|from) (httpx|urllib|requests|aiohttp|socket)"``
# poszerzony o ``httpx2`` (wariant httpx używany w repo) i zawężony do klientów sieciowych.
# Każdy wpis z uzasadnieniem: konfiguracja administracyjna/env albo użycie lokalne.
ALLOWED = frozenset(
    {
        "app/core/container.py",  # httpx: klient OIDC; issuer z konfiguracji admina/env
        "app/integrations/sharepoint/auth.py",  # httpx: token Graph; base_url admina/env
        "app/integrations/sharepoint/connector.py",  # httpx: Graph; base_url admina/env
        "app/integrations/sharepoint/graph.py",  # httpx: Graph; base_url admina/env
        "app/integrations/sharepoint/graph_download.py",  # httpx: pobranie z Graph
        "app/integrations/sharepoint/log_redact.py",  # httpx: redakcja nagłówków Graph
        "app/llm/errors.py",  # httpx2: mapowanie wyjątków SDK; bez własnego ruchu
        "app/llm/openai_gateway.py",  # httpx2: bramka LLM; base_url z konfiguracji admina
        "app/mcp/client.py",  # httpx: klient API WD; api_base z WD_MCP_API_BASE (compose, K17 §1)
        "app/services/oidc.py",  # httpx: OIDC; issuer z konfiguracji admina/env
        "app/services/provider_probe.py",  # httpx2: sonda dostawcy; base_url admina/env
        "app/services/web_search/_http.py",  # httpx: transport dostawców; hosty wg API dostawcy/env
        "app/services/web_search/searxng.py",  # httpx: transport searxng; base_url config (K18 §5)
        "app/services/web_search/tavily.py",  # httpx: transport tavily; host API dostawcy (K18 §5)
        "app/services/web_search/brave.py",  # httpx: transport brave; host API dostawcy (K18 §5)
        "app/services/web_search/duckduckgo.py",  # httpx: transport duckduckgo; host API dostawcy
        "app/worker/loop.py",  # socket: wyłącznie gethostname (identyfikacja workera)
    }
)

# Narzędzia CLI uruchamiane ręcznie przez admina — poza ścieżką żądania HTTP.
EXEMPT_PREFIXES = ("app/tools/",)

_NETWORK_IMPORT_RE = re.compile(
    r"^\s*(?:import|from)\s+(?:httpx2?|urllib\.request|requests|aiohttp|socket)\b"
)


def matches(text: str) -> list[int]:
    """Numery linii (od 1) z importem klienta sieciowego."""
    return [
        no for no, line in enumerate(text.splitlines(), start=1) if _NETWORK_IMPORT_RE.search(line)
    ]


def offenders(root: Path) -> list[str]:
    """Ścieżki (względem ``backend/``) plików z klientem sieciowym, poza ``EXEMPT_PREFIXES``."""
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root.parent).as_posix()
        if rel.startswith(EXEMPT_PREFIXES):
            continue
        if matches(path.read_text(encoding="utf-8")):
            found.append(rel)
    return found


def test_no_unexpected_outbound_http_client() -> None:
    """Skan ``app/**/*.py``: zbiór plików z klientem sieciowym == ALLOWED (H13)."""
    assert set(offenders(APP_ROOT)) == set(ALLOWED)


def test_regex_semantics_on_synthetic_lines() -> None:
    """Lockdown regexu: klient sieciowy tak, parsowanie URL i komentarze nie."""
    assert matches("import httpx\n") == [1]
    assert matches("import httpx2\n") == [1]
    assert matches("from urllib.request import urlopen\n") == [1]
    assert matches("    import socket\n") == [1]
    assert matches("from urllib.parse import quote\n") == []
    assert matches("import urllib.parse\n") == []
    assert matches("# import httpx\n") == []
    assert matches("x = 'import httpx'\n") == []
