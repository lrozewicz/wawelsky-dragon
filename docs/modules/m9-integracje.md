# M9 — Integracje: framework konektorów (stan po E4-1, 2026-09-29)

## Co robi (2–3 zdania)
Generyczny framework synchronizacji zewnętrznych źródeł z datasetami (ADR-16): porty konektora, rejestr typów, silnik `SyncEngine` realizujący tabelę decyzji 09 §6, scheduler z atomowym lockiem w bazie (bezpieczny między replikami workera), audyt przebiegów i zdarzeń, kooperacyjne anulowanie oraz zadanie kolejki `integration_sync`. Rejestr produkcyjny jest pusty — konektor SharePoint (E4-2) i trasy HTTP/CRUD (E4-3) dochodzą później; w testach źródłem jest `FakeConnector`.
Kontrakt: `docs/contracts/K12-integracje-framework.md`; kontrakt wewnętrzny WP: `work/wp/E4-1/CONTRACT.md`.

## Publiczny interfejs
| Element | Plik |
|---|---|
| Migracja `0003_integrations` (6 tabel: `integrations`, `integration_sharepoint`, `integration_containers`, `integration_item_mappings`, `integration_sync_runs`, `integration_sync_events`), `SCHEMA_HEAD="0003"` | `backend/alembic/versions/0003_integrations.py`, `app/db/schema.py` |
| Porty: `Container` (zdalny), `RemoteItem`, `ChangeSet`, `Connector` (Protocol; `cfg: Any` wg DEC-040), `ConnectionReport`, `SyncCounts`, `RunTrigger`, `RunStatus` | `app/integrations/base.py` |
| Rejestr: `register/get/registered_types/clear`, `ConfigLoader` | `app/integrations/registry.py` |
| `IntegrationsConfig` (stałe z 09 §12, bez `Settings` — K12 §0 p. 3) | `app/integrations/config.py` |
| `RunRecorder` (start, `event`, `maybe_flush`, `flush`, `finish`; przycinanie 2000/1024 z „…”) | `app/integrations/audit.py` |
| `SyncEngine.run(integration_id, *, trigger, worker_id) -> RunOutcome \| None` (`None` = lock zajęty, bez wiersza runu) | `app/integrations/engine.py` (+ `engine_items.py` — wiersze tabeli decyzji, `engine_sync.py` — kontenery, anulowanie, reset delty, rekonsyliacja) |
| Locki: `acquire/heartbeat/release/recover_stale` (recover: run `running` → `failed` + zdarzenie `error "stale lock recovered"`) | `app/integrations/locks.py` |
| `Scheduler.tick(now_ms)` (recover → retencja zdarzeń → due sekwencyjnie), `run_forever(stop)` | `app/integrations/scheduler.py`; start jako drugi `asyncio.Task` w `app/worker/main.py::_amain` |
| Handler zadania `integration_sync` (payload `{"integration_id", "trigger": "manual"\|"full"}`; lock zajęty → sukces bez runu) | `app/worker/handlers/integration_sync.py`; rejestrowany w `create_worker` |
| `IntegrationRunsService`: `request_sync` (409 `Conflict` przy biegu), `wait_for_run`, `cancel` → `CancelResult` (09 §8 p. 1–3, także wymuszony) | `app/services/integration_runs.py` |
| Repozytorium (pakiet, 30 funkcji + 6 dataclassów; ścieżka importu `app.db.repositories.integrations`) | `app/db/repositories/integrations/{rows,core,catalog,runs}.py` |
| `DocumentIngestService.rename_document`, `set_source_meta` (K12 §4; bez zmian pliku/chunków/`run`, bez zadania parse) | `app/services/ingest.py`, `app/db/repositories/documents.py::set_meta_fields` |
| Test-double: `FakeConnector`, `fake_load_config`, `make_item` | `backend/tests/fakes/integrations.py` |

Tabela decyzji (wiersze 1–10, testy `tests/integration/integrations/test_engine_decisions.py::test_row<N>_*`): folder/skip; delete z `delete_propagation`; rozszerzenia ignorowane; za duży plik; rename bez re-parsowania; zmiana tylko `meta_tag`; upload/replace (`document_id` zachowany) z `source_type="sharepoint"`, `source_ref="<integration>:<container>:<item>"`, `meta_fields.wd_source`; błąd elementu → mapping `failed`.

## SharePoint — warstwa HTTP Graph (E4-2a, 2026-09-29)
Pakiet `app/integrations/sharepoint/`, bez `Connector` i bez DB (konektor w E4-2b). Kontrakt wewnętrzny (wiąże E4-2b): `work/wp/E4-2a/CONTRACT.md` (zawiera URL-e dokumentacji Microsoft, kształty i przykład użycia).
| Element | Plik |
|---|---|
| `GraphAuthError` (bez sekretów), `GraphError(status, code, message)`, `GraphNotFound` (404/410), `SizeLimitExceeded` | `sharepoint/errors.py` |
| `TokenProvider(http, *, tenant_id, client_id, client_secret, clock)`: cache modułowy per `(tenant, client, sha256(client_secret))` (sam sekret nigdy w kluczu; E4-H2), `POST /api/wd/v1/test/reset` woła `clear_token_cache()`, odświeżenie 60 s przed wygaśnięciem, `get_token(force_refresh)`, `invalidate`, `clear_token_cache` | `sharepoint/auth.py` |
| `make_http_client()`, `GraphClient(http, tokens, *, sleep, jitter)`: retry 429/503/504 (`Retry-After` lub backoff z jitterem, max 5), 401 → jeden refresh, `resolve_site`, `list_drives -> (containers, total_bez_system)`, `get_item`, `request_redirect`, `aclose` | `sharepoint/graph.py` |
| `decode_item(raw, drive_id) -> RemoteItem` (tolerancyjne), `iter_delta` (`ChangeSet` per strona, `cursor` tylko w ostatnim, 410 → `reset_required`, limit 10 000 stron → `GraphError deltaPageLimitExceeded`) | `sharepoint/graph_delta.py` |
| `download_item`: 302 → host docelowy bez `Authorization`, strumień do pliku, limit `max_bytes` (także po `Content-Length`), SHA-256, plik częściowy usuwany | `sharepoint/graph_download.py` |
| Redakcja query-stringów URL-i w logach loggera `httpx` (pre-signed `sig=`, `token=` w deltaLink), instalowana przez `make_http_client()` | `sharepoint/log_redact.py` |
Testy: `backend/tests/unit/integrations/sharepoint/` na `httpx.MockTransport` (bez `respx` — decyzja Architekta), fixture'y `backend/tests/fixtures/graph/*.json`; pokrycie pakietu 100%. Marker `sharepoint_live` zarejestrowany (testy live w E4-2b). Decyzja: DEC-058 (`asyncio.to_thread` dla `pathlib` flagowanego przez ASYNC240).
Uwagi z dokumentacji Graph: delta nie zwraca `parentReference.path` (dla takich elementów `path = "/<name>"`, śledzenie po `id`); nowy nextLink z nagłówka `Location` przy 410 nie jest używany — reset to pełne przejście od `cursor=None`.
Ograniczenia: 400 z nieprawidłowym tokenem delty nie jest mapowany na reset (tylko 410); nieliczbowy `expires_in` w odpowiedzi tokenu daje `TypeError` (MINOR T1).

## Jak uruchomić i przetestować
- Unit: `cd backend && uv run --frozen pytest -q tests/unit/integrations -p no:cacheprovider --cov=app/integrations --cov-report=term`.
- DB (stos testowy): `eval "$(tools/dev/up.sh test env)" && tools/dev/up.sh test up mariadb-test fake-llm && (cd backend && uv run --frozen pytest -q -p no:cacheprovider tests/integration/integrations tests/integration/db); tools/dev/up.sh test down`.
- Wyrocznie: `./.claude/verify.sh`, `./.claude/verify-full.sh`.
- Mutacje (każda: `MUTACJA WYKRYTA`): `tools/dev/mutation-check.sh backend/tests/mutations/e4-1-{lock-not-atomic,rename-reparses,delete-ignores-propagation,cancel-advances-cursor}.patch <testy>` — identyfikatory testów w `work/wp/E4-1/reports/TL.md`.
- Scenariusz przekrojowy: `tests/integration/integrations/test_scenario.py` (request_sync → worker → dokumenty → rename bez parse → delete → cancel).

## Odstępstwa od docs/architecture/09-integracje-sharepoint.md
| punkt spec | co zrobiono | dlaczego |
|---|---|---|
| kolumny `cursor`, `trigger` | `delta_cursor`, `run_trigger` | słowa zastrzeżone MariaDB (K12 §0 p. 1) |
| parametry `WD_INTEGRATIONS_*` w `Settings` | (E4-1c) 9 pól `Settings` (`WD_INTEGRATIONS_*`, `WD_SP_*`) → `IntegrationsConfig.from_settings`; `WD_SECRETS_KEY` pominięty (klucz = `WD_CRYPTO_KEY`) | Q9; heartbeat i `events_flush_*` zostają stałymi |
| `SyncEngine.run(id, full, cancel)` z tokenem | `run(id, *, trigger, worker_id)`; anulowanie przez `integrations.cancel_requested` w bazie | przebieg działa w workerze, nie w `api` (K12 §0 p. 5) |
| `Connector` bez adnotacji `cfg`/`dataset_exists` | `cfg: Any`, `dataset_exists: bool`, `resolve -> dict[str, Any]` | mypy strict; DEC-040 |
| repozytorium jako jeden moduł | pakiet 4 modułów z re-eksportem | limit 400 linii/plik (DEC-041, decyzja TL o podziale zamiast allowlisty) |
| identyfikatory `CHAR(32)` | `ascii_bin` (także `container_id`/`item_id`) | zgodność FK z `datasets.id` (K12 §0 p. 2) |

## Znane ograniczenia i dług
- Rejestr produkcyjny pusty; brak konektora SharePoint, loadera konfiguracji/sekretu (E4-2) oraz tras, CRUD i UI (E4-3).
- `wait_for_run`/`cancel` odpytują bazę co `_poll_s` (0,2 s); liczba prób = `ceil(czas/_poll_s)` (odporność na zamrożony zegar w testach).
- Generator `changes()` po `reset_required` jest porzucany bez `aclose()`; `reset_required` na stronach pełnego przejścia po resecie jest ignorowany (MINOR z przeglądu T8).
- `rename_document`/`set_source_meta` robią read-modify-write `meta_fields` poza transakcją zapisu (bezpieczne dzięki lockowi per integracja).
- Log startowy workera (`task_types`) nie wymienia `integration_sync` (MINOR T9); test `create_worker` jest pod `pytestmark=db`.
- `trim(text, 0)` zwraca tekst dłuższy niż limit — nieużywane (limity 2000/1024).

## SharePoint — konektor, sekrety, rejestracja (E4-2b, 2026-09-29)
Kontrakt: `work/wp/E4-2b/CONTRACT.md`.
- `app/core/crypto.py`: opcjonalne `aad` w `encrypt`/`decrypt` (wstecznie zgodne). `app/integrations/secrets.py`: `encrypt_secret(key, integration_id, plaintext) -> (enc, last4)` i `decrypt_secret(...)`; format `v1:<nonce_b64>:<ct+tag_b64>`, AAD `integration:<id>`, klucz `WD_CRYPTO_KEY`. Rotacja poza zakresem (E5-3).
- `sharepoint/config.py`: `SharePointConfig` (pydantic, frozen, `client_secret: SecretStr`), `IntegrationConfigError`.
- Repozytorium `app/db/repositories/integrations/sharepoint.py`: `get_sharepoint`, `upsert_sharepoint`, `delete_sharepoint`, `set_secret`, `SharePointRow` (re-eksport w pakiecie).
- `sharepoint/loader.py::make_load_config(container)`: wiersz `integrations` + `integration_sharepoint` + odszyfrowany sekret -> `SharePointConfig`; brak wiersza SP lub sekretu -> `IntegrationConfigError`.
- `sharepoint/connector.py::SharePointConnector`: `resolve`, `list_containers` (wykluczenia), `changes` (delta), `download` (zwraca rozmiar; host docelowy bez `Authorization`), `web_link` (404/410 -> `None`), `test_connection` (kroki `graph_auth` -> `site_resolution` -> `dataset_exists`, wczesny powrot po bledzie tokenu). Klient HTTP per wywolanie, zamykany w `finally`.
- Rejestracja: `sharepoint/register.py::register_sharepoint(container)`, wolane w `app/worker/main.py::create_worker` (test: rejestr niepusty).
- Testy: unit (`tests/unit/integrations/sharepoint/`), DB (`test_sharepoint_repo/loader`), scenariusz przez `SyncEngine` z symulatorem Graph (`test_sharepoint_scenario.py`: add, rename bez parse, replace, delete, 410 -> reset), live `tests/live/sharepoint/` (`tools/dev/live.sh sharepoint-live`, 4 testy). Lacki mutacji `backend/tests/mutations/e4-2b-{secret-aad,download-auth-leak,config-secret-repr}.patch`.
- Dla E4-3: `registry.get("sharepoint")`, `make_load_config`, `encrypt_secret` + `set_secret`, `upsert_sharepoint`; DTO test-connection buduje E4-3 z `ConnectionReport.checks/resolved`.

## Stub Graph (E4-3d, 2026-10-01)
Kontrakt: `work/wp/E4-3d/CONTRACT.md`; decyzje DEC-181..183.
- Konfiguracja: `Settings.sp_login_base_url` (`WD_SP_LOGIN_BASE_URL`, domyslnie `https://login.microsoftonline.com`) i `sp_graph_base_url` (`WD_SP_GRAPH_BASE_URL`, domyslnie `https://graph.microsoft.com/v1.0`); walidacja: `http(s)://`, bez koncowego `/`. Przekazywane przez `register_sharepoint` do `SharePointConnector(login_base_url, graph_base_url)` -> `TokenProvider(login_base_url)` i `make_http_client(graph_base_url)`. `SCOPE` stały. Brak ochrony SSRF w backendzie — stub dopuszczony wyłącznie konfiguracją.
- `tools/fake-graph/` (stdlib `http.server`, port 8095, obraz `wawelsky/fake-graph`, ~133 MB sumy warstw): token (`fake-graph-secret` -> `fake-graph-token`, zły sekret 401 `invalid_client`), site `sites/e2e`, dyski `Dokumenty` (`sample.pdf`, `sample.docx`, `notatka.txt`) i `Archiwum` (`arch.txt`), delta z `@odata.deltaLink` (`token=T<wersja>`, przyrost po `POST /__test/files`, `POST /__test/reset`), get_item, content 302 -> `/download/...`. Testy własne: 32 passed, pokrycie 99%; **nie ma ich w `verify-fast.sh`** (uruchamiać: `cd tools/fake-graph && uv run --frozen pytest`).
- Stos testowy: usługa `fake-graph` tylko w `docker-compose.test.yml` (bez portu hosta); `api` i `worker` dostają `WD_SP_*_BASE_URL` na `http://fake-graph:8095`.
- Testy: `backend/tests/integration/integrations/test_sharepoint_fake_graph.py` (3 testy: sync pierwszy -> 3 dokumenty, przyrost po deltaLink -> +1, zły sekret -> `graph_auth failed`; prawdziwy HTTP na stub w wątku), e2e S6-11 (`frontend/e2e/s11-integrations.spec.ts`, 2 testy: zły sekret oraz pełny cykl — test połączenia OK, wykluczenie `Archiwum`, zapis, sync `success`, 3 dokumenty w datasecie, edycja, usunięcie).
- Znane: UI po usunięciu integracji dociąga 4 trasy usuniętego zasobu (404 w konsoli; `queries.ts` `useDeleteIntegration.onSuccess` unieważnia cały prefiks) — e2e toleruje wąsko ten wzorzec; wniosek o poprawkę UI.

## Historia
| WP | data | zmiana |
|---|---|---|
| E4-1 | 2026-09-29 | framework integracji: migracja 0003, silnik, scheduler, locki, audyt, anulowanie, `integration_sync`, `IntegrationRunsService` |
| E4-1c | 2026-09-29 | 9 zmiennych `WD_INTEGRATIONS_*`/`WD_SP_*` w `Settings`, `IntegrationsConfig.from_settings` (+`enabled`, `delete_docs_on_integration_delete`, `link_cache_ttl_seconds`; dwa ostatnie czekają na konsumenta E4-3), `start_scheduler` w `worker/main.py`: `WD_INTEGRATIONS_ENABLED=false` → log `integrations disabled`, brak schedulera, handler `integration_sync` działa |
| E4-2a | 2026-09-29 | warstwa HTTP SharePoint: token, GraphClient z retry, site/drives/delta/download, redakcja logów httpx |
| E4-2b | 2026-09-29 | konektor SharePoint, sekrety AAD, repozytorium SP, loader, rejestracja, scenariusz, live |
| E4-3d | 2026-10-01 | konfigurowalne URL logowania/Graph, stub `tools/fake-graph`, compose testowy, test integracyjny na stub, e2e S6-11 pełny cykl |
| E4-H2 | 2026-10-02 | klucz cache tokenów Graph ze skrótem sekretu (zły sekret nie dostaje tokenu poprawnego), reset testowy czyści cache, mutacja `e4-h2-graph-token-cache-key`, `tools/fake-graph/coverage.xml` poza git |
