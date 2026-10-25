# K17 — serwer MCP (M11, WP E6-2)

Status: **ZAMROŻONY** 2026-10-11 (Architekt, zmiana 26). Źródła: `docs/architecture/13-v1x.md` §3 (ZAAKCEPTOWANA, Q23 a),
`docs/contracts/golden-E6.md` §„MCP” i „Fakty dla K17”, złoto `backend/tests/contract/golden/v0.27.2/mcp/mcp--*.json`, upstream v0.27.2 `mcp/server/server.py`.
Zmiana kontraktu = wniosek do Architekta.

## 1. Usługa i wdrożenie
- Moduł `backend/app/mcp/` (pakiet), start `python -m app.mcp` (ten sam obraz `wawelsky/backend`). Nasłuch `0.0.0.0:9382` (`WD_MCP_PORT`, domyślnie 9382).
- Compose: usługa **`mcp`** w profilu **`mcp`** (domyślnie wyłączona), `depends_on: api (service_healthy)`, healthcheck `GET /healthz` → 200 `{"status":"ok"}`, limit pamięci `${WD_MCP_MEM_LIMIT:-256m}`, `read_only: true`, logowanie `*logging`. Bez portu na hoście.
- Serwer **nie importuje warstwy usług ani bazy** — woła API WD po HTTP: `WD_MCP_API_BASE` (domyślnie `http://api:8000/api/v1`), przekazując klucz klienta jako `Authorization: Bearer <klucz>` (model uprawnień identyczny z klientem REST).
- Publicznie przez `web` (`frontend/serve.ts`): ścieżki `/mcp` (GET/POST/DELETE), `/sse` (GET, strumień bez buforowania, bez limitu czasu bezczynności krótszego niż 1 h) i `/messages/` (POST, z query) → `WD_MCP_UPSTREAM` (domyślnie `http://mcp:9382`), z przekazaniem wszystkich nagłówków żądania (w tym `Authorization`, `api_key`, `X-API-Key`, `mcp-session-id`) i odpowiedzi. Gdy upstream nieosiągalny (profil wyłączony) → **503** `application/json` `{"error":"MCP server is not enabled (compose profile \"mcp\")"}`; `web` startuje i działa bez usługi `mcp`.
- Zmienne do `.env.example` (sekcja „MCP”, puste/domyślne): `WD_MCP_PORT=9382`, `WD_MCP_API_BASE=http://api:8000/api/v1`, `WD_MCP_MEM_LIMIT=256m`; `web`: `WD_MCP_UPSTREAM=http://mcp:9382`. Wpis w K8 (Architekt przenosi z raportu).

## 2. Transporty (jak upstream `create_starlette_app`, tryb `host`)
| Trasa | Transport | Uwagi |
|---|---|---|
| `GET /sse` + `POST /messages/?session_id=…` | SSE | event `endpoint` wskazuje `/messages/…` (ścieżka względna — działa przez proxy `web`) |
| `GET/POST/DELETE /mcp` | streamable HTTP | `stateless=True`, `json_response=True` (jak upstream l. 770–775) |
| `GET /healthz` | — | bez auth |
Pakiet `mcp` z PyPI: `mcp>=1.28.1,<2.0.0` (jak upstream; wersję i `pip-audit` sprawdza WP; właściciel `backend/pyproject.toml`/`uv.lock` w fali — E6-2).
`initialize`: `serverInfo.name = "ragflow-mcp-server"`; `serverInfo.version` = wersja zainstalowanego pakietu `mcp` (porównanie ze złotem: pole maskowane); `capabilities.tools.listChanged = false`.
Transport SSE w `initialize` **nie** odbija nagłówków żądania do `capabilities.experimental.headers` (upstream to robi — wyciek klucza; świadoma odchyłka, wpis w `SKIPPED.md`/odchyłkach testu kontraktu: `experimental` = `{}` dla obu transportów).

## 3. Autoryzacja (dosłownie jak upstream `_extract_token_from_headers`, `server.py:479–502`)
1. Nagłówek `Authorization` (bez rozróżniania wielkości nazwy): wartość zaczynająca się od `bearer ` (bez rozróżniania wielkości) → token = reszta.
2. Gdy brak Bearer: pierwszy obecny z `api_key`, `x-api-key`, `Api-Key`, `X-API-Key` (nazwy nagłówków HTTP są i tak case-insensitive).
3. Brak tokenu → middleware odpowiada **401** `application/json` `{"error": "Missing or invalid authorization header"}` (oba transporty, także `initialize`). `/healthz` bez auth.
4. Middleware sprawdza **tylko obecność** tokenu (jak upstream) — `initialize` ze złym kluczem przechodzi; zły klucz wychodzi przy pierwszym wywołaniu API WD z narzędzia (`list_tools` / `call_tool`) → błąd JSON-RPC (klient dostaje `McpError`, komunikat zawiera `Unauthorized`), jak złoto `--16`/`--30`.
5. Tryb `self-host` (`WD_MCP_HOST_API_KEY`) — **poza zakresem** E6-2.

## 4. Narzędzia — dokładnie jak upstream
Nazwy, opisy i `inputSchema` trzech narzędzi `ragflow_retrieval`, `ragflow_list_datasets`, `ragflow_list_chats` **przeniesione z upstream** `server.py:546–661` (opisy dynamiczne: lista datasetów/czatów konta wstawiana jak upstream, l. 549–556, 618, 641). Wyniki `call_tool` (treść `TextContent` — JSON jak upstream, w tym paginacja `page`/`page_size`, `ragflow_retrieval` bez `dataset_ids` = wszystkie datasety konta, l. 290–295) — **kształt jak złoto** `mcp--08…12`, `22…26`.
Błędy narzędzi **nie** rzucają: nieznane narzędzie → `CallToolResult(isError=true, text="Tool not found: <name>")`; walidacja `inputSchema` (SDK) → `isError=true`, `text="Input validation error: …"` (złoto `--17…19`, `--31…33`).
Plik pochodzący z upstream (port `server.py`) — komentarz atrybucji + pozycja w `docs/licensing/ragflow-provenance.md` i kategoria w `NOTICE` (konwencja E5-5).

## 5. Testy (wyrocznia E6-2)
- Kontrakt ze złotem: test w `backend/tests/contract/` uruchamia serwer MCP WD na stosie testowym i porównuje strukturalnie z `golden/v0.27.2/mcp/*.json` (maskowanie id jak golden-E6 „Uwagi ogólne”; opisy narzędzi porównywane po podstawieniu listy zasobów konta testowego), oba transporty, wszystkie kroki 06–33.
- Integracyjne przez `web` (proxy): `initialize` + `list_tools` na `http://web:8080/mcp` i `/sse`; `web` bez usługi `mcp` → 503 z treścią z §1.
- Testy negatywne bezpieczeństwa z mutacjami (`backend/tests/mutations/k17-*.patch`, `tools/dev/mutation-check.sh` → „MUTACJA WYKRYTA”): (a) brak tokenu przepuszczony przez middleware; (b) serwer używa stałego/cudzego klucza zamiast klucza klienta (narzędzie widzi datasety innego użytkownika).
- Compose: `docker compose --profile mcp config` poprawny; bez profilu usługa `mcp` nie startuje.
