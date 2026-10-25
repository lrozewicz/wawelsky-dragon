# M9 — trasy WD integracji `/api/wd/v1/integrations*` (stan po E4-3b, 2026-09-30)

## Co robi
Administrator WD (JWT lub klucz API, superuser) zarządza integracjami SharePoint przez czystą powierzchnię `/api/wd/v1`
(koperta WD, właściwe statusy HTTP), na tej samej `IntegrationService` co SVC `sharepoint-sync` (E4-3a). Trasy i schematy są
w `backend/openapi.json` i `frontend/src/api/schema.gen.ts` — podstawa UI integracji (E4-3c). Dodatkowo test połączenia
z zapisanym sekretem i link do źródła dokumentu.

## Publiczny interfejs
Pakiet `backend/app/api/wd/integrations/` (`__init__.py` → `routers`; `crud.py`, `runs.py`, `schemas.py`, `deps.py`, `errors.py`). (`WdRoute` z E4-3b usunięty w E3-6a — DEC-094.)
Montowanie: `app/main.py::include_routers`, gdy `settings.integrations_enabled`. Wszystkie trasy: `require_admin` (401 `unauthorized`, 403 `permission_denied` przez `app.domain.policy.require`), walidacja → 400 `validation_failed` (nigdy 422).

| operationId | Trasa | Status |
|---|---|---|
| `integrations_list` | GET `/integrations?page&page_size` (1..; 1..100, dom. 20) | 200 `Envelope[Page[Integration]]` |
| `integrations_create` | POST `/integrations` (`type:"sharepoint"` wymagane) | 201 |
| `integrations_test` | POST `/integrations/test` | 200 `ConnectionTest` |
| `integrations_get` / `_update` / `_delete` | GET / PATCH / DELETE `/integrations/{id}` | 200 / 200 / 204 |
| `integrations_test_saved` | POST `/integrations/{id}/test` (ciało opcjonalne, nadpisania bez zapisu) | 200 |
| `integrations_sync` | POST `/integrations/{integration_id}/sync?full&wait` | 202 `{queued:true}` / 200 `IntegrationRun` |
| `integrations_cancel` | POST `…/cancel` | 200 `{cancelled}` |
| `integrations_status` / `integrations_drives` | GET `…/status`, `…/drives` | 200 |
| `integrations_runs_list` | GET `…/runs?limit&after_id` (kursor malejący: `id < after_id`) | 200 `CursorPage[IntegrationRun]` |
| `integration_run_events` | GET `/runs/{run_id}/events?level&limit&after_id` (rosnąco, `id > after_id`) | 200 `CursorPage[IntegrationEvent]` |
| `documents_source_link` | GET `/documents/{document_id}/source-link` | 200 `SourceLink`; 404 `no_mapping`/`item_not_found`, 502 `upstream_error` |

Schematy OpenAPI dla UI: `Integration` (19 kluczy DTO SVC + `type`, `client_secret_masked`), `IntegrationRun`, `IntegrationEvent`,
`IntegrationDrive`, `IntegrationStatus`, `IntegrationLatestRun`, `ConnectionTest`, `SyncQueued`, `CancelResult`, `DriveList`, `SourceLink`,
żądania `IntegrationCreateRequest`, `IntegrationUpdateRequest`, `ConnectionTestRequest`, `SavedConnectionTestRequest`, koperty
`Envelope_<T>_`, `Page_<T>_`, `CursorPage_<T>_`, błąd `WdErrorResponse`/`WdErrorDetail`.
Usługa (dodane w E4-3b): `IntegrationCore.test_saved(integration_id, TestOverrides)` (`app/services/integration_ops.py`; bez zapisu i audytu),
`list_runs(..., before_id=None)` (usługa i `repositories/integrations/admin.py`). Aktor audytu = e-mail zalogowanego użytkownika.

## Jak uruchomić i przetestować
- `cd backend && uv run --frozen pytest -q -m contract tests/contract/wd/integrations tests/contract/hub_compat/sharepoint` (wymaga stosu: przez `./.claude/verify.sh`) → zielone, 0 skip.
- `cd frontend && bun run gen:api:check` → 0; `cd backend && uv run --frozen python -m app.api.openapi_export --check` → 0.
- Mutacje: `backend/tests/mutations/e4-3b-*.patch` przez `tools/dev/mutation-check.sh` → „MUTACJA WYKRYTA”.

## Odstępstwa od docs/architecture/02-api.md §12 / 09
| punkt spec | co zrobiono | dlaczego |
|---|---|---|
| `GET /integrations/{id}/runs`, `/runs/{id}/events` — lista | kursor `next_after_id` zamiast `{total,page}` | przebiegi rosną (decyzja Architekta w briefie) |
| 09 §10 test połączenia | dodany wariant z zapisanym sekretem (`/{id}/test`) | rozszerzenie WD |
| K3 handler walidacji wypisuje `input` błędu | od E3-6a globalny handler nie zwraca `input` (wd/domyślna); `WdRoute` usunięty | wyciek sekretu przy `missing` (DEC-082, DEC-094) |
| Zdarzenia nieistniejącego przebiegu | 200 z pustą listą (jak SVC), nie 404 | zgodność z SVC |

## Znane ograniczenia i dług
- `source-link` wymaga superusera (zgodnie z briefem) — UI czatu dla zwykłego użytkownika będzie potrzebować osobnej decyzji.
- Wyciek `input` naprawiony globalnie w E3-6a (DEC-094); `ragflow*` redaguje obiekty/listy w `Value:`.
- Paginacja listy integracji w pamięci (mała liczba integracji).

## Historia
| WP | data | zmiana |
|---|---|---|
| E4-3b | 2026-09-30 | trasy WD integracji, `test_saved`, `before_id`, `WdRoute`, OpenAPI + schema.gen.ts |
| E3-6a | 2026-09-30 | `WdRoute` usunięty, redakcja `input` w globalnym handlerze (DEC-094) |
