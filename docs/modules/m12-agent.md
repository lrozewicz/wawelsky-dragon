# M12 — fundament Agenta (stan po E6-3f, 2026-10-12)

> **Zakres tego dokumentu**: część „fundament” pakietu E6-3f, czyli to, co powstało **przed** API `/agents*`,
  trasami wyszukiwania i UI (E6-3a/E6-3b): migracja `0008`, repozytoria, warstwa `web_search`, `tool_calls`
  w fake-llm, usługa compose `searxng`, stub `fake-searx`. Wszystko poniżej jest w kodzie `wp/E6-3f`.

## Co robi
Fundament Agenta to trzy niezależne elementy: (1) schemat bazy dla agentów i dostawców wyszukiwania (`0008`),
(2) warstwa dostawców wyszukiwania (`WebSearchProvider`, K18 §5), (3) usługa **`searxng`** w stosie produkcyjnym,
która daje agentowi wyszukiwanie w internecie bez kluczy zewnętrznych dostawców. Stos testowy dostaje stub
**`fake-searx`** zwracający deterministyczne wyniki, a fake-llm umie odpowiadać ramkami `tool_calls`, żeby dało się
przejść całą pętlę agenta (SC-E6-3f-04) bez internetu.

## Publiczny interfejs

### Migracja `0008_agents` (K2 §6)
`backend/alembic/versions/0008_agents.py`, `revision="0008"`, `down_revision="0007"`; `backend/app/db/schema.py`
`SCHEMA_HEAD = "0008"`. Trzy tabele (kolejność zakładania): `agents`, `agent_sessions`, `web_search_providers`.
Seed idempotentny: wiersz dostawcy `searxng` (`id` stały `5ea4c00d5ea4c00d5ea4c00d5ea4c00d`, `provider='searxng'`,
`name='searxng'`, `config='{"base_url": "http://searxng:8080"}'`, `is_default=1`), wstawiany tylko, gdy nie istnieje.
Downgrade: `DROP TABLE agent_sessions`, `agents`, `web_search_providers`.

### Usługa compose `searxng` (K18 §5, decyzja Q23 b)
`docker-compose.yml`, usługa `searxng` — obraz `wawelsky/searxng:${WD_VERSION:-latest}` budowany z `docker/searxng/`
(`FROM searxng/searxng:2026.10.4-d48c4b555`, przypięty tag). **Domyślnie włączona** (bez profilu), bez `ports`
(tylko sieć `wd-net`), bez `depends_on` po stronie `api`/`worker`.

| Element | Wartość |
|---|---|
| konfiguracja | `docker/searxng/settings.yml` (`use_default_settings: true`, `server.limiter: false`, `server.public_instance: false`, `search.formats: [html, json]`, `outgoing.request_timeout: 6.0`); `server.secret_key` **nie** jest w repo — nadpisuje go env `SEARXNG_SECRET` |
| sekret | `SEARXNG_SECRET: ${SEARXNG_SECRET:-${WD_SECRET_KEY:?}}` — brak zmiennej → pochodna `WD_SECRET_KEY` (istniejąca instalacja nie potrzebuje nowej) |
| limit pamięci | `deploy.resources.limits.memory: ${WD_SEARXNG_MEM_LIMIT:-256m}` |
| healthcheck | `wget -qO- http://localhost:8080/healthz` (co 10 s, 6 prób, `start_period` 10 s) |
| użytkownik | `USER searxng` (uid 977) w `docker/searxng/Dockerfile` — wymóg H11 |

Zmierzone (T5, `work/wp/E6-3f/reports/T5-searxng-measure.md`): start do `healthy` ~6 s, pamięć 99,13 MiB z 256 MiB.
Kontener odpytany po nazwie usługi z innego kontenera: `http://searxng:8080/search?q=test&format=json` → HTTP 200,
`application/json`. Bez dostępu do internetu `searxng` zwraca 200 z pustymi `results` i `unresponsive_engines`
(SC-E6-3f-03 = zachowanie dostawcy w backendzie, patrz T4).

### Stub `fake-searx` (K18 §5, C6)
`tools/fake-searx/` (wzorzec `tools/fake-graph`): pakiet `fake_searx`, start `python -m fake_searx.app`, port z
`FAKE_SEARX_PORT` (domyślnie 8080), zero zależności runtime.

| Trasa | Odpowiedź |
|---|---|
| `GET /search?q=<q>&format=json` | `{"query": q, "results": [{"title": "Wynik <i>: <q>", "url": "https://example.test/<i>", "content": "Fragment <i> o <q>"} dla i=1..3]}`; brak `q` → pusta lista |
| `GET /search?…&format=<inny>` | **403** (jak SearXNG bez włączonego JSON) |
| `GET /health` | 200 `{"status":"ok"}` |

W stosie testowym (`docker-compose.test.yml`) usługa `fake-searx` (obraz `wawelsky/fake-searx:${WD_VERSION:-latest}`,
bez portu na hoście); **nie** jest podnoszona przez `tools/dev/up.sh test up` — trzeba jej jawnie, gdy test dotyka
wyszukiwania (wniosek o krok w `.claude/verify*.sh` złożony do Architekta).

### fake-llm: `tools` → `tool_calls` (K10 „Poprawka 2026-10-11c”)
`tools/fake-llm/fake_llm/tool_calls.py` + hook w `chat.py`: `ChatRequest` przyjmuje `tools: list[dict] | None`;
tekst sterujący `[[tools:all]]` / `[[tool:<n>]]`, inaczej pierwsze narzędzie; odpowiedź to ramki SSE z
`tool_calls` (nazwa, fragmenty `arguments`, `finish_reason="tool_calls"`); po wiadomości `role: "tool"` wraca
odpowiedź końcowa; licznik widać w `GET /v1/fake/stats` (klucz `tool_calls`, reset przez `POST /v1/fake/stats/reset`).

## Jak uruchomić i przetestować
- Stub: `cd tools/fake-searx && uv run --frozen pytest -q --cov=fake_searx --cov-fail-under=90` → zielone (13 testów, 97%);
  `uv run --frozen ruff check . && uv run --frozen ruff format --check . && uv run --frozen mypy fake_searx` → czysto.
- Compose produkcyjny: `docker compose --env-file <env> -f docker-compose.yml config -q` → rc=0;
  `docker compose --env-file <env> -f docker-compose.yml up -d --wait searxng` → `healthy` w ~6 s.
- Stos testowy: `docker compose -p <proj> -f docker-compose.test.yml up -d --wait fake-searx`;
  `docker run --rm --network <proj>_default python:3.13-slim python -c "…urlopen('http://fake-searx:8080/search?q=kot&format=json')…"` → 3 wyniki wg C6.
- Wyrocznia WP (TL): `./.claude/verify-full.sh` (compose-check H11/H12 na `docker-compose.yml` jest zielony),
  `./.claude/verify-real.sh` (SC-E6-3f-01/-02 — czysta instalacja i aktualizacja `0007 → 0008`).

## Odstępstwa od docs/architecture/ (spec Agenta)
| punkt spec | co zrobiono | dlaczego |
|---|---|---|
| `settings.yml` z sekretem w repo | `server.secret_key` nie w repo; wartość z env `SEARXNG_SECRET`, domyślnie pochodna `WD_SECRET_KEY` | wymóg `tools/check_compose.py` H12 (sekrety nie mogą mieć domyślnej wartości w compose) i wcześniejsza decyzja o sekretach instalacji |
| obraz SearXNG jako obraz publiczny | własny obraz `wawelsky/searxng` z `COPY settings.yml` | K8-B p. 7 — bez bind-mountów ścieżek repo |
| usługa `searxng` w `docker-compose.test.yml` | stub `fake-searx` zamiast SearXNG | deterministyczne wyniki bez internetu (Q19) |

## Znane ograniczenia i dług
- Sekcja `.env.example` „SearXNG” (`WD_SEARXNG_MEM_LIMIT`, `SEARXNG_SECRET`) jest **zakomentowana**, tak jak sekcja
  „MCP”: sekcja „tylko compose” ma zamknięty zbiór zmiennych pod `backend/tests/unit/core/test_env_example.py`,
  a te zmienne są wyłącznie compose. Wartości domyślne wystarczają do pracy.
- `fake-searx` nie jest jeszcze podnoszony przez `tools/dev/up.sh test up` ani wyrocznię — do czasu zmiany
  `.claude/verify*.sh` (wniosek do Architekta) testy dotykające wyszukiwania muszą podnosić go jawnie.
- `tools/fake-searx` nie ma jeszcze kroku w `verify-fast.sh` (zakres wg diffu traktuje nieznane ścieżki jako
  „całość”, więc jego brak jest maskowany); wniosek o krok — jak wyżej.
- `_http.py` łapie tylko `httpx.HTTPError`: `base_url` z niepoprawnym portem (np. 99999) / `httpx.InvalidURL` wyjdzie jako
  surowy wyjątek — walidacja `config` należy do E6-3a (trasy zarządzania dostawcami).
- Dostawcy `tavily`/`brave`/`duckduckgo` testowani na fixture'ach w `backend/tests/fixtures/web_search/` zbudowanych wg
  znanych kształtów API, bez wywołań live (Q19).

## Warstwa danych i serwisy (T2/T4)
- `backend/app/db/repositories/{web_search_providers,agents,agent_sessions}.py` — styl `provider_instances.py`
  (`text()`, bez `commit`). `WebSearchProviderRow.api_key_enc` ma `repr=False`.
- `backend/app/services/web_search/`: `types.py` (`WebResult`, `WebSearchProvider`, `WebSearchUnavailable(provider, reason)`),
  `registry.get_provider(row, settings)`, `_http.py` (wspólny transport httpx, mapowanie błędów na `WebSearchUnavailable`,
  `__repr__` bez klucza), `searxng.py`, `tavily.py`, `brave.py`, `duckduckgo.py`, `keys.py`
  (`encrypt_key/decrypt_key`, AES-GCM, AAD `b"web-search-provider:" + id`).
- `rotate_crypto_key` obejmuje kolumnę `web_search_providers.api_key_enc` (guard schematu wymusił wpis).
- Testy: `tests/unit/services/web_search`, `tests/integration/web_search` (SC-03: martwy port i niemy serwer →
  `WebSearchUnavailable` < 3 s; SC-04: fake-searx jako podproces + pętla `tool_calls` z fake-llm). Mutacja
  `backend/tests/mutations/k18-web-search-key-leak.patch` → `MUTACJA WYKRYTA`.

## fake-llm: wstrzykiwanie zawężone do modelu (T6, wniosek o poprawkę K10)
Wstrzykiwanie `POST /v1/fake/{embed-delay,ocr-delay,embed-429,upstream-error}` było globalne dla wspólnej instancji
fake-llm i pod `pytest -n 8` psuło równoległe testy. Teraz: (a) alias modelu `<model_bazowy>~<scope>` (separator `~`,
bo `@` zajmuje `app/llm/registry.py:105`) działa jak model bazowy (odpowiedź, wymiary, `usage`; nieznana baza → 404);
(b) ciała czterech POST-ów przyjmują opcjonalne `"model": "<pełna nazwa z aliasem>"` — reguła dotyczy tylko żądań tego
modelu, wartość zerowa ją usuwa, bez pola zachowanie globalne bez zmian; (c) `stats/reset` nie usuwa reguł zawężonych;
(d) `GET …/{embed-delay,ocr-delay,upstream-error}` dodaje klucz `scoped` tylko, gdy istnieją reguły zawężone.
`test_concurrency.py` używa własnych aliasów. Flak MCP golden (`sha_retrieval_dataset_ids`) miał inną przyczynę:
domyślny read-timeout 5 s klienta MCP w testach (T7: `httpx.Timeout(60)` w `session_helpers.py` i
`tools/contract-recorder/mcp_runner.py`).

## Historia
| WP | data | zmiana |
|---|---|---|
| E6-3f | 2026-10-12 | fundament: migracja `0008` + seed `searxng`, `tool_calls` w fake-llm, usługa compose `searxng` + `docker/searxng/`, stub `fake-searx`, sekcja runbooka §14 |
