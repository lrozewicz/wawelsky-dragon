# M11 — serwer MCP (stan po E6-2, 2026-10-11)

## Co robi
Wystawia API WD jako serwer MCP: trzy narzędzia read-only (`ragflow_retrieval`, `ragflow_list_datasets`,
`ragflow_list_chats`) w dwóch transportach (streamable HTTP i SSE), zgodne ze złotem upstream RAGFlow v0.27.2.
Serwer **nie importuje warstwy usług ani bazy** — woła API WD po HTTP kluczem przekazanym przez klienta, więc model
uprawnień jest identyczny jak dla klienta REST. Startuje jako `python -m app.mcp` w usłudze compose `mcp`
(profil `mcp`, domyślnie wyłączony) i jest dostępny publicznie wyłącznie przez `web`.

## Publiczny interfejs
Pakiet `backend/app/mcp/`: `__init__.py`, `__main__.py` (wejście uvicorn), `server.py` (aplikacja Starlette,
middleware auth, schematy narzędzi, `_dispatch`), `client.py` (`ApiConnector` — klient HTTP API WD).

Start: `python -m app.mcp` → `0.0.0.0:${WD_MCP_PORT:-9382}`, API WD po `WD_MCP_API_BASE` (dom. `http://api:8000/api/v1`).

| Trasa | Transport | Uwagi |
|---|---|---|
| `GET /healthz` | — | bez auth, `{"status":"ok"}` (healthcheck compose) |
| `GET/POST/DELETE /mcp` | streamable HTTP | `stateless=True`, `json_response=True` (jak upstream) |
| `GET /sse` + `POST /messages/?session_id=…` | SSE | event `endpoint` → ścieżka względna `/messages/…` (działa przez proxy `web`) |

Autoryzacja (K17 §3, dosłownie jak upstream `_extract_token_from_headers`): token z nagłówka `Authorization`
o wartości zaczynającej się od `bearer ` (bez rozróżniania wielkości), a gdy go brak — z pierwszego obecnego
z `api_key`/`x-api-key`/`Api-Key`/`X-API-Key`. Brak tokenu → **401** `application/json`
`{"error":"Missing or invalid authorization header"}` (oba transporty, także `initialize`); `/healthz` bez auth.
Middleware sprawdza tylko **obecność** tokenu — zły klucz przechodzi, a błąd wychodzi przy pierwszym wywołaniu API WD
z narzędzia (klient dostaje `McpError` z „Unauthorized”).

Narzędzia: nazwy, opisy (lista datasetów/czatów konta wstawiana dynamicznie) i `inputSchema` przeniesione z upstream.
`initialize`: `serverInfo.name = "ragflow-mcp-server"`, `serverInfo.version` = wersja pakietu `mcp`,
`capabilities.tools.listChanged = false`; błędy narzędzi nie rzucają (`isError=true`), brak narzędzia →
`Tool not found: <nazwa>`.

Compose: usługa `mcp` (obraz `wawelsky/backend`, `python -m app.mcp`) z `profiles: ["mcp"]`, port wewnętrzny 9382
bez publikacji na hoście, `read_only: true`, limit `${WD_MCP_MEM_LIMIT:-256m}`, healthcheck `/healthz`.
`web` (`frontend/serve.ts`) proxyuje `/mcp`, `/sse` i `/messages/` do `${WD_MCP_UPSTREAM:-http://mcp:9382}`
z przekazaniem nagłówków (`Authorization`, `api_key`, `X-API-Key`, `mcp-session-id`); gdy upstream nieosiągalny
(profil wyłączony) → **503** `{"error":"MCP server is not enabled (compose profile \"mcp\")"}`, a `web` działa dalej.

Zmienne `.env.example` (sekcja „MCP”, zakomentowane — czyta je compose, nie `Settings`): `WD_MCP_PORT`,
`WD_MCP_API_BASE`, `WD_MCP_MEM_LIMIT` (`mcp`) oraz `WD_MCP_UPSTREAM` (`web`).

Frontend: karta „Serwer MCP” w Ustawieniach → Klucze API (`frontend/src/features/settings/api/McpServerCard.tsx`),
scenariusz SC-E6-2-06.

## Jak uruchomić i przetestować
- Testy kontraktowe na stosie (mariadb-test + fake-llm; w całości przez `./.claude/verify.sh`):
  `cd backend && uv run --frozen pytest -q -m contract tests/contract/mcp_wd` → zielone (SC-E6-2-01…04 i 07 + 28 kroków złota; SC-05 = `frontend/serve.test.ts` i `mcp-off.spec.ts`, SC-06 = e2e `s20-mcp-card`/`s21-copy-dialog`).
- Mutacje bezpieczeństwa (K17 §5):
  `tools/dev/mutation-check.sh backend/tests/mutations/k17-no-token-check.patch tests/contract/mcp_wd/test_sc04_auth.py`
  i `tools/dev/mutation-check.sh backend/tests/mutations/k17-shared-key.patch tests/contract/mcp_wd/test_sc03_isolation.py`
  → „MUTACJA WYKRYTA” dla obu.
- Cały łańcuch klient → `web` → `mcp` → `api` na stosie prod. (clean-install, korpus PL): `bash tools/dev/mcp-prod-check.sh` (WD_CI_PROFILES=mcp + `frontend/e2e-real/mcp-prod.spec.ts` SC-01…04, 07; potem stos bez profilu + `mcp-off.spec.ts` SC-05). Nie jest wpięte w `verify-real` (wymaga zmiany `.claude/verify-real.sh` — wniosek do Architekta).
- Compose: `docker compose --profile mcp config` → 0; bez profilu usługa `mcp` nie startuje.

## Odstępstwa od docs/architecture/13-v1x.md §3
| punkt spec | co zrobiono | dlaczego (DEC/K) |
|---|---|---|
| §3.2 tryb `self-host` (`WD_MCP_HOST_API_KEY`) | nie zaimplementowany w E6-2 | K17 §3.5 — poza zakresem |
| §3.2 upstream odbija nagłówki żądania w `initialize` | `capabilities.experimental = {}` (oba transporty) — brak odbicia | wyciek klucza API; świadoma odchyłka K17 §2 (`DEVIATIONS.md`) |
| `serverInfo.version` | wersja zainstalowanego pakietu `mcp` (przypięte `mcp==1.30.0`; złoto 1.28.1) | K17 §2 — pole maskowane w porównaniu ze złotem |
| §3.1 narzędzia | bez zmian — trzy narzędzia 1:1 z upstream | — |
| `positions` chunków w `ragflow_retrieval` | różnią się od złota (korpus/parser) — porównywane bez `positions` | K17 §4, `DEVIATIONS.md` |

## Znane ograniczenia i dług
- Brak trybu `self-host`; brak rate-limitów i cache w serwerze (metadane świeżo per żądanie, brak klucza globalnego).
- `backend/app/mcp/client.py` jest na allowliście klientów HTTP (H13) — wszystkie wywołania idą kluczem per żądanie.
- Jedyna zależność runtime modułu to pakiet `mcp` (`mcp==1.30.0`, zakres upstream `mcp>=1.28.1,<2.0.0`).

## Historia
| WP | data | zmiana |
|---|---|---|
| E6-2 | 2026-10-11 | T1–T3: port serwera (`app/mcp`), proxy `web` + usługa compose `mcp`; T4: karta „Serwer MCP”; T5: testy kontraktowe ze złotem (oba transporty); T6: mutacje k17 i dokumentacja; T7/T9/T10: kopiowanie w niezabezpieczonym kontekście (HTTP) — `copyToClipboard` z fallbackiem `execCommand` (QA-UI); T8: SC-01…05, 07 przez `web` na stosie prod. |