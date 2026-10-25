# K18 — prosty Agent (M12): DSL WD, API `/agents*`, ramki SSE, `WebSearchProvider`

Status: **ZAMROŻONY** 2026-10-11 (Architekt, zmiana 26), **z wyjątkiem §4.3** (kształt `reference` i ramek przy wywołaniu narzędzia — rozstrzyga E6-3a: źródło upstream + nagranie złota ścieżki narzędziowej po rozszerzeniu fake-llm w E6-3f).
Źródła: `docs/architecture/13-v1x.md` §4 (ZAAKCEPTOWANA), `docs/contracts/golden-E6.md` §„Agenty” i „Fakty dla K18”, złoto `backend/tests/contract/golden/v0.27.2/agents*/agents--*`, upstream v0.27.2 `api/apps/restful_apis/agent_api.py`, `agent/canvas.py`, `agent/component/{begin,agent_with_tools,message}.py`.
Dane: K2 §6 (`0008_agents`). fake-llm: K10 „Poprawka 2026-10-11c”. Zmiana = wniosek do Architekta.

## 1. DSL
- Przyjmujemy i zwracamy **format DSL upstream** (obiekt JSON; zapis bez normalizacji treści, zwrot z kluczami posortowanymi jak upstream — złoto `--06`).
- **Uruchamialny** (WD) ⇔ `components` zawiera dokładnie trzy węzły: `Begin` → `Agent` → `Message` (pole `obj.component_name`; krawędzie `downstream`/`upstream` liniowe), a narzędzia komponentu `Agent` (`obj.params.tools[].component_name`) ⊆ {`Retrieval`, `SearXNG`, `TavilySearch`, `DuckDuckGo`, `Google`}. `dsl: {}` — poprawny, nieuruchamialny (pusty graf, jak upstream `--08`).
- `POST/PUT /agents` z DSL zawierającym inny komponent/narzędzie → `code 101`, `message: "component <Nazwa> is not supported by Wawelsky Dragon"` (pierwszy nieobsługiwany w kolejności kluczy `components`). Agent zaimportowany przez `ragflow_migrate` z takim DSL **zapisuje się** z `unsupported_components = [nazwy]`; `POST /agents/chat/completions` dla niego → `code 101` z tym samym komunikatem.
- Walidacja pozostałych błędów (`dsl` brak/nie-obiekt, `title` brak, duplikat tytułu) — kody i komunikaty **jak złoto** `--07…13`, `--29…30`.
- Parametry komponentu `Agent` czytane przez runtime (reszta przechowywana, ignorowana): `llm_id`, `sys_prompt`, `prompts`, `temperature`/`top_p`/`max_tokens` (jeśli obecne), `max_rounds` (domyślnie jak upstream), `tools[].params` (Retrieval: `kb_ids`, `top_n`, `similarity_threshold`, `keywords_similarity_weight`; web search: `top_n`, dostawca wg §5). `Message`: `content` (zmienne `{agent@content}` jak upstream).

## 2. API (`/api/v1`, kształt i kody jak złoto)
Trasy obsługiwane: `GET /agents/templates`, `GET/POST /agents`, `GET/PUT/DELETE /agents/{id}`, `GET/POST/DELETE /agents/{id}/sessions`, `GET/DELETE /agents/{id}/sessions/{sid}`, `POST /agents/chat/completions` (SSE i JSON).
Każdy krok złota `agents--05…68` ma test kontraktowy WD, z odchyłkami:
1. `GET /agents/templates` — **szablony WD** (1–2: „Asystent z bazą wiedzy” = Begin→Agent(Retrieval)→Message; „Asystent z wyszukiwarką” = + SearXNG), w kształcie elementu listy upstream; liczba i treść ≠ upstream (`SKIPPED`/odchyłka w teście: porównanie kształtu, nie zawartości).
2. `GET /agents` — parametry jak golden-E6 „Fakty z agentów” (`title`/`id` ignorowane; `type=filter` → `data.filter`); tryb „merge” grup szablonów — WD nie ma grup → zachowanie jak stos bez grup (`--14`).
3. Pozostałe trasy `/agents*` (webhook, versions, debug, rerun, upload, reset, test_db_connection, attachments, logs, prompts, download, tags, input-form), `/agents_openai/*`, `/agentbots/*` — odmowa `NotSupported` jak dotąd (K11 tabela odmów).
Dostęp: agent należy do `tenant_id`; `permission: team` — jak czaty (K11 §6). Klucz API i JWT jak pozostałe trasy.

## 3. Sesje
`agent_sessions` (K2 §6): `POST /agents/{id}/sessions` tworzy sesję z migawką `dsl` **rozszerzoną domyślnymi upstream** (kształt `data.dsl` jak złoto `--31`; `version_title` = `f"{nickname}_{title}_%Y-%m-%d %H:%M:%S"`). `messages`/`reference` — jak upstream `API4Conversation` (lista wiadomości, lista referencji per odpowiedź). Kody: brakująca sesja `102`, cudza `103` (złoto).

## 4. Runtime i SSE
1. Pętla function-calling (OpenAI `tools`) przez `LLMGateway` (`tool_choice: auto`), najwyżej `max_rounds` rund narzędzi, potem odpowiedź bez narzędzi. Tokeny sumowane do `usage` (`calls`, `prompt_tokens`, `completion_tokens`, `total_tokens`) i `agent_sessions.tokens`.
2. **Ramki SSE i JSON — dokładnie jak „Fakty dla K18”** w `golden-E6.md`: nowa sesja `workflow_started → node_started(begin) → node_finished(begin) → node_started(agent) → node_started(message) → n × message → message_end → node_finished(agent) → node_finished(message) → workflow_finished → [DONE]`; istniejąca sesja — filtr `_iter_session_completion_events` (od `node_finished(begin)`); JSON bez `stream` — nowa sesja = `workflow_finished` + `data.data.{content,reference}`, istniejąca = `message_end` + `content`, `reference`, `usage`. Pola ramek jak tam (`event`, `message_id`, `created_at`, `task_id`, `session_id`, `data`).
3. **[OTWARTE → E6-3a]** Gdy agent wywołał narzędzie: dodatkowe ramki (jeśli upstream je emituje) i kształt `reference` (bez narzędzia: `{}` — złoto). E6-3a ustala ze źródła upstream (`agent/canvas.py`, `agent_with_tools.py`), nagrywa złoto ścieżki narzędziowej recorderem z fake-llm po K10 2026-10-11c, Architekt dopisuje tu wynik przed odbiorem E6-3a. Cytowania w UI — format czatu K4, jeśli upstream ma `chunks`/`doc_aggs`.
4. Błąd modelu/narzędzia w trakcie: ramka `node_finished` z `error` ≠ null (jak upstream), potem `workflow_finished`; komunikat zrozumiały (bez stack trace). Anulowanie przez zamknięcie strumienia przerywa pętlę.

## 5. `WebSearchProvider`
```python
@dataclass(frozen=True)
class WebResult:
    title: str
    url: str
    snippet: str

class WebSearchProvider(Protocol):
    name: str                     # "searxng" | "tavily" | "brave" | "duckduckgo"
    async def search(self, query: str, *, top_n: int, timeout_s: float = 10.0) -> list[WebResult]: ...
```
- Rejestr `backend/app/services/web_search/registry.py`: `get_provider(row: WebSearchProviderRow) -> WebSearchProvider`; konfiguracja z `web_search_providers` (K2 §6; klucz `api_key_enc` przez M4 crypto, nigdy w odpowiedziach API ani logach).
- `searxng`: `GET {config.base_url}/search?q=<q>&format=json&language=<lang?>` → `results[].{title,url,content}` (pierwsze `top_n`). Błąd/timeout → wyjątek `WebSearchUnavailable(provider, reason)` → wynik narzędzia z komunikatem dla modelu (nie przerywa agenta).
- Zewnętrzni dostawcy (`tavily`, `brave`, `duckduckgo`) — testy na nagranych odpowiedziach, bez live (Q19).
- Compose: usługa **`searxng`** (obraz upstream SearXNG, **wersja przypięta**), konfiguracja `docker/searxng/settings.yml` (format JSON włączony, bez limitera dla sieci wewnętrznej), domyślnie **włączona** (Q23 b), limit pamięci `${WD_SEARXNG_MEM_LIMIT:-256m}`; seed: rekord `web_search_providers` `searxng` (`base_url: http://searxng:8080`, `is_default=1`) przy migracji/seedzie. Stos testowy: stub **`fake-searx`** (deterministyczne wyniki: dla zapytania `q` 3 wyniki `title: "Wynik <i>: <q>"`, `url: https://example.test/<i>`, `snippet: "Fragment <i> o <q>"`).
- API zarządzania dostawcami (admin): `/api/wd/v1/web-search-providers` (GET lista bez kluczy, POST, PATCH, DELETE, `POST …/{id}/verify`) — kształt koperty WD jak `/api/wd/v1/providers*` (K13).

## 6. Interfejs wewnętrzny E6-3a1 ↔ E6-3a2 (Architekt, zmiana 27, 2026-10-12 — ZAMROŻONY)
E6-3a dzielony na dwa równoległe WP: **E6-3a1** (DSL, API `/agents*` bez completions, sesje, szablony, `ragflow_migrate`, API dostawców wyszukiwania) i **E6-3a2** (runtime, narzędzia, `POST /agents/chat/completions`, §4.3). Styk = jeden plik o treści **dosłownie** jak niżej — **oba WP tworzą go jako pierwsze zadanie z identyczną treścią** (git scala identyczne dodania bez konfliktu); zmiana treści = wniosek do Architekta.

`backend/app/domain/agent/spec.py`:
```python
"""Specyfikacja uruchamialnego agenta WD (K18 §6) — wspólny styk E6-3a1 (DSL) i E6-3a2 (runtime)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ToolKind = Literal["retrieval", "web_search"]

# Nazwy komponentów narzędzi akceptowane w `Agent.params.tools[].component_name` (K18 §1).
RETRIEVAL_COMPONENTS: frozenset[str] = frozenset({"Retrieval"})
WEB_SEARCH_COMPONENTS: frozenset[str] = frozenset(
    {"SearXNG", "TavilySearch", "DuckDuckGo", "Google"}
)


class UnsupportedComponentError(ValueError):
    """DSL zawiera komponent/narzędzie spoza podzbioru WD (K18 §1) — `code 101`."""

    def __init__(self, name: str) -> None:
        super().__init__(f"component {name} is not supported by Wawelsky Dragon")
        self.name = name


@dataclass(frozen=True)
class ToolSpec:
    kind: ToolKind
    component_name: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentSpec:
    llm_id: str
    sys_prompt: str
    prompts: list[dict[str, Any]]
    max_rounds: int
    tools: tuple[ToolSpec, ...]
    message_content: str
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
```
Podział funkcji (sygnatury wiążące):
- **E6-3a1** — `backend/app/domain/agent/dsl.py`: `unsupported_components(dsl: dict[str, Any]) -> list[str]`; `parse_runnable(dsl: dict[str, Any]) -> AgentSpec` (rzuca `UnsupportedComponentError`, a dla `dsl: {}`/grafu nie Begin→Agent→Message — `UnsupportedComponentError` z nazwą pierwszego niepasującego węzła albo `ValueError` dla pustego grafu; domyślne `max_rounds` jak upstream). `backend/app/services/agents.py`: `async def create_session(db, *, agent: AgentRow, user: UserRow) -> AgentSessionRow` (migawka DSL z domyślnymi upstream, `version_title`, K18 §3) i `async def append_turn(db, *, session: AgentSessionRow, question: str, answer: str, reference: dict[str, Any], tokens: int) -> None` (`messages`/`reference`/`tokens` jak §3). Nazwy typów wierszy — jak w `backend/app/db/repositories/agents.py` / `agent_sessions.py` (E6-3f); jeśli różnią się od `AgentRow`/`AgentSessionRow`, użyj istniejących — to nie zmiana kontraktu.
- **E6-3a2** — `backend/app/domain/agent/runtime.py` (pętla §4.1 na `AgentSpec`, zdarzenia), `backend/app/domain/agent/tools.py` (Retrieval przez istniejący serwis retrievalu; web search przez `services/web_search/registry.py`), trasa `POST /agents/chat/completions` (SSE i JSON, §4.2–4.4). Do czasu scalenia E6-3a1 do `main` testy E6-3a2 budują `AgentSpec` wprost; zadanie trasy completions (używa `parse_runnable`, `create_session`, `append_turn`) TL E6-3a2 zleca **po** `git merge main` z E6-3a1.

## Poprawka 2026-10-12 (Architekt, zmiana 27 — odbiór E6-3f)
§5 compose: sekret SearXNG = `SEARXNG_SECRET: ${SEARXNG_SECRET:-${WD_SECRET_KEY:?}}` (zatwierdzone odstępstwo — reguła H12 `tools/check_compose.py`); `settings.yml` bez `secret_key`; obraz własny `wawelsky/searxng` (`FROM searxng/searxng:2026.10.4-d48c4b555`). `fake-searx` nie jest podnoszony przez `tools/dev/up.sh test up` — testy, które go potrzebują, startują go same (podproces) albo jawnie.

## Poprawka 2026-10-12b (Architekt, zmiana 27 — zgłoszenie TL E6-3a1)
§6 `spec.py`: linia `WEB_SEARCH_COMPONENTS` złamana dokładnie tak, jak robi to `ruff format` (konfiguracja `backend/pyproject.toml`); treść bloku = wyjście `ruff format` (sprawdzone: `ruff format` bez zmian, `ruff check` czysto).
