# M8b — hub-compat sharepoint-sync (stan po E4-3a, 2026-09-30)

## Co robi (2–3 zdania)
Powierzchnia SVC `sharepoint-sync` dla hub-compat: CRUD integracji SharePoint, test połączenia, sync/cancel/status, drives, przebiegi i zdarzenia, lista datasetów i link do dokumentu. Trasy `/api/integrations*`, `/api/datasets`, `/api/documents/link` montowane pod `""` i `/sharepoint-sync-api` (koperta `{data}`/`{error}`, `X-API-Secret`, `include_in_schema=False`), a logika żyje w `IntegrationService` (wspólnej z przyszłymi trasami WD, E4-3b).
Kontrakt: `docs/contracts/K7-hub-compat-user-api.md` część 2 (§6–§8); kontrakt wewnętrzny WP: `work/wp/E4-3a/CONTRACT.md`; decyzje: DEC-074 (w CONTRACT), DEC-075.

## Publiczny interfejs
| Element | Plik |
|---|---|
| `IntegrationService`: `list/get/create/update/delete/test_connection/sync/cancel/status/drives/list_runs/list_events/list_datasets/document_link`; DTO-y wewnętrzne `Actor`, `IntegrationView`, `StatusView`, `SyncOutcome` | `app/services/integrations.py`, `app/services/integration_ops.py` (baza `IntegrationCore`: odczyty, test połączenia, konektor z rejestru) |
| Mapowanie `ConnectionReport` → płaski DTO test-connection | `app/services/integration_test_report.py` |
| Walidacja ścisła wejścia (`parse_create/parse_update/parse_test_connection`, komunikaty 400 jak oryginał) | `app/services/integration_input.py` |
| `DocumentLinkResolver` (LRU 10 000, TTL `WD_SP_LINK_CACHE_TTL_SECONDS`, cache także negatywny; świeży mapping < 24 h bez konektora), `LinkNotFound(reason)` | `app/services/integration_links.py` |
| Repozytorium administracyjne (lista, update, delete, runs/events z filtrami, mapping po dokumencie, datasety) | `app/db/repositories/integrations/admin.py` |
| Trasy SVC, DTO (`iso_ms`, `integration_dto`, …), `install_integrations(app, settings)` (rejestracja konektora SharePoint w procesie `api` + `app.state.integrations`) | `app/api/hub_compat/sharepoint/{integrations,runs,datasets,documents,dto,setup}.py` |
| Montowanie (`hub_compat_routes` i `integrations_enabled`; `runs` przed `{id}`; health i fallback 404 pod `/sharepoint-sync-api`) | `app/api/hub_compat/__init__.py`, `app/main.py` |
| Akcje audytu `integration_created/updated/deleted/sync_requested/cancelled` (`target_type="integration"`, `details` bez sekretów) | `app/services/audit.py` |

Trasy: `GET|POST /api/integrations`, `POST /api/integrations/test-connection`, `GET /api/integrations/runs`, `GET /api/integrations/runs/{id}/events`, `GET|PUT|DELETE /api/integrations/{id}`, `POST /{id}/sync|cancel`, `GET /{id}/status|drives`, `GET /api/datasets`, `GET /api/documents/link?documentId=`.

Interfejs dla E4-3b: `IntegrationService` z `request.app.state.integrations` (tworzony w `create_app`, gdy `integrations_enabled`); aktor przekazywany jako `Actor(label, id, ip)`; wyjątki `NotFound/ValidationFailed/Conflict/UpstreamError/LinkNotFound`; widoki zwracają wiersze repozytorium (DTO JSON buduje warstwa tras).

## Jak uruchomić i przetestować
- Kontrakt: `eval "$(tools/dev/up.sh test env)" && tools/dev/up.sh test up mariadb-test fake-llm && (cd backend && uv run --frozen pytest -q -m contract tests/contract/hub_compat/sharepoint -p no:cacheprovider); tools/dev/up.sh test down` (172 testów, 0 skipped).
- Testy usługi/repozytorium/linków (DB): `tests/integration/integrations/test_{service_crud,service_ops,repo_admin,links}.py`; unit: `tests/unit/services/test_integration_input.py`, `tests/unit/api/test_sharepoint_dto.py`.
- Mutacje (każda: `MUTACJA WYKRYTA`; ścieżki testów względem `backend/`): `tools/dev/mutation-check.sh backend/tests/mutations/e4-3a-{secret-in-audit,runs-after-id,no-secret-check}.patch <testy>` (identyfikatory: `work/wp/E4-3a/reports/TL.md`).
- Wyrocznie: `./.claude/verify.sh`, `./.claude/verify-full.sh`.

## Odstępstwa od docs/architecture/03 i K7
| punkt spec | co zrobiono | dlaczego |
|---|---|---|
| walidacja pydantic `StrictStr…` (K7 §7.5) | ręczne parsery z komunikatami z oryginału (`<pole> is required and must be a non-empty string`, …) | zgodność komunikatów z `integrations.ts:144-184`; `bool` ≠ liczba |
| „Invalid JSON body” dla body nie-obiektu | 400 z komunikatem pierwszego wymaganego pola | prostsze i zgodne z oryginałem (errata TL) |
| `owner_id` integracji | `datasets.created_by` (SVC nie ma użytkownika) | K12 wymaga `owner_id` |
| `item_not_found` komunikat | „Item no longer exists in SharePoint” (09 §9), nie „Item not found in SharePoint” (oryginał) | spec 09 |
| `wait=1` | 200 z obiektem przebiegu w kształcie elementu `runs`; timeout → 202 | K7 §7.8 (oryginał zwracał wynik `runSync`) |
| typ ścieżki `{id}` | `str` parsowany ręcznie → 400 „Invalid integration id” | brak 422 |
| kolumna audytu | `audit_log.details` (nie `details_json`) | nazwa z migracji 0002 |
| typy wierszy w `app/api` | re-eksport przez `app/services/integrations.py` | DEC-075 (import-linter vs mypy) |

## Znane ograniczenia i dług
- Parametry query `limit`/`after_id` parsowane po pythonowemu — egzotyczne wejścia (`0x10`, `1_000`) różnią się od JS `Number()`.
- `test_connection` dla SharePoint robi drugie wywołanie Graph (`list_containers`) po udanym `site_resolution`, by uzyskać `drive_names` (raport konektora niesie tylko liczby).
- Scenariusz 09 §15 nie wykrywa mutacji `e4-1-delete-ignores-propagation` (domyślna propagacja true) — pokrywa ją `test_engine_decisions.py::test_row2_*`.
- Cache linków jest per proces `api` (bez unieważniania po zmianie mappingu przez worker do końca TTL).
- `test_crud.py` (kontrakt) ma 442 linie (limit 400 dotyczy `app/`).
- `WD_SP_DELETE_DOCS_ON_INTEGRATION_DELETE` audytuje flagę konfiguracji, nie liczbę skasowanych dokumentów poza `documents_deleted`.

## Historia
| WP | data | zmiana |
|---|---|---|
| E4-3a | 2026-09-30 | `IntegrationService`, trasy SVC sharepoint-sync (AG-19…27, 29…31), link do dokumentu, marker `live` testów live SharePoint |
